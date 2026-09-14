import sys
import os
import random
import subprocess
import argparse
import tempfile

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QVariantAnimation, QEasingCurve, QSize,
    QThread, pyqtSignal, QFileSystemWatcher
)
from PyQt6.QtGui import (
    QPixmap, QFont, QMovie, QFontDatabase, QShortcut, QKeySequence, QColor
)

from core.actions import (
    load_playlist_from_folder, play_music, pause_music,
    load_track_by_index, get_current_position_ms, get_current_track_duration_ms,
    set_volume, playlist, get_current_track_name, get_current_index, set_current_index,
    seek_to_position, register_substitute, clear_substitutes, active_rate,
    get_playback_path
)
from core.visualizer import AudioVisualizer, compute_spectrogram
from core.media import MediaDisplay, SKINS
from core.widgets import IconButton, SeekBar, VolumeBar
from core import nightcore, theme, palette as palette_mod
import pygame


# Threads que l'on n'a pas pu attendre à la fermeture (voir shutdown_workers).
# Les garder référencés ici empêche Qt de détruire un QThread encore actif —
# ce qui ferait abandonner le processus avec un « Fatal Python error ».
_ORPHANED_WORKERS = []


def _clamp_float(value, low, high):
    return max(low, min(high, float(value)))


def ms_to_mmss(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60:02}:{seconds % 60:02}"


def parse_args():
    parser = argparse.ArgumentParser(description='Lecteur de musique')
    parser.add_argument('--tiled', action='store_true', help='Mode fenêtre tiled (non flottante)')
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Travaux de fond : ils évitent que l'interface se fige.
# ---------------------------------------------------------------------------

class NightcoreWorker(QThread):
    """Fabrique le rendu nightcore d'une piste sans bloquer l'interface."""
    ready = pyqtSignal(int, str, float)
    failed = pyqtSignal(int, str)

    def __init__(self, index, src_path, ratio, parent=None):
        super().__init__(parent)
        self.index = index
        self.src_path = src_path
        self.ratio = ratio

    def run(self):
        try:
            path = nightcore.render(self.src_path, self.ratio)
            self.ready.emit(self.index, path, self.ratio)
        except Exception as exc:
            self.failed.emit(self.index, str(exc))


class SpectrogramWorker(QThread):
    """Analyse audio du visualiseur, hors du thread graphique."""
    ready = pyqtSignal(str, object)

    def __init__(self, path, nb_bandes, sample_rate, hop_length, parent=None):
        super().__init__(parent)
        self.path = path
        self.nb_bandes = nb_bandes
        self.sample_rate = sample_rate
        self.hop_length = hop_length

    def run(self):
        try:
            data = compute_spectrogram(self.path, self.nb_bandes, self.sample_rate, self.hop_length)
        except Exception as exc:
            print(f"Erreur Equalizer : {exc}")
            data = None
        self.ready.emit(self.path, data)


class MusicApp(QWidget):
    def __init__(self, tiled_mode=False):
        super().__init__()
        self.config = theme.load_config()
        self.is_playing = False
        self.is_looping = False
        self.is_shuffling = False
        self.is_muted = False
        self.is_pinned = False
        self._volume_before_mute = None
        self.track_finished = False
        self._drag_pos = None
        self.tiled_mode = tiled_mode

        # Couleurs tirées de la pochette (mode « colorize »).
        self._palette = palette_mod.NEUTRAL_PALETTE
        self._palette_anim = None

        # Nightcore
        self.nightcore_enabled = False
        self._nightcore_workers = {}
        # Plusieurs analyses peuvent tourner en parallèle si l'on enchaîne
        # les pistes : il faut toutes les connaître pour les attendre à la
        # fermeture, sinon Qt tue un QThread encore actif (abandon brutal).
        self._spectro_workers = set()
        self._pending_spectro_path = None

        self.buttons = {}
        self._button_names = []
        self._button_rows = []
        self._media_row = None
        self._main_layout = None
        self._fitting = False

        self.setup_window()
        self.setup_ui()
        self.setup_shortcuts()
        self.load_music()
        self.apply_config()

        # Rechargement à chaud : on édite dans la fenêtre de config, le lecteur
        # se met à jour immédiatement, sans redémarrage.
        self._watcher = QFileSystemWatcher(self)
        if os.path.isfile(theme.CONFIG_FILE):
            self._watcher.addPath(theme.CONFIG_FILE)
        self._watcher.fileChanged.connect(self.on_config_file_changed)

        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start()

        self.on_volume_change(self.volume_slider.value())

        if self.config.get("nightcore", {}).get("enabled_at_startup", False):
            self.on_toggle_nightcore()

        self.show()
        self.maybe_fade_in()

    # ------------------------------------------------------------------
    # Fenêtre
    # ------------------------------------------------------------------

    def setup_window(self):
        cfg = self.config.get("window", {})
        self.setWindowTitle(cfg.get("title", "Marulk"))

        if not self.tiled_mode:
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlag(Qt.WindowType.Window, True)

        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)
        self.bg_label.lower()
        self.bg_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.bg_path = cfg.get("background_image_path", "")

        # Voile coloré du mode « couleurs de la pochette » : sans lui, une
        # image de fond masquerait entièrement la teinte du morceau.
        self.tint_label = QLabel(self)
        self.tint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.tint_label.hide()

        # Voile assombrissant optionnel (section `overlay` du JSON).
        self.overlay_label = QLabel(self)
        self.overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay_label.hide()

        self.bg_movie = None

    def maybe_fade_in(self):
        anim_cfg = self.config.get("animations", {})
        target = float(self.config.get("window", {}).get("opacity", 1.0))
        if not (anim_cfg.get("enabled", True) and anim_cfg.get("window_fade_in", True)):
            self.setWindowOpacity(target)
            return
        self.setWindowOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(max(120, int(anim_cfg.get("duration", 150)) * 3))
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(target)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.start()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def make_button(self, name, callback):
        """Crée un bouton ; tout son style est appliqué par apply_config()."""
        btn = IconButton(name)
        # `click_feedback` déclenche la rotation de l'icône pour les actions qui
        # tournent (recharger, boucle, aléatoire, nightcore, support, visu).
        btn.clicked.connect(btn.click_feedback)
        btn.clicked.connect(callback)
        self.buttons[name] = btn
        self._button_names.append(name)
        return btn

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        self._main_layout = main_layout

        # --- barre de titre -------------------------------------------------
        title_bar = QHBoxLayout()
        title_bar.setSpacing(2)
        title_bar.addStretch()
        for name, cb in (
            ("config", self.launch_config_ui),
            ("search", self.launch_research_ui),
            ("reload", self.reload_playlist),
            ("minimize", self.showMinimized),
            ("close", self.close),
        ):
            title_bar.addWidget(self.make_button(name, cb))
        main_layout.addLayout(title_bar)
        self._button_rows.append(title_bar)

        # --- playlist -------------------------------------------------------
        self.list_widget = QListWidget()
        self.list_widget.clicked.connect(self.select_track)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_widget.setWordWrap(False)
        main_layout.addWidget(self.list_widget)

        # --- pochette (vinyle / CD / cassette / GIF) --------------------------
        media_row = QHBoxLayout()
        media_row.addStretch()
        self.media = MediaDisplay()
        self.media.on_clicked = self.on_media_clicked
        media_row.addWidget(self.media)
        media_row.addStretch()
        main_layout.addLayout(media_row)
        self._media_row = media_row

        main_layout.addStretch()

        # --- titre de la piste ----------------------------------------------
        self.track_label = QLabel("")
        self.track_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_label.setWordWrap(True)
        main_layout.addWidget(self.track_label)

        # --- barre de progression -------------------------------------------
        self.progress_bar = SeekBar()
        self.progress_bar.seeked.connect(self.on_seek)
        main_layout.addWidget(self.progress_bar)

        # --- temps + bascules boucle / nightcore / aléatoire ------------------
        info_row = QHBoxLayout()
        info_row.setSpacing(2)
        self.time_label = QLabel("00:00 / 00:00")
        info_row.addWidget(self.time_label)
        info_row.addStretch(1)

        # Repère visuel quand le nightcore est actif (ex. "×1.25").
        self.rate_label = QLabel("")
        self.rate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_row.addWidget(self.rate_label)

        for name, cb in (
            ("shuffle", self.on_toggle_shuffle),
            ("nightcore", self.on_toggle_nightcore),
            ("loop", self.on_toggle_loop),
        ):
            info_row.addWidget(self.make_button(name, cb))
        main_layout.addLayout(info_row)
        self._button_rows.append(info_row)

        # --- transport --------------------------------------------------------
        controls = QHBoxLayout()
        controls.setSpacing(2)
        controls.addStretch()
        for name, cb in (
            ("rewind", self.on_skip_back),
            ("play", self.on_toggle_play_pause),
            ("stop", self.on_stop),
            ("forward", self.on_skip),
        ):
            controls.addWidget(self.make_button(name, cb))
        controls.addStretch()
        main_layout.addLayout(controls)
        self._button_rows.append(controls)

        # --- volume -----------------------------------------------------------
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(4)
        volume_layout.addWidget(self.make_button("mute", self.on_toggle_mute))
        self.volume_slider = VolumeBar()
        self.volume_slider.setValue(
            int(self.config.get("volume_bar", {}).get("default_volume", 70)))
        self.volume_slider.valueChanged.connect(self.on_volume_change)
        volume_layout.addWidget(self.volume_slider)
        main_layout.addLayout(volume_layout)

        # --- bascules d'affichage ----------------------------------------------
        extras = QHBoxLayout()
        extras.setSpacing(2)
        extras.addStretch()
        for name, cb in (
            ("colorize", self.on_toggle_colorize),
            ("skin", self.on_cycle_skin),
            ("viz", self.on_cycle_visualizer),
            ("playlist", self.on_toggle_playlist),
            ("pin", self.on_toggle_pin),
        ):
            extras.addWidget(self.make_button(name, cb))
        extras.addStretch()
        main_layout.addLayout(extras)
        self._button_rows.append(extras)

        # --- visualiseur --------------------------------------------------------
        self.visualizer = AudioVisualizer()
        main_layout.addWidget(self.visualizer)

    def setup_shortcuts(self):
        """Raccourcis clavier : piloter le lecteur sans viser un bouton."""
        for keys, handler in (
            ("Space", self.on_toggle_play_pause),
            ("Right", self.on_skip),
            ("Left", self.on_skip_back),
            ("N", self.on_toggle_nightcore),
            ("L", self.on_toggle_loop),
            ("R", self.reload_playlist),
            ("C", self.launch_config_ui),
            ("Up", lambda: self.nudge_volume(+5)),
            ("Down", lambda: self.nudge_volume(-5)),
            ("S", self.on_toggle_shuffle),
            ("M", self.on_toggle_mute),
            ("X", self.on_stop),
            ("K", self.on_toggle_colorize),
            ("D", self.on_cycle_skin),
            ("V", self.on_cycle_visualizer),
            ("P", self.on_toggle_playlist),
            ("T", self.on_toggle_pin),
            ("Esc", self.close),
        ):
            QShortcut(QKeySequence(keys), self, activated=handler)

    def nudge_volume(self, delta):
        self.volume_slider.setValue(
            max(0, min(100, self.volume_slider.value() + delta)))

    # ------------------------------------------------------------------
    # Application du thème (appelée au démarrage ET à chaque sauvegarde)
    # ------------------------------------------------------------------

    def themed_config(self):
        """
        Configuration réellement appliquée.

        En mode « couleurs de la pochette », c'est la config de l'utilisateur
        repeinte à partir de la palette du morceau : ses tailles, ses formes et
        ses réglages sont conservés, seules les couleurs changent. Désactiver le
        mode restitue exactement son thème, sans rien avoir écrasé.
        """
        if self.colorize_enabled():
            return theme.derive_from_palette(self.config, self._palette)
        return self.config

    def colorize_enabled(self):
        return bool(self.config.get("colorize", {}).get("enabled", False))

    def apply_config(self):
        cfg = self.themed_config()
        win = cfg.get("window", {})
        btn_cfg = cfg.get("buttons", {})
        anim_cfg = cfg.get("animations", {})

        # Fenêtre
        width, height = win.get("width", 270), win.get("height", 450)
        self._wanted_size = (width, height)
        if self.tiled_mode:
            # Plancher volontairement bas : tout ce qui ne tient pas est rogné
            # par fit_to_window() plutôt que d'imposer une taille au WM.
            self.setMinimumSize(180, 150)
            self.setMaximumSize(16777215, 16777215)
        else:
            # La taille finale est fixée en fin d'apply_config, une fois tous
            # les widgets dimensionnés (voir fit_to_content).
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.resize(width, height)
        self.setWindowTitle(win.get("title", "Marulk"))
        self.setWindowOpacity(float(win.get("opacity", 1.0)))

        # Police
        font_path = btn_cfg.get("font_path", "")
        family = btn_cfg.get("font_family", "Arial")
        if font_path and os.path.isfile(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
        self.app_font = QFont(family, int(btn_cfg.get("font_size", 12)))
        for widget in (self.list_widget, self.track_label, self.time_label,
                       self.rate_label, self.progress_bar, self.volume_slider):
            widget.setFont(self.app_font)

        # Boutons : structure (taille, forme, animations) ; les couleurs sont
        # posées juste après par apply_colors(), qui sert aussi aux transitions.
        for name in self._button_names:
            btn = self.buttons[name]
            btn.configure(btn_cfg.get(name, {}), anim_cfg,
                          btn_cfg.get("text_color", "#FFFFFF"))
            btn.setToolTip(self.tooltip_for(name))

        # Playlist
        pl_cfg = cfg.get("playlist", {})
        pb_cfg = cfg.get("progress_bar", {})
        pl_height = int(pl_cfg.get("height", 80))
        self.list_widget.setFixedHeight(pl_height)
        self.list_widget.setVisible(pl_cfg.get("visible", True))

        # Barres
        self.progress_bar.configure(pb_cfg)
        self.progress_bar.set_playing(self.is_playing)
        self.time_label.setVisible(pb_cfg.get("show_time", True))
        self.volume_slider.configure(cfg.get("volume_bar", {}))

        # Visualiseur
        self.visualizer.configure(cfg)

        # Fond + voile
        self.bg_path = win.get("background_image_path", "")
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        self.update_background()
        self.update_overlay()

        # Pochette
        self.media.configure(cfg)
        self.media.set_rate(active_rate())
        self.media.set_playing(self.is_playing)
        self.media.set_progress(get_current_position_ms(), get_current_track_duration_ms())

        self.apply_colors(cfg)
        self.refresh_state_indicators()
        self.fit_to_content()

    def apply_colors(self, cfg=None):
        """
        Ne pose que les couleurs.

        Chemin rapide des transitions de palette : rejouer apply_config() trente
        fois par seconde re-dimensionnerait tous les widgets et relancerait le
        layout à chaque image. Ici, rien ne bouge, tout se teinte.
        """
        cfg = cfg or self.themed_config()
        win = cfg.get("window", {})
        btn_cfg = cfg.get("buttons", {})
        pb_cfg = cfg.get("progress_bar", {})
        vol_cfg = cfg.get("volume_bar", {})
        viz_cfg = cfg.get("visualizer", {})

        bg_color = win.get("background_color", "#9141ac")
        self.setObjectName("root")
        self.setStyleSheet(f"QWidget#root {{ background-color: {bg_color}; }}")
        self.setAutoFillBackground(True)
        qt_palette = QWidget.palette(self)
        qt_palette.setColor(self.backgroundRole(), QColor(bg_color))
        self.setPalette(qt_palette)

        accent = pb_cfg.get("color", "#ffffff")
        default_text = btn_cfg.get("text_color", "#FFFFFF")
        for name in self._button_names:
            one = btn_cfg.get(name, {})
            self.buttons[name].apply_colors(
                background=one.get("color", "#613583"),
                foreground=one.get("text_color") or default_text,
                accent=accent)

        self.list_widget.setStyleSheet(
            theme.playlist_qss(cfg.get("playlist", {}), pb_cfg))

        text_on_bg = theme.readable_text_on(bg_color)
        for widget in (self.track_label, self.time_label, self.rate_label):
            widget.setStyleSheet(f"color: {text_on_bg}; background: transparent;")

        self.progress_bar.apply_colors(
            fill=pb_cfg.get("color", "#d09dd2"),
            track=pb_cfg.get("background_color", "#350b4a"),
            accent=accent)
        self.volume_slider.apply_colors(
            fill=vol_cfg.get("slider_color", "#ffffff"),
            track=vol_cfg.get("background_color", "#62a0ea"),
            accent=vol_cfg.get("slider_color", "#ffffff"))
        self.visualizer.apply_colors(viz_cfg.get("color_start", "#ffffff"),
                                     viz_cfg.get("color_end", "#ffffff"))
        self.media.configure(cfg)
        self.update_tint(bg_color)

    def update_tint(self, color):
        """Voile coloré posé sur l'image de fond en mode couleurs de la pochette."""
        if not (self.colorize_enabled() and self.bg_path
                and os.path.isfile(self.bg_path)):
            self.tint_label.hide()
            return
        strength = float(self.config.get("colorize", {}).get("strength", 0.9))
        self.tint_label.setStyleSheet(
            f"background-color: {theme.rgba(color, 0.30 + 0.35 * strength)};")
        self.tint_label.setGeometry(0, 0, self.width(), self.height())
        self.tint_label.show()
        # Ordre d'empilement : image de fond, voile, puis les contrôles.
        self.bg_label.lower()
        self.tint_label.stackUnder(self.overlay_label)
        self.bg_label.lower()

    # ------------------------------------------------------------------
    # Couleurs tirées de la pochette
    # ------------------------------------------------------------------

    def refresh_palette(self, animate=None):
        """
        Recalcule la palette depuis la pochette et la fait glisser en douceur.

        Sauter d'une palette à l'autre au changement de piste donne un flash
        désagréable ; on interpole donc l'ancienne vers la nouvelle.
        """
        if not self.colorize_enabled():
            return
        target = self.media.cover_palette()
        section = self.config.get("colorize", {})
        if animate is None:
            animate = section.get("animate", True)

        if self._palette_anim is not None:
            self._palette_anim.stop()
            self._palette_anim = None

        if not animate:
            self._palette = target
            self.apply_colors()
            return

        origin = self._palette
        anim = QVariantAnimation(self)
        anim.setDuration(650)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(
            lambda t, a=origin, b=target: self._blend_palette(a, b, float(t)))
        anim.finished.connect(lambda: self.apply_colors())
        self._palette_anim = anim
        anim.start()

    def _blend_palette(self, origin, target, t):
        self._palette = palette_mod.blend_palettes(origin, target, t)
        self.apply_colors()

    def fit_to_content(self):
        """
        Garde la taille demandée, mais l'agrandit si le contenu ne tient pas :
        sans ça, activer une pochette de 120 px écrasait le disque au lieu de
        faire de la place.
        """
        if self.tiled_mode:
            # Ici la taille vient du gestionnaire de fenêtres : c'est le
            # contenu qui doit céder, pas la fenêtre.
            self.fit_to_window()
            return
        width, height = self._wanted_size
        layout = self.layout()
        layout.activate()
        needed = layout.minimumSize()
        self.setFixedSize(max(width, needed.width()), max(height, needed.height()))
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        self.update_background()

    # Planchers en dessous desquels un élément n'apporte plus rien : on le
    # masque plutôt que d'afficher une bande illisible.
    MIN_PLAYLIST = 46
    MIN_MEDIA = 44
    MIN_VIZ = 22

    def fit_to_window(self):
        """
        Fait entrer le contenu dans la fenêtre imposée (mode tiled).

        Une fenêtre pavée — carrée, typiquement — ne fait pas la taille
        demandée dans le JSON. Comme la playlist, la pochette et le visualiseur
        ont chacun une hauteur fixe, leur somme dépassait la fenêtre : Qt
        n'ayant plus de place à distribuer, les rangées finissaient
        superposées. On répartit donc la hauteur réellement disponible, en
        rognant dans cet ordre : visualiseur, playlist, pochette.
        """
        if self._fitting or self._main_layout is None:
            return
        self._fitting = True
        try:
            self._fit_width()
            self._fit_height()
        finally:
            self._fitting = False

    def _fit_width(self):
        """Rétrécit les boutons si la rangée la plus large déborde."""
        margins = self._main_layout.contentsMargins()
        avail = self.width() - margins.left() - margins.right()
        if avail <= 0 or not self._button_rows:
            return
        first = self.buttons.get(self._button_names[0]) if self._button_names else None
        scale = first.size_scale() if first is not None else 1.0
        widest = max(row.sizeHint().width() for row in self._button_rows)
        full = widest / max(0.5, scale)
        target = _clamp_float(avail / max(1.0, full), 0.5, 1.0)
        for btn in self.buttons.values():
            btn.set_size_scale(target)

    def _fit_height(self):
        """Répartit la hauteur disponible entre playlist, pochette et visu."""
        layout = self._main_layout
        margins = layout.contentsMargins()
        avail = self.height()
        if avail <= 0:
            return

        cfg = self.themed_config()
        pl_cfg, viz_cfg, media_cfg = (cfg.get("playlist", {}), cfg.get("visualizer", {}),
                                      cfg.get("media", {}))
        want_pl = int(pl_cfg.get("height", 80)) if pl_cfg.get("visible", True) else 0
        want_viz = int(viz_cfg.get("height", 120)) if viz_cfg.get("enabled", True) else 0
        want_media = int(media_cfg.get("size", 120)) \
            if media_cfg.get("skin", "vinyl") != "none" else 0

        # Deux passes : le mode serré des barres libère quelques pixels, qui
        # changent à leur tour le verdict sur la pochette et le visualiseur.
        for compact in (False, True):
            self.progress_bar.set_compact(compact)
            self.volume_slider.set_compact(compact)
            free = avail - self._fixed_height()
            if free >= want_pl + want_media + want_viz or compact:
                break

        pl, media, viz = self._shrink(free, want_pl, want_media, want_viz)

        self.list_widget.setVisible(bool(pl))
        if pl:
            self.list_widget.setFixedHeight(pl)
        self.visualizer.setVisible(bool(viz) and viz_cfg.get("enabled", True))
        if viz:
            self.visualizer.setFixedHeight(viz)
        self.media.apply_size(media)
        # Une cassette est plus large que haute : elle peut dépasser en largeur
        # même quand la hauteur convient.
        room = self.width() - margins.left() - margins.right()
        if media and self.media.width() > room:
            self.media.apply_size(int(media * room / max(1, self.media.width())))

    def _shrink(self, free, want_pl, want_media, want_viz):
        """
        Répartit `free` pixels entre les trois éléments souples.

        Deux temps : chacun reçoit d'abord son plancher, par ordre de priorité
        (pochette, playlist, visualiseur) — celui qui n'a plus la place de
        tenir son plancher est simplement retiré ; le reste est ensuite rendu
        proportionnellement à ce qui manque encore à chacun, pour ne pas
        laisser de vide sous prétexte qu'un voisin a disparu.
        """
        wants = {"media": want_media, "pl": want_pl, "viz": want_viz}
        floors = {"media": self.MIN_MEDIA, "pl": self.MIN_PLAYLIST, "viz": self.MIN_VIZ}
        order = ("media", "pl", "viz")

        if sum(wants.values()) <= free:
            return want_pl, want_media, want_viz

        sizes = dict.fromkeys(order, 0)
        left = max(0, free)
        for key in order:
            floor = min(floors[key], wants[key])
            if wants[key] and left >= floor:
                sizes[key] = floor
                left -= floor

        for key in order:
            if not sizes[key] or left <= 0:
                continue
            give = min(left, wants[key] - sizes[key])
            sizes[key] += give
            left -= give

        return sizes["pl"], sizes["media"], sizes["viz"]

    def _fixed_height(self):
        """
        Hauteur du contenu incompressible : tout sauf les trois souples.

        On part du minimum du layout — lui seul connaît exactement les marges,
        les espacements et les rangées masquées — et on en retire ce que les
        éléments souples y apportent aujourd'hui.
        """
        layout = self._main_layout
        layout.activate()
        total = layout.minimumSize().height()
        for widget in (self.list_widget, self.media, self.visualizer):
            if not widget.isHidden():
                total -= widget.height()
        return max(0, total)

    def tooltip_for(self, name):
        ratio = self.nightcore_ratio()
        tips = {
            "play": "Lecture / Pause  (Espace)",
            "rewind": "Piste précédente  (←)",
            "forward": "Piste suivante  (→)",
            "stop": "Arrêter et revenir au début  (X)",
            "shuffle": "Lecture aléatoire  (S)",
            "loop": "Répéter la piste  (L)",
            "nightcore": (f"Nightcore ×{ratio:g}  —  +{nightcore.ratio_to_semitones(ratio):.1f} "
                          f"demi-tons  (N)"),
            "mute": "Couper / rétablir le son  (M)",
            "colorize": "Couleurs tirées de la pochette  (K)",
            "skin": "Changer de support : vinyle, CD, cassette…  (D)",
            "viz": "Style du visualiseur  (V)",
            "playlist": "Afficher / masquer la playlist  (P)",
            "pin": "Garder la fenêtre au-dessus  (T)",
            "config": "Personnaliser l'interface  (C)",
            "search": "Télécharger un morceau",
            "reload": "Recharger la playlist  (R)",
            "minimize": "Réduire",
            "close": "Fermer  (Échap)",
        }
        return tips.get(name, theme.BUTTON_LABELS.get(name, name))

    def refresh_state_indicators(self):
        """
        Reflète l'état du lecteur sur les boutons.

        Chaque bascule active porte son liseré d'accent et son battement lent
        (géré par IconButton), et les boutons dont l'icône a deux états en
        changent : lecture/pause, boucle/boucle-unique, son/muet.
        """
        states = {
            "loop": self.is_looping,
            "nightcore": self.nightcore_enabled,
            "shuffle": self.is_shuffling,
            "mute": self.is_muted,
            "pin": self.is_pinned,
            "colorize": self.colorize_enabled(),
            "playlist": self.config.get("playlist", {}).get("visible", True),
        }
        for name, active in states.items():
            if name in self.buttons:
                self.buttons[name].set_active(bool(active))

        self.buttons["play"].set_icon_name("pause" if self.is_playing else "play")
        self.buttons["loop"].set_icon_name("loop_one" if self.is_looping else "loop")
        self.buttons["mute"].set_icon_name(
            "mute" if (self.is_muted or self.volume_slider.value() == 0) else "volume")

        if self.nightcore_enabled:
            rate = active_rate()
            # "…" tant que le rendu tourne : l'attente est visible, pas subie.
            self.rate_label.setText(f"×{rate:g}" if rate > 1.0 else "…")
        else:
            self.rate_label.setText("")

    # ------------------------------------------------------------------
    # Bascules d'affichage
    # ------------------------------------------------------------------

    def persist(self):
        """
        Enregistre config.json depuis le lecteur (changement de support, de
        visualiseur…) pour que le choix survive au redémarrage.

        Le QFileSystemWatcher va voir passer notre propre écriture ; c'est
        _reload_config qui la reconnaît et ne reconstruit rien pour rien.
        """
        try:
            theme.save_config(self.config)
        except Exception as exc:
            print(f"⚠️  Impossible d'enregistrer la configuration : {exc}")

    def on_toggle_colorize(self):
        section = self.config.setdefault("colorize", {})
        section["enabled"] = not section.get("enabled", False)
        if section["enabled"]:
            # On part de la palette neutre pour que la teinte arrive en fondu.
            self._palette = palette_mod.NEUTRAL_PALETTE
            self.apply_config()
            self.refresh_palette()
        else:
            self.apply_config()
        self.persist()
        print(f"🎨 Couleurs de la pochette : {'activées' if section['enabled'] else 'désactivées'}")

    def on_cycle_skin(self):
        cfg = self.config.setdefault("media", {})
        order = [s for s in SKINS if s != "none"]
        try:
            index = order.index(cfg.get("skin", "vinyl"))
        except ValueError:
            index = -1
        cfg["skin"] = order[(index + 1) % len(order)]
        self.apply_config()
        self.media.play_insert()
        self.persist()

    def on_cycle_visualizer(self):
        cfg = self.config.setdefault("visualizer", {})
        styles = ["bars", "wave", "circle"]
        try:
            index = styles.index(cfg.get("style", "bars"))
        except ValueError:
            index = -1
        cfg["style"] = styles[(index + 1) % len(styles)]
        self.visualizer.configure(self.themed_config())
        # configure() repose la hauteur du JSON : on refait la répartition,
        # sinon le visualiseur repousse les contrôles en mode tiled.
        self.fit_to_content()
        self.persist()

    def on_toggle_playlist(self):
        cfg = self.config.setdefault("playlist", {})
        cfg["visible"] = not cfg.get("visible", True)
        self.list_widget.setVisible(cfg["visible"])
        self.refresh_state_indicators()
        self.fit_to_content()
        self.persist()

    def on_toggle_pin(self):
        """Toujours au-dessus : utile quand le lecteur sert de widget de bureau."""
        self.is_pinned = not self.is_pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
        self.refresh_state_indicators()
        self.show()  # changer un flag masque la fenêtre : il faut la remontrer

    def on_config_file_changed(self, path):
        """La fenêtre de configuration vient d'enregistrer : on applique."""
        QTimer.singleShot(120, self._reload_config)
        # Une écriture atomique remplace le fichier : il faut se réabonner.
        if path not in self._watcher.files() and os.path.isfile(path):
            self._watcher.addPath(path)

    def _reload_config(self):
        loaded = theme.load_config()
        if loaded == self.config:
            # Écriture venue du lecteur lui-même (bascule support, visualiseur,
            # couleurs auto…) : l'interface est déjà à jour. Comparer le contenu
            # plutôt que poser un drapeau temporel évite de rater, dans la
            # foulée, une vraie sauvegarde faite depuis la fenêtre de config.
            return
        self.config = loaded
        self.apply_config()
        if not self._watcher.files() and os.path.isfile(theme.CONFIG_FILE):
            self._watcher.addPath(theme.CONFIG_FILE)
        print("🎨 Configuration rechargée à chaud")

    # ------------------------------------------------------------------
    # Nightcore
    # ------------------------------------------------------------------

    def nightcore_ratio(self):
        return nightcore.clamp_ratio(
            self.config.get("nightcore", {}).get("ratio", nightcore.DEFAULT_RATIO))

    def on_toggle_nightcore(self):
        if not playlist:
            return
        self.nightcore_enabled = not self.nightcore_enabled

        if self.nightcore_enabled:
            self.refresh_state_indicators()
            self.request_nightcore(get_current_index(), apply_now=True)
        else:
            clear_substitutes()
            self.swap_current_source()
            self.refresh_state_indicators()
            print("🌙 Nightcore désactivé")

    def request_nightcore(self, index, apply_now=False):
        """Lance (si besoin) le rendu nightcore d'une piste."""
        if not (0 <= index < len(playlist)):
            return
        if active_rate(index) > 1.0:
            if apply_now:
                self.swap_current_source()
            return
        if index in self._nightcore_workers:
            return

        ratio = self.nightcore_ratio()
        worker = NightcoreWorker(index, playlist[index], ratio, self)
        worker.ready.connect(
            lambda i, p, r, now=apply_now: self.on_nightcore_ready(i, p, r, now))
        worker.failed.connect(self.on_nightcore_failed)
        worker.finished.connect(lambda i=index: self._nightcore_workers.pop(i, None))
        self._nightcore_workers[index] = worker
        worker.start()

    def on_nightcore_ready(self, index, path, ratio, apply_now):
        register_substitute(index, path, ratio)
        semis = nightcore.ratio_to_semitones(ratio)
        print(f"🌙 Nightcore prêt (×{ratio:g}, +{semis:.2f} demi-tons) : "
              f"{os.path.basename(playlist[index])}")

        if apply_now and index == get_current_index() and self.nightcore_enabled:
            self.swap_current_source()
        self.refresh_state_indicators()

        # Prépare la piste suivante pendant qu'on écoute celle-ci.
        # Uniquement depuis la piste courante : sinon chaque rendu terminé
        # déclencherait le suivant et on rendrait toute la playlist d'un coup.
        if (self.nightcore_enabled
                and index == get_current_index()
                and self.config.get("nightcore", {}).get("auto_render_next", True)
                and len(playlist) > 1):
            self.request_nightcore((index + 1) % len(playlist))

    def on_nightcore_failed(self, index, message):
        print(f"⚠️  Nightcore impossible pour {os.path.basename(playlist[index])} : {message}")
        if index == get_current_index():
            self.nightcore_enabled = False
            self.refresh_state_indicators()

    def swap_current_source(self):
        """
        Bascule entre le fichier original et son rendu nightcore en conservant
        la position d'écoute (proportionnellement, les timelines diffèrent).
        """
        index = get_current_index()
        if not (0 <= index < len(playlist)):
            return

        old_duration = get_current_track_duration_ms()
        position = get_current_position_ms()
        fraction = (position / old_duration) if old_duration > 0 else 0.0

        was_playing = self.is_playing
        load_track_by_index(index)
        new_duration = get_current_track_duration_ms()
        target = int(fraction * new_duration)

        seek_to_position(target)
        if not was_playing:
            pause_music()

        self.track_finished = False
        self.load_spectrogram(get_playback_path(index))
        self.media.set_rate(active_rate())
        self.refresh_state_indicators()

    # ------------------------------------------------------------------
    # Playlist / lecture
    # ------------------------------------------------------------------

    def launch_config_ui(self):
        subprocess.Popen([sys.executable, "config_ui.py"])

    def launch_research_ui(self):
        subprocess.Popen([sys.executable, "research.py"])

    def load_spectrogram(self, path):
        """Analyse la piste pour le visualiseur, dans un thread de fond."""
        if not path or not self.visualizer.enabled:
            self.visualizer.set_spectrogram(None)
            return
        self._pending_spectro_path = path
        self.visualizer.set_spectrogram(None)
        worker = SpectrogramWorker(
            path, self.visualizer.nb_bandes,
            self.visualizer.sample_rate, self.visualizer.hop_length, self)
        worker.ready.connect(self.on_spectrogram_ready)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self._spectro_workers.discard(w))
        self._spectro_workers.add(worker)
        worker.start()

    def on_spectrogram_ready(self, path, data):
        # Une piste a pu être changée entre-temps : on ignore les résultats périmés.
        if path == self._pending_spectro_path:
            self.visualizer.set_spectrogram(data)

    def goto_index(self, index):
        """Point d'entrée unique pour changer de piste."""
        if not playlist:
            return
        index %= len(playlist)
        set_current_index(index)
        if self.nightcore_enabled:
            self.request_nightcore(index)
        load_track_by_index(index)
        self.track_finished = False
        self.list_widget.setCurrentRow(index)
        self.update_track_label()
        self.load_spectrogram(get_playback_path(index))
        self.media.set_rate(active_rate())
        self.media.play_insert()
        if self.is_playing:
            play_music()
        self.set_playing(self.is_playing)

    def reload_playlist(self):
        """Recharge la playlist sans fermer l'application"""
        print("🔄 Rechargement de la playlist...")
        was_playing = self.is_playing
        current_track = get_current_track_name()

        music_dir = os.path.join(os.getcwd(), "assets", "music")
        load_playlist_from_folder(music_dir)
        clear_substitutes()

        self.list_widget.clear()
        for path in playlist:
            self.list_widget.addItem(os.path.basename(path))

        if playlist:
            try:
                current_path = os.path.join(music_dir, current_track) if current_track else None
                idx = playlist.index(current_path) if current_path in playlist else 0
            except (ValueError, TypeError):
                idx = 0
            self.is_playing = was_playing
            self.goto_index(idx)
        else:
            self.track_label.setText("Aucune musique trouvée")
        print("✅ Playlist rechargée")

    def load_music(self):
        music_dir = os.path.join(os.getcwd(), "assets", "music")
        os.makedirs(music_dir, exist_ok=True)
        load_playlist_from_folder(music_dir)
        self.list_widget.clear()
        for path in playlist:
            self.list_widget.addItem(os.path.basename(path))
        if playlist:
            self.goto_index(0)
        else:
            self.track_label.setText("Aucune musique trouvée")

    def update_track_label(self):
        name = get_current_track_name()
        self.track_label.setText(name or "Aucune musique")
        self.set_media_art(name)

    def update_progress(self):
        pos = get_current_position_ms()
        dur = get_current_track_duration_ms()
        self.progress_bar.set_progress(pos, dur)
        if dur > 0:
            self.time_label.setText(f"{ms_to_mmss(pos)} / {ms_to_mmss(dur)}")

            if pos >= dur - 500:
                if self.is_looping:
                    seek_to_position(0)
                    pygame.mixer.music.play(loops=-1)
                    self.track_finished = False
                    self.set_playing(True)
                elif not self.track_finished:
                    self.track_finished = True
                    self.on_skip()
            elif pos < dur - 1000:
                self.track_finished = False
        else:
            self.time_label.setText("00:00 / 00:00")

        self.visualizer.update_visualizer(pos)
        self.media.set_progress(pos, dur)

    def on_seek(self, position_ms):
        """Clic ou glissé sur la barre de progression."""
        seek_to_position(int(position_ms))
        if not self.is_playing:
            pause_music()
        self.track_finished = False

    def select_track(self, index):
        self.goto_index(index.row())

    def set_playing(self, playing):
        """Point unique de vérité : l'état de lecture et son reflet visuel."""
        self.is_playing = bool(playing)
        self.media.set_playing(self.is_playing)
        self.progress_bar.set_playing(self.is_playing)
        self.refresh_state_indicators()

    def on_toggle_play_pause(self):
        if not playlist:
            return
        if self.is_playing:
            pause_music()
            self.set_playing(False)
        else:
            pos = get_current_position_ms()
            dur = get_current_track_duration_ms()
            if pos >= dur or pos == 0:
                seek_to_position(0)
                pygame.mixer.music.play(loops=-1 if self.is_looping else 0)
            else:
                play_music()
            self.set_playing(True)

    def on_media_clicked(self):
        """Cliquer la pochette lance ou met en pause."""
        if self.config.get("media", {}).get("click_toggles_play", True):
            self.on_toggle_play_pause()

    def on_stop(self):
        """Arrêt franc : on coupe et on revient au début de la piste."""
        if not playlist:
            return
        pause_music()
        seek_to_position(0)
        pause_music()
        self.track_finished = False
        self.set_playing(False)
        self.progress_bar.set_progress(0, get_current_track_duration_ms())

    def next_index(self):
        """Piste suivante : l'aléatoire évite de retomber sur la même."""
        if self.is_shuffling and len(playlist) > 1:
            choices = [i for i in range(len(playlist)) if i != get_current_index()]
            return random.choice(choices)
        return get_current_index() + 1

    def on_skip_back(self):
        self.goto_index(get_current_index() - 1)

    def on_skip(self):
        self.goto_index(self.next_index())

    def on_toggle_loop(self):
        self.is_looping = not self.is_looping
        self.refresh_state_indicators()

    def on_toggle_shuffle(self):
        self.is_shuffling = not self.is_shuffling
        self.refresh_state_indicators()

    def on_toggle_mute(self):
        """Coupe le son en mémorisant le niveau, pour le rendre tel quel."""
        if self.is_muted:
            self.is_muted = False
            if self._volume_before_mute is not None:
                self.volume_slider.setValue(self._volume_before_mute)
            self.on_volume_change(self.volume_slider.value())
        else:
            self._volume_before_mute = self.volume_slider.value() or 70
            self.is_muted = True
            set_volume(0.0)
        self.refresh_state_indicators()

    def on_volume_change(self, value):
        # Bouger le volume à la main lève naturellement la coupure.
        if self.is_muted and value > 0:
            self.is_muted = False
        set_volume(0.0 if self.is_muted else value / 100)
        self.buttons["mute"].setToolTip(f"Volume : {value} %  (M pour couper)")
        self.refresh_state_indicators()

    # ------------------------------------------------------------------
    # Fenêtre : déplacement, fond, voile
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if not self.tiled_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition()

    def mouseMoveEvent(self, event):
        if not self.tiled_mode and self._drag_pos:
            diff = event.globalPosition() - self._drag_pos
            self.move(int(self.x() + diff.x()), int(self.y() + diff.y()))
            self._drag_pos = event.globalPosition()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def enterEvent(self, event):
        if self.config.get("overlay", {}).get("show_on_hover", False):
            self.overlay_label.show()
            self.overlay_label.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.overlay_label.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.tiled_mode:
            # Le gestionnaire de fenêtres impose la taille : on réajuste le
            # contenu à chaque changement de pavage.
            self.fit_to_window()
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        self.tint_label.setGeometry(0, 0, self.width(), self.height())
        self.overlay_label.setGeometry(0, 0, self.width(), self.height())
        self.update_background()

    def update_overlay(self):
        ov = self.config.get("overlay", {})
        self.overlay_label.setGeometry(0, 0, self.width(), self.height())
        self.overlay_label.setStyleSheet(
            f"background-color: {theme.rgba(ov.get('color', '#000000'), ov.get('opacity', 0.8))};")
        if not ov.get("show_on_hover", False):
            self.overlay_label.hide()

    def update_background(self):
        """Met à jour le fond pour qu'il remplisse toute la fenêtre"""
        if not (self.bg_path and os.path.isfile(self.bg_path)):
            self.bg_label.clear()
            return

        width, height = self.width(), self.height()
        if self.bg_path.lower().endswith('.gif'):
            if self.bg_movie:
                self.bg_movie.stop()
            self.bg_movie = QMovie(self.bg_path)
            self.bg_movie.setScaledSize(QSize(width, height))
            self.bg_label.setMovie(self.bg_movie)
            self.bg_movie.start()
        else:
            self.bg_label.setPixmap(QPixmap(self.bg_path).scaled(
                width, height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_media_art(self, track_name):
        """
        Alimente la pochette. Ordre de repli : le GIF jumeau du morceau, puis
        une image de même nom, puis la pochette intégrée aux tags ID3, puis une
        pochette générée à partir du titre — pour qu'aucune piste ne reste nue.
        """
        if not track_name:
            return
        base = os.path.splitext(track_name)[0]
        music_dir = os.path.join(os.getcwd(), "assets", "music")

        gif_path = os.path.join(music_dir, f"{base}.gif")
        image_path = ""
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = os.path.join(music_dir, base + ext)
            if os.path.isfile(candidate):
                image_path = candidate
                break
        if not image_path:
            image_path = self.extract_embedded_cover(
                os.path.join(music_dir, track_name), base)

        self.media.set_art(gif_path=gif_path, image_path=image_path,
                           track_name=base)
        # Un GIF n'a pas encore décodé sa première image à cet instant : on
        # laisse passer un tour d'événements avant d'en tirer les couleurs.
        QTimer.singleShot(60, self.refresh_palette)

    def extract_embedded_cover(self, mp3_path, base):
        """Extrait la pochette ID3 vers un fichier temporaire, si elle existe."""
        try:
            from mutagen.id3 import ID3
            pictures = ID3(mp3_path).getall("APIC")
            if not pictures:
                return ""
            cache_dir = os.path.join(tempfile.gettempdir(), "marulk_covers")
            os.makedirs(cache_dir, exist_ok=True)
            out = os.path.join(cache_dir, f"{abs(hash(base))}.img")
            if not os.path.isfile(out):
                with open(out, "wb") as f:
                    f.write(pictures[0].data)
            return out
        except Exception:
            return ""

    def shutdown_workers(self):
        """Attend la fin des threads de fond avant de rendre la main."""
        workers = list(self._nightcore_workers.values()) + list(self._spectro_workers)
        for worker in workers:
            try:
                if not worker.isRunning():
                    continue
                # On coupe d'abord les signaux : plus aucun callback ne doit
                # atteindre une interface en cours de destruction.
                worker.blockSignals(True)
                if not worker.wait(5000):
                    # librosa et ffmpeg ne s'interrompent pas : un gros fichier
                    # peut dépasser le délai. On détache alors le thread de la
                    # fenêtre pour que Qt ne le détruise pas en pleine course ;
                    # il s'éteindra avec le processus.
                    worker.setParent(None)
                    _ORPHANED_WORKERS.append(worker)
            except RuntimeError:
                pass  # déjà détruit côté Qt
        self._nightcore_workers.clear()
        self._spectro_workers.clear()

    def closeEvent(self, event):
        self.timer.stop()
        self.shutdown_workers()
        super().closeEvent(event)


if __name__ == "__main__":
    args = parse_args()
    pygame.mixer.init()
    app = QApplication(sys.argv)
    window = MusicApp(tiled_mode=args.tiled)
    app.aboutToQuit.connect(window.shutdown_workers)
    sys.exit(app.exec())
