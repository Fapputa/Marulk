"""
Fenêtre de personnalisation de Marulk.

Principes de l'interface :
  * navigation par sections à gauche, plus de scroll interminable ;
  * aperçu en direct à droite, construit avec les MÊMES fonctions de style que
    le lecteur (core/theme.py) : ce qu'on voit est ce qu'on obtient ;
  * chaque réglage s'applique immédiatement à l'aperçu, et l'option
    « appliquer en direct » propage au lecteur déjà ouvert (il surveille
    config.json et se recharge tout seul).
"""

import os
import sys

import numpy as np
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QFont, QMovie, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QColorDialog, QComboBox, QSpinBox, QFileDialog, QSlider,
    QCheckBox, QListWidget, QListWidgetItem, QStackedWidget, QLineEdit,
    QScrollArea, QFrame, QProgressBar, QMessageBox
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import theme, nightcore, icons, palette as palette_mod
from core.visualizer import AudioVisualizer
from core.media import MediaDisplay, SKINS, SKIN_LABELS
from core.widgets import IconButton, SeekBar, VolumeBar

CONFIG_FILE = theme.CONFIG_FILE

# Styles de remplissage partagés par les deux barres.
BAR_STYLES = ["gradient", "glass", "neon", "segments", "flat"]

# Palette de la fenêtre de configuration (indépendante du thème du lecteur).
UI_BG = "#16161e"
UI_PANEL = "#1e1e28"
UI_PANEL_2 = "#262633"
UI_TEXT = "#e6e6f0"
UI_MUTED = "#9a9ab0"
UI_ACCENT = "#a06bd4"
UI_BORDER = "#32323f"

STYLESHEET = f"""
QWidget {{
    background-color: {UI_BG};
    color: {UI_TEXT};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 20px; font-weight: 600; }}
QLabel#subtitle {{ color: {UI_MUTED}; font-size: 12px; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 600; padding: 2px 0 6px 0; }}
QLabel#hint {{ color: {UI_MUTED}; font-size: 11px; }}
QLabel#fieldLabel {{ color: {UI_MUTED}; }}

QFrame#card {{
    background-color: {UI_PANEL};
    border: 1px solid {UI_BORDER};
    border-radius: 10px;
}}

QListWidget#nav {{
    background-color: {UI_PANEL};
    border: none;
    border-radius: 10px;
    padding: 6px;
    font-size: 14px;
    outline: none;
}}
QListWidget#nav::item {{
    padding: 10px 12px;
    border-radius: 8px;
    margin: 2px 0;
    color: {UI_MUTED};
}}
QListWidget#nav::item:selected {{
    background-color: {UI_ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QListWidget#nav::item:hover:!selected {{ background-color: {UI_PANEL_2}; color: {UI_TEXT}; }}

QPushButton {{
    background-color: {UI_PANEL_2};
    border: 1px solid {UI_BORDER};
    border-radius: 7px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background-color: #32323f; }}
QPushButton:pressed {{ background-color: #3a3a4a; }}
QPushButton#primary {{
    background-color: {UI_ACCENT}; border: none; color: #ffffff; font-weight: 600;
    padding: 10px 18px;
}}
QPushButton#primary:hover {{ background-color: #b07de0; }}
QPushButton#primary:disabled {{ background-color: #444455; color: {UI_MUTED}; }}

QComboBox, QSpinBox, QLineEdit {{
    background-color: {UI_PANEL_2};
    border: 1px solid {UI_BORDER};
    border-radius: 7px;
    padding: 6px 8px;
    min-height: 18px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {UI_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {UI_PANEL_2}; border: 1px solid {UI_BORDER};
    selection-background-color: {UI_ACCENT}; outline: none;
}}

QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {UI_BORDER}; background-color: {UI_PANEL_2};
}}
QCheckBox::indicator:checked {{ background-color: {UI_ACCENT}; border-color: {UI_ACCENT}; }}

QSlider::groove:horizontal {{ height: 5px; background: {UI_PANEL_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {UI_ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: #ffffff; width: 15px; height: 15px;
    margin: -6px 0; border-radius: 7px;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {UI_BORDER}; border-radius: 4px; min-height: 25px; }}
QScrollBar::handle:vertical:hover {{ background: {UI_ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""

# Thèmes prêts à l'emploi : un clic repeint tout l'ensemble de façon cohérente.
PRESETS = {
    "Braise (actuel)": {
        "window": "#5f1f13", "buttons": "#955053", "accent": "#9b4e50",
        "bar": "#ffffff", "viz_start": "#ffcaa0", "viz_end": "#ffffff",
    },
    "Améthyste": {
        "window": "#241634", "buttons": "#613583", "accent": "#a06bd4",
        "bar": "#d09dd2", "viz_start": "#a06bd4", "viz_end": "#f0d0ff",
    },
    "Nuit océan": {
        "window": "#0f1c2e", "buttons": "#1f4e79", "accent": "#3d8bcd",
        "bar": "#8ecdf5", "viz_start": "#3d8bcd", "viz_end": "#c8f0ff",
    },
    "Forêt": {
        "window": "#13261a", "buttons": "#2f6b45", "accent": "#4caf7d",
        "bar": "#b8e6c8", "viz_start": "#4caf7d", "viz_end": "#e0ffe8",
    },
    "Monochrome": {
        "window": "#1a1a1a", "buttons": "#3a3a3a", "accent": "#7a7a7a",
        "bar": "#ffffff", "viz_start": "#666666", "viz_end": "#ffffff",
    },
}


# ---------------------------------------------------------------------------
# Petits widgets réutilisables
# ---------------------------------------------------------------------------

class ColorButton(QPushButton):
    """Sélecteur de couleur affichant la pastille ET le code hexadécimal."""
    colorChanged = pyqtSignal(str)

    def __init__(self, color="#ffffff", parent=None):
        super().__init__(parent)
        self._color = color or "#ffffff"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self):
        return self._color

    def setColor(self, color):
        if color and color != self._color:
            self._color = color
            self._refresh()

    def _refresh(self):
        text_color = theme.readable_text_on(self._color)
        self.setText(f"  {self._color.upper()}")
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._color};
                color: {text_color};
                border: 1px solid {UI_BORDER};
                border-radius: 7px;
                padding: 7px 12px;
                text-align: left;
                font-family: monospace;
            }}
            QPushButton:hover {{ border: 1px solid {UI_ACCENT}; }}
        """)

    def _pick(self):
        color = QColorDialog.getColor(QColor(self._color), self, "Choisir une couleur")
        if color.isValid():
            self._color = color.name()
            self._refresh()
            self.colorChanged.emit(self._color)


class SliderRow(QWidget):
    """Slider + valeur lisible en direct (fini les QSpinBox sans contexte)."""
    valueChanged = pyqtSignal(float)

    def __init__(self, minimum, maximum, value, step=1, suffix="", scale=1.0,
                 decimals=0, parent=None):
        super().__init__(parent)
        self._scale = scale
        self._suffix = suffix
        self._decimals = decimals

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum / scale), int(maximum / scale))
        self.slider.setSingleStep(max(1, int(step / scale)))
        self.slider.setValue(int(round(value / scale)))
        self.slider.valueChanged.connect(self._on_change)

        self.value_label = QLabel()
        self.value_label.setMinimumWidth(64)
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setStyleSheet(f"color: {UI_TEXT}; font-family: monospace;")

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self._update_label()

    def value(self):
        return self.slider.value() * self._scale

    def _update_label(self):
        self.value_label.setText(f"{self.value():.{self._decimals}f}{self._suffix}")

    def _on_change(self):
        self._update_label()
        self.valueChanged.emit(self.value())


class Card(QFrame):
    """Bloc de réglages titré."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            self._layout.addWidget(label)
        self.form = QGridLayout()
        self.form.setColumnStretch(1, 1)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self._layout.addLayout(self.form)
        self._row = 0

    def add_row(self, label, widget):
        if label:
            lab = QLabel(label)
            lab.setObjectName("fieldLabel")
            self.form.addWidget(lab, self._row, 0, Qt.AlignmentFlag.AlignVCenter)
            self.form.addWidget(widget, self._row, 1)
        else:
            self.form.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1
        return widget

    def add_hint(self, text):
        hint = QLabel(text)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.form.addWidget(hint, self._row, 0, 1, 2)
        self._row += 1
        return hint


# ---------------------------------------------------------------------------
# Aperçu en direct
# ---------------------------------------------------------------------------

class PreviewPanel(QFrame):
    """
    Maquette du lecteur, stylée par core/theme.py — exactement les mêmes
    fonctions que main.py, donc l'aperçu ne peut pas mentir.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        header = QLabel("Aperçu en direct")
        header.setObjectName("sectionTitle")
        outer.addWidget(header)

        self.size_label = QLabel()
        self.size_label.setObjectName("hint")
        self.size_label.setWordWrap(True)
        outer.addWidget(self.size_label)

        holder = QHBoxLayout()
        holder.addStretch()
        self.player = QWidget()
        self.player.setAutoFillBackground(True)
        holder.addWidget(self.player)
        holder.addStretch()
        outer.addLayout(holder)
        outer.addStretch()

        self._build_player()

        # Anime le visualiseur et la pochette pour juger le rendu en mouvement.
        self._frame = 0
        self._fake_position = 0.0
        self._media_art = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def _build_player(self):
        # Fond (image ou GIF) : posé sous les contrôles, comme dans le lecteur.
        self.bg_label = QLabel(self.player)
        self.bg_label.setScaledContents(True)
        self.bg_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.bg_label.lower()
        self._bg_movie = None
        self._bg_shown = None

        # Voile coloré du mode « couleurs de la pochette ».
        self.tint_label = QLabel(self.player)
        self.tint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.tint_label.hide()

        layout = QVBoxLayout(self.player)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.buttons = {}

        def add_buttons(row, names):
            for name in names:
                btn = IconButton(name)
                # L'aperçu ne se pilote pas : on montre le style, pas l'action.
                btn.setEnabled(False)
                self.buttons[name] = btn
                row.addWidget(btn)

        title_bar = QHBoxLayout()
        title_bar.setSpacing(2)
        title_bar.addStretch()
        add_buttons(title_bar, ("config", "search", "reload", "minimize", "close"))
        layout.addLayout(title_bar)

        self.playlist = QListWidget()
        for title in ("Arabesque", "Distraction", "White Dress", "Defeat Here"):
            self.playlist.addItem(title)
        self.playlist.setCurrentRow(0)
        layout.addWidget(self.playlist)

        media_row = QHBoxLayout()
        media_row.addStretch()
        self.media = MediaDisplay()
        media_row.addWidget(self.media)
        media_row.addStretch()
        layout.addLayout(media_row)

        layout.addStretch()

        self.track_label = QLabel("Arabesque")
        self.track_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.track_label)

        self.progress = SeekBar()
        self.progress.set_progress(128000, 305000)
        self.progress.set_playing(True)
        layout.addWidget(self.progress)

        info = QHBoxLayout()
        info.setSpacing(2)
        self.time_label = QLabel("02:08 / 05:05")
        info.addWidget(self.time_label)
        info.addStretch(1)
        self.rate_label = QLabel("")
        info.addWidget(self.rate_label)
        add_buttons(info, ("shuffle", "nightcore", "loop"))
        layout.addLayout(info)

        controls = QHBoxLayout()
        controls.setSpacing(2)
        controls.addStretch()
        add_buttons(controls, ("rewind", "play", "stop", "forward"))
        controls.addStretch()
        layout.addLayout(controls)

        volume = QHBoxLayout()
        volume.setSpacing(4)
        add_buttons(volume, ("mute",))
        self.volume_slider = VolumeBar()
        self.volume_slider.setValue(70)
        self.volume_slider.setEnabled(False)
        volume.addWidget(self.volume_slider)
        layout.addLayout(volume)

        extras = QHBoxLayout()
        extras.setSpacing(2)
        extras.addStretch()
        add_buttons(extras, ("colorize", "skin", "viz", "playlist", "pin"))
        extras.addStretch()
        layout.addLayout(extras)

        self.visualizer = AudioVisualizer()
        layout.addWidget(self.visualizer)

    def _refresh_background(self, path, width, height):
        self.bg_label.setGeometry(0, 0, width, height)
        self.bg_label.lower()
        if not (path and os.path.isfile(path)):
            self.bg_label.clear()
            self._bg_shown = None
            return
        # Ne recharge que si l'image ou la taille a changé (refresh() est appelé
        # à chaque mouvement de slider).
        key = (path, width, height)
        if key == self._bg_shown:
            return
        self._bg_shown = key
        if path.lower().endswith(".gif"):
            if self._bg_movie:
                self._bg_movie.stop()
            self._bg_movie = QMovie(path)
            self._bg_movie.setScaledSize(QSize(width, height))
            self.bg_label.setMovie(self._bg_movie)
            self._bg_movie.start()
        else:
            self._bg_movie = None
            self.bg_label.setPixmap(QPixmap(path).scaled(
                width, height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _fake_spectrogram(self, bands):
        """Spectre synthétique lisse : décroissant vers les aigus, animé."""
        rng = np.random.default_rng(7)
        frames = 120
        base = np.linspace(1.0, 0.25, bands)[:, None]
        noise = rng.random((bands, frames)) * 0.55 + 0.45
        smooth = np.stack([np.convolve(noise[i], np.ones(9) / 9, mode="same")
                           for i in range(bands)])
        return np.clip(base * smooth, 0.02, 1.0)

    def _find_sample_art(self):
        folder = os.path.join(os.getcwd(), "assets", "music")
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(".gif"):
                    return os.path.join(folder, name)
        return ""

    def _tick(self):
        # Fait défiler une lecture fictive : le disque tourne, le bras avance,
        # la bande passe d'une bobine à l'autre.
        self._fake_position = (self._fake_position + 0.35) % 240.0
        self.media.set_progress(self._fake_position * 1000, 240 * 1000)
        if self.visualizer.spectrogramme is not None:
            self._frame = (self._frame + 1) % self.visualizer.spectrogramme.shape[1]
            self.visualizer.current_frame = self._frame
            self.visualizer.update()

    def effective_config(self):
        """
        Configuration telle que le lecteur l'appliquerait.

        En mode « couleurs de la pochette », l'aperçu montre le résultat teinté
        par la pochette d'exemple : sinon on réglerait des couleurs qui ne
        s'affichent nulle part.
        """
        if self.config.get("colorize", {}).get("enabled", False):
            if self._media_art is None:
                self._media_art = self._find_sample_art()
            pal = palette_mod.extract(self._media_art) if self._media_art \
                else palette_mod.NEUTRAL_PALETTE
            return theme.derive_from_palette(self.config, pal)
        return self.config

    def refresh(self):
        cfg = self.effective_config()
        win = cfg.get("window", {})
        btn_cfg = cfg.get("buttons", {})
        anim_cfg = cfg.get("animations", {})

        width, height = int(win.get("width", 270)), int(win.get("height", 450))
        self._wanted_size = (width, height)

        bg_color = win.get("background_color", "#9141ac")
        palette = self.player.palette()
        palette.setColor(self.player.backgroundRole(), QColor(bg_color))
        self.player.setPalette(palette)

        font = QFont(btn_cfg.get("font_family", "Arial"), int(btn_cfg.get("font_size", 12)))
        default_text = btn_cfg.get("text_color", "#FFFFFF")
        pb_cfg = cfg.get("progress_bar", {})
        accent = pb_cfg.get("color", "#ffffff")

        for name, btn in self.buttons.items():
            btn.configure(btn_cfg.get(name, {}), anim_cfg, default_text, accent)
            btn.setFont(font)

        pl_cfg = cfg.get("playlist", {})
        pl_visible = pl_cfg.get("visible", True)
        self.playlist.setFont(font)
        self.playlist.setStyleSheet(theme.playlist_qss(pl_cfg, pb_cfg))
        self.playlist.setFixedHeight(int(pl_cfg.get("height", 80)))
        self.playlist.setVisible(pl_cfg.get("visible", True))

        # La boucle est montrée active pour donner à voir l'état « bascule
        # enclenchée » (liseré d'accent, teinte, battement) ; les autres
        # reflètent la configuration réelle.
        self.buttons["loop"].set_active(True)
        self.buttons["colorize"].set_active(
            self.config.get("colorize", {}).get("enabled", False))
        self.buttons["playlist"].set_active(pl_visible)
        self.buttons["play"].set_icon_name("pause")
        self.buttons["loop"].set_icon_name("loop_one")

        text_on_bg = theme.readable_text_on(bg_color)
        for label in (self.track_label, self.time_label, self.rate_label):
            label.setFont(font)
            label.setStyleSheet(f"color: {text_on_bg}; background: transparent;")

        self.progress.setFont(font)
        self.progress.configure(pb_cfg)
        self.progress.apply_colors(pb_cfg.get("color", "#d09dd2"),
                                   pb_cfg.get("background_color", "#350b4a"), accent)
        self.time_label.setVisible(pb_cfg.get("show_time", True))

        vol_cfg = cfg.get("volume_bar", {})
        self.volume_slider.setFont(font)
        self.volume_slider.configure(vol_cfg)
        self.volume_slider.apply_colors(vol_cfg.get("slider_color", "#ffffff"),
                                        vol_cfg.get("background_color", "#62a0ea"),
                                        vol_cfg.get("slider_color", "#ffffff"))

        nc_cfg = cfg.get("nightcore", {})
        ratio = nightcore.clamp_ratio(nc_cfg.get("ratio", 1.25))
        self.rate_label.setText(f"×{ratio:g}" if nc_cfg.get("enabled_at_startup") else "")

        # Pochette : on prend un vrai GIF de la bibliothèque s'il y en a un,
        # pour juger le rendu sur du contenu réel.
        self.media.configure(cfg)
        if self._media_art is None:
            self._media_art = self._find_sample_art()
        self.media.set_art(gif_path=self._media_art, track_name="Arabesque")
        self.media.set_playing(True)
        self.media.set_rate(ratio if nc_cfg.get("enabled_at_startup") else 1.0)

        bands = max(1, int(cfg.get("visualizer", {}).get("num_bars", 60)))
        self.visualizer.configure(cfg)
        self.visualizer.set_spectrogram(self._fake_spectrogram(bands))
        self.visualizer.setFixedHeight(max(20, int(cfg.get('visualizer', {}).get('height', 120))))

        self._fit_player(win)
        self._refresh_tint(win, bg_color)

    def _refresh_tint(self, win, bg_color):
        """Même voile coloré que dans le lecteur, au-dessus de l'image de fond."""
        path = win.get("background_image_path", "")
        if not (self.config.get("colorize", {}).get("enabled", False)
                and path and os.path.isfile(path)):
            self.tint_label.hide()
            return
        strength = float(self.config.get("colorize", {}).get("strength", 0.9))
        self.tint_label.setStyleSheet(
            f"background-color: {theme.rgba(bg_color, 0.30 + 0.35 * strength)};")
        self.tint_label.setGeometry(0, 0, self.player.width(), self.player.height())
        self.tint_label.show()
        self.tint_label.stackUnder(self.playlist)
        self.bg_label.lower()

    def _fit_player(self, win):
        """Même règle que le lecteur : la taille demandée, agrandie si besoin."""
        width, height = self._wanted_size
        self.player.setMinimumSize(0, 0)
        self.player.setMaximumSize(16777215, 16777215)
        layout = self.player.layout()
        layout.activate()
        needed = layout.minimumSize()
        final_w = max(width, needed.width())
        final_h = max(height, needed.height())
        self.player.setFixedSize(final_w, final_h)
        self._refresh_background(win.get("background_image_path", ""), final_w, final_h)

        grown = " (agrandie pour tenir le contenu)" if final_h > height else ""
        self.size_label.setText(
            f"{win.get('title', 'Marulk')} — {final_w} × {final_h} px  ·  "
            f"opacité {int(float(win.get('opacity', 1.0)) * 100)} %{grown}")


# ---------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------

class ConfigUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Marulk — Personnalisation")
        self.resize(1180, 820)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(STYLESHEET)

        self.config = theme.load_config()
        self._dirty = False
        self._loading = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(400)
        self._autosave_timer.timeout.connect(self._autosave)

        self._build()
        self.refresh_preview()

    # -- ossature ------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # En-tête
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Personnalisation")
        title.setObjectName("title")
        subtitle = QLabel("Les changements s'affichent dans l'aperçu à droite. "
                          "« Appliquer en direct » met aussi à jour le lecteur ouvert.")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch()

        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Thème…")
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.setMinimumWidth(160)
        self.preset_combo.activated.connect(self.apply_preset)
        header.addWidget(self.preset_combo)
        root.addLayout(header)

        # Corps : navigation | pages | aperçu
        body = QHBoxLayout()
        body.setSpacing(14)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        self.nav.currentRowChanged.connect(lambda i: self.pages.setCurrentIndex(i))
        body.addWidget(self.nav)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)

        self.preview = PreviewPanel(self.config)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self.preview)
        preview_scroll.setFixedWidth(360)
        body.addWidget(preview_scroll)

        root.addLayout(body, 1)

        for label, builder in (
            ("🪟  Fenêtre", self.page_window),
            ("🔘  Boutons", self.page_buttons),
            ("🎚️  Lecture", self.page_playback),
            ("💿  Pochette", self.page_media),
            ("🎵  Visualiseur", self.page_visualizer),
            ("🌙  Nightcore", self.page_nightcore),
            ("⚡  Animations", self.page_animations),
            ("🎨  Couleurs auto", self.page_colorize),
        ):
            self.nav.addItem(QListWidgetItem(label))
            self.pages.addWidget(self._scrollable(builder()))
        self.nav.setCurrentRow(0)

        # Barre d'actions
        footer = QHBoxLayout()
        self.live_check = QCheckBox("Appliquer en direct")
        self.live_check.setChecked(True)
        self.live_check.setToolTip(
            "Enregistre à chaque modification. Le lecteur surveille config.json "
            "et se recharge sans redémarrer.")
        footer.addWidget(self.live_check)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        footer.addWidget(self.status_label)
        footer.addStretch()

        reset_btn = QPushButton("Réinitialiser")
        reset_btn.clicked.connect(self.reset_config)
        footer.addWidget(reset_btn)

        self.save_button = QPushButton("💾  Enregistrer")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(lambda: self.save_config(explicit=True))
        footer.addWidget(self.save_button)
        root.addLayout(footer)

    def _scrollable(self, widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        return page, layout

    # -- réactions ------------------------------------------------------

    def touch(self):
        """Un réglage a changé : aperçu immédiat + sauvegarde éventuelle."""
        if self._loading:
            return
        self._dirty = True
        self.refresh_preview()
        if self.live_check.isChecked():
            self._autosave_timer.start()
        else:
            self.status_label.setText("Modifications non enregistrées")

    def refresh_preview(self):
        self.preview.config = self.config
        self.preview.refresh()

    def _autosave(self):
        self.save_config(explicit=False)

    def set_value(self, section, key, value):
        self.config.setdefault(section, {})[key] = value
        self.touch()

    def set_button_value(self, button, key, value):
        self.config["buttons"].setdefault(button, {})[key] = value
        self.touch()

    # -- page : fenêtre --------------------------------------------------

    def page_window(self):
        page, layout = self._page()
        win = self.config["window"]

        card = Card("Fenêtre")
        title_edit = QLineEdit(win.get("title", "Marulk"))
        title_edit.textChanged.connect(lambda t: self.set_value("window", "title", t))
        card.add_row("Titre", title_edit)

        color_btn = ColorButton(win.get("background_color", "#9141ac"))
        color_btn.colorChanged.connect(
            lambda c: self.set_value("window", "background_color", c))
        card.add_row("Couleur de fond", color_btn)

        width = SliderRow(200, 900, win.get("width", 270), suffix=" px")
        width.valueChanged.connect(lambda v: self.set_value("window", "width", int(v)))
        card.add_row("Largeur", width)

        height = SliderRow(250, 1200, win.get("height", 450), suffix=" px")
        height.valueChanged.connect(lambda v: self.set_value("window", "height", int(v)))
        card.add_row("Hauteur", height)

        opacity = SliderRow(20, 100, float(win.get("opacity", 1.0)) * 100, suffix=" %")
        opacity.valueChanged.connect(lambda v: self.set_value("window", "opacity", v / 100))
        card.add_row("Opacité", opacity)
        layout.addWidget(card)

        # Image de fond
        bg_card = Card("Image de fond")
        self.bg_path_label = QLabel(win.get("background_image_path") or "Aucune image")
        self.bg_path_label.setObjectName("hint")
        self.bg_path_label.setWordWrap(True)

        row = QHBoxLayout()
        choose = QPushButton("Choisir une image / un GIF…")
        choose.clicked.connect(self.pick_bg_image)
        clear = QPushButton("Retirer")
        clear.clicked.connect(lambda: (
            self.set_value("window", "background_image_path", ""),
            self.bg_path_label.setText("Aucune image")))
        row.addWidget(choose, 1)
        row.addWidget(clear)
        holder = QWidget()
        holder.setLayout(row)
        bg_card.add_row(None, holder)
        bg_card.add_row(None, self.bg_path_label)
        bg_card.add_hint("L'image est étirée à la taille de la fenêtre. "
                         "Un .gif est animé automatiquement.")
        layout.addWidget(bg_card)

        # Playlist
        pl = self.config["playlist"]
        pl_card = Card("Playlist")
        visible = QCheckBox("Afficher la liste des pistes")
        visible.setChecked(pl.get("visible", True))
        visible.toggled.connect(lambda v: self.set_value("playlist", "visible", v))
        pl_card.add_row(None, visible)

        pl_height = SliderRow(40, 300, pl.get("height", 80), suffix=" px")
        pl_height.valueChanged.connect(lambda v: self.set_value("playlist", "height", int(v)))
        pl_card.add_row("Hauteur", pl_height)

        pl_color = ColorButton(pl.get("text_color", "#ffffff"))
        pl_color.colorChanged.connect(lambda c: self.set_value("playlist", "text_color", c))
        pl_card.add_row("Couleur du texte", pl_color)

        pl_opacity = SliderRow(0, 100, float(pl.get("background_opacity", 0.25)) * 100, suffix=" %")
        pl_opacity.valueChanged.connect(
            lambda v: self.set_value("playlist", "background_opacity", v / 100))
        pl_card.add_row("Fond (opacité)", pl_opacity)
        layout.addWidget(pl_card)

        # Overlay
        ov = self.config["overlay"]
        ov_card = Card("Voile au survol")
        ov_check = QCheckBox("Assombrir la fenêtre au survol")
        ov_check.setChecked(ov.get("show_on_hover", False))
        ov_check.toggled.connect(lambda v: self.set_value("overlay", "show_on_hover", v))
        ov_card.add_row(None, ov_check)

        ov_color = ColorButton(ov.get("color", "#000000"))
        ov_color.colorChanged.connect(lambda c: self.set_value("overlay", "color", c))
        ov_card.add_row("Couleur", ov_color)

        ov_opacity = SliderRow(0, 100, float(ov.get("opacity", 0.8)) * 100, suffix=" %")
        ov_opacity.valueChanged.connect(lambda v: self.set_value("overlay", "opacity", v / 100))
        ov_card.add_row("Opacité", ov_opacity)
        layout.addWidget(ov_card)

        layout.addStretch()
        return page

    def pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image ou un GIF", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.set_value("window", "background_image_path", path)
            self.bg_path_label.setText(path)

    # -- page : boutons --------------------------------------------------

    def page_buttons(self):
        page, layout = self._page()
        btn_cfg = self.config["buttons"]

        general = Card("Police et couleur par défaut")
        font_combo = QComboBox()
        families = QFontDatabase.families()
        font_combo.addItems(families)
        current = btn_cfg.get("font_family", "Arial")
        if current in families:
            font_combo.setCurrentText(current)
        font_combo.currentTextChanged.connect(
            lambda f: self.set_value("buttons", "font_family", f))
        general.add_row("Police", font_combo)

        font_size = SliderRow(5, 40, btn_cfg.get("font_size", 12), suffix=" pt")
        font_size.valueChanged.connect(
            lambda v: self.set_value("buttons", "font_size", int(v)))
        general.add_row("Taille", font_size)

        text_color = ColorButton(btn_cfg.get("text_color", "#FFFFFF"))
        text_color.colorChanged.connect(lambda c: self.set_value("buttons", "text_color", c))
        general.add_row("Couleur du texte", text_color)
        general.add_hint("Utilisée pour les boutons qui n'ont pas leur propre couleur de texte.")
        layout.addWidget(general)

        # Éditeur par bouton : un sélecteur plutôt que 10 onglets serrés.
        editor = Card("Bouton par bouton")
        self.button_selector = QComboBox()
        for name in theme.BUTTON_ORDER:
            # L'icône du menu est celle réellement dessinée sur le bouton.
            self.button_selector.addItem(
                icons.icon(name, 18, UI_TEXT),
                theme.BUTTON_LABELS.get(name, name), name)
        self.button_selector.currentIndexChanged.connect(self.load_button_editor)
        editor.add_row("Bouton", self.button_selector)

        self.btn_shape = QComboBox()
        self.btn_shape.addItems(theme.SHAPES)
        self.btn_shape.currentTextChanged.connect(
            lambda v: self.set_button_value(self.current_button(), "shape", v))
        editor.add_row("Forme", self.btn_shape)

        self.btn_color = ColorButton()
        self.btn_color.colorChanged.connect(
            lambda c: self.set_button_value(self.current_button(), "color", c))
        editor.add_row("Couleur de fond", self.btn_color)

        self.btn_text_color = ColorButton()
        self.btn_text_color.colorChanged.connect(
            lambda c: self.set_button_value(self.current_button(), "text_color", c))
        editor.add_row("Couleur du texte", self.btn_text_color)

        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_w = QSpinBox(); self.btn_w.setRange(10, 200); self.btn_w.setSuffix(" px")
        self.btn_h = QSpinBox(); self.btn_h.setRange(10, 200); self.btn_h.setSuffix(" px")
        for spin in (self.btn_w, self.btn_h):
            spin.valueChanged.connect(self.push_button_size)
        size_layout.addWidget(QLabel("L")); size_layout.addWidget(self.btn_w, 1)
        size_layout.addSpacing(8)
        size_layout.addWidget(QLabel("H")); size_layout.addWidget(self.btn_h, 1)
        editor.add_row("Taille", size_row)

        self.btn_opacity = SliderRow(0, 100, 100, suffix=" %")
        self.btn_opacity.valueChanged.connect(
            lambda v: self.set_button_value(self.current_button(), "opacity", v / 100))
        editor.add_row("Opacité", self.btn_opacity)

        self.btn_border_w = SliderRow(0, 10, 0, suffix=" px")
        self.btn_border_w.valueChanged.connect(
            lambda v: self.set_button_value(self.current_button(), "border_width", int(v)))
        editor.add_row("Bordure", self.btn_border_w)

        self.btn_border_c = ColorButton()
        self.btn_border_c.colorChanged.connect(
            lambda c: self.set_button_value(self.current_button(), "border_color", c))
        editor.add_row("Couleur bordure", self.btn_border_c)

        image_row = QWidget()
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        pick = QPushButton("Image…")
        pick.clicked.connect(self.pick_button_image)
        drop = QPushButton("Retirer")
        drop.clicked.connect(lambda: (
            self.set_button_value(self.current_button(), "image_path", ""),
            self.btn_image_label.setText("Aucune image")))
        image_layout.addWidget(pick, 1)
        image_layout.addWidget(drop)
        editor.add_row("Icône", image_row)

        self.btn_image_label = QLabel("Aucune image")
        self.btn_image_label.setObjectName("hint")
        self.btn_image_label.setWordWrap(True)
        editor.add_row(None, self.btn_image_label)

        apply_all = QPushButton("Appliquer cette couleur à tous les boutons")
        apply_all.clicked.connect(self.apply_color_to_all)
        editor.add_row(None, apply_all)
        layout.addWidget(editor)

        layout.addStretch()
        self.load_button_editor()
        return page

    def current_button(self):
        return self.button_selector.currentData()

    def load_button_editor(self):
        """Recharge l'éditeur sans déclencher de sauvegarde parasite."""
        name = self.current_button()
        if not name:
            return
        cfg = self.config["buttons"].setdefault(name, {})
        self._loading = True
        try:
            self.btn_shape.setCurrentText(cfg.get("shape", "rounded"))
            self.btn_color.setColor(cfg.get("color", "#613583"))
            self.btn_text_color.setColor(cfg.get("text_color", "#FFFFFF"))
            size = cfg.get("size", [30, 30])
            self.btn_w.setValue(int(size[0]))
            self.btn_h.setValue(int(size[1]))
            self.btn_opacity.slider.setValue(int(float(cfg.get("opacity", 1.0)) * 100))
            self.btn_border_w.slider.setValue(int(cfg.get("border_width", 0) or 0))
            self.btn_border_c.setColor(cfg.get("border_color", "#000000"))
            self.btn_image_label.setText(cfg.get("image_path") or "Aucune image")
        finally:
            self._loading = False

    def push_button_size(self):
        if self._loading:
            return
        self.set_button_value(self.current_button(), "size",
                              [self.btn_w.value(), self.btn_h.value()])

    def pick_button_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Icône du bouton", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.set_button_value(self.current_button(), "image_path", path)
            self.btn_image_label.setText(path)

    def apply_color_to_all(self):
        color = self.btn_color.color()
        for name in theme.BUTTON_ORDER:
            self.config["buttons"].setdefault(name, {})["color"] = color
        self.touch()

    # -- page : lecture ---------------------------------------------------

    def page_playback(self):
        page, layout = self._page()

        pb = self.config["progress_bar"]
        card = Card("Barre de progression")
        color = ColorButton(pb.get("color", "#d09dd2"))
        color.colorChanged.connect(lambda c: self.set_value("progress_bar", "color", c))
        card.add_row("Couleur", color)

        bg = ColorButton(pb.get("background_color", "#350b4a"))
        bg.colorChanged.connect(lambda c: self.set_value("progress_bar", "background_color", c))
        card.add_row("Couleur de fond", bg)

        height = SliderRow(2, 40, pb.get("height", 10), suffix=" px")
        height.valueChanged.connect(lambda v: self.set_value("progress_bar", "height", int(v)))
        card.add_row("Hauteur", height)

        radius = SliderRow(0, 30, pb.get("radius", 10), suffix=" px")
        radius.valueChanged.connect(lambda v: self.set_value("progress_bar", "radius", int(v)))
        card.add_row("Arrondi", radius)

        style = QComboBox()
        style.addItems(BAR_STYLES)
        style.setCurrentText(pb.get("style", "gradient"))
        style.currentTextChanged.connect(lambda v: self.set_value("progress_bar", "style", v))
        card.add_row("Style", style)

        show_time = QCheckBox("Afficher le temps écoulé / total")
        show_time.setChecked(pb.get("show_time", True))
        show_time.toggled.connect(lambda v: self.set_value("progress_bar", "show_time", v))
        card.add_row(None, show_time)

        animated = QCheckBox("Reflet qui balaie la partie déjà lue")
        animated.setChecked(pb.get("animated", True))
        animated.toggled.connect(lambda v: self.set_value("progress_bar", "animated", v))
        card.add_row(None, animated)

        knob = QCheckBox("Poignée sur la tête de lecture")
        knob.setChecked(pb.get("knob", True))
        knob.toggled.connect(lambda v: self.set_value("progress_bar", "knob", v))
        card.add_row(None, knob)

        glow = QCheckBox("Halo lumineux")
        glow.setChecked(pb.get("glow", True))
        glow.toggled.connect(lambda v: self.set_value("progress_bar", "glow", v))
        card.add_row(None, glow)
        card.add_hint("La barre est cliquable et se glisse ; au survol elle "
                      "s'épaissit et affiche le temps visé.")
        layout.addWidget(card)

        vol = self.config["volume_bar"]
        vcard = Card("Volume")
        slider_color = ColorButton(vol.get("slider_color", "#ffffff"))
        slider_color.colorChanged.connect(
            lambda c: self.set_value("volume_bar", "slider_color", c))
        vcard.add_row("Curseur", slider_color)

        vbg = ColorButton(vol.get("background_color", "#62a0ea"))
        vbg.colorChanged.connect(lambda c: self.set_value("volume_bar", "background_color", c))
        vcard.add_row("Rail", vbg)

        vheight = SliderRow(2, 40, vol.get("height", 10), suffix=" px")
        vheight.valueChanged.connect(lambda v: self.set_value("volume_bar", "height", int(v)))
        vcard.add_row("Hauteur", vheight)

        shape = QComboBox()
        shape.addItems(["rounded", "square"])
        shape.setCurrentText(vol.get("slider_shape", "rounded"))
        shape.currentTextChanged.connect(
            lambda v: self.set_value("volume_bar", "slider_shape", v))
        vcard.add_row("Forme du curseur", shape)

        vradius = SliderRow(0, 30, vol.get("radius", 5), suffix=" px")
        vradius.valueChanged.connect(lambda v: self.set_value("volume_bar", "radius", int(v)))
        vcard.add_row("Arrondi", vradius)

        vstyle = QComboBox()
        vstyle.addItems(BAR_STYLES)
        vstyle.setCurrentText(vol.get("style", "gradient"))
        vstyle.currentTextChanged.connect(lambda v: self.set_value("volume_bar", "style", v))
        vcard.add_row("Style", vstyle)

        vknob = QCheckBox("Poignée")
        vknob.setChecked(vol.get("knob", True))
        vknob.toggled.connect(lambda v: self.set_value("volume_bar", "knob", v))
        vcard.add_row(None, vknob)

        vglow = QCheckBox("Halo lumineux")
        vglow.setChecked(vol.get("glow", True))
        vglow.toggled.connect(lambda v: self.set_value("volume_bar", "glow", v))
        vcard.add_row(None, vglow)

        default_volume = SliderRow(0, 100, vol.get("default_volume", 70), suffix=" %")
        default_volume.valueChanged.connect(
            lambda v: self.set_value("volume_bar", "default_volume", int(v)))
        vcard.add_row("Volume au démarrage", default_volume)
        vcard.add_hint("La barre se règle aussi à la molette.")
        layout.addWidget(vcard)

        shortcuts = Card("Raccourcis clavier du lecteur")
        for keys, action in (
            ("Espace", "Lecture / Pause"),
            ("← / →", "Piste précédente / suivante"),
            ("↑ / ↓", "Volume"),
            ("N", "Nightcore"),
            ("L", "Boucle"),
            ("S", "Lecture aléatoire"),
            ("X", "Arrêt"),
            ("M", "Couper le son"),
            ("K", "Couleurs de la pochette"),
            ("D", "Changer de support"),
            ("V", "Style du visualiseur"),
            ("P", "Afficher / masquer la playlist"),
            ("T", "Garder au-dessus"),
            ("R", "Recharger la playlist"),
            ("C", "Ouvrir cette fenêtre"),
            ("Échap", "Fermer le lecteur"),
        ):
            key_label = QLabel(keys)
            key_label.setStyleSheet(
                f"background: {UI_PANEL_2}; border: 1px solid {UI_BORDER};"
                "border-radius: 5px; padding: 3px 8px; font-family: monospace;")
            shortcuts.add_row(action, key_label)
        layout.addWidget(shortcuts)

        layout.addStretch()
        return page

    # -- page : pochette ----------------------------------------------------

    def page_media(self):
        page, layout = self._page()
        media = self.config["media"]

        card = Card("Support affiché")
        skin = QComboBox()
        for name in SKINS:
            skin.addItem(SKIN_LABELS[name], name)
        index = skin.findData(media.get("skin", "vinyl"))
        skin.setCurrentIndex(max(0, index))
        skin.currentIndexChanged.connect(
            lambda i, c=skin: self.set_value("media", "skin", c.itemData(i)))
        card.add_row("Support", skin)
        card.add_hint("Vinyle et CD tournent ; la cassette déroule sa bande "
                      "d'une bobine à l'autre. La pochette vient du GIF du "
                      "morceau, sinon des tags, sinon elle est générée.")

        size = SliderRow(60, 260, media.get("size", 120), suffix=" px")
        size.valueChanged.connect(lambda v: self.set_value("media", "size", int(v)))
        card.add_row("Taille", size)

        replay = QPushButton("▶  Rejouer l'animation d'insertion")
        replay.clicked.connect(lambda: self.preview.media.play_insert())
        card.add_row(None, replay)
        layout.addWidget(card)

        spin_card = Card("Rotation")
        spin = QCheckBox("Faire tourner le support")
        spin.setChecked(media.get("spin", True))
        spin.toggled.connect(lambda v: self.set_value("media", "spin", v))
        spin_card.add_row(None, spin)

        rpm = SliderRow(5, 120, float(media.get("rpm", 33.3)),
                        step=0.1, scale=0.1, decimals=1, suffix=" tr/min")
        rpm.valueChanged.connect(lambda v: self.set_value("media", "rpm", round(v, 1)))
        spin_card.add_row("Vitesse", rpm)
        spin_card.add_hint("33,3 tr/min est la vitesse réelle d'un 33 tours. "
                           "La rotation suit la position de lecture : en pause "
                           "le disque se fige, et un saut dans la barre le fait "
                           "sauter aussi.")

        follow = QCheckBox("Tourner plus vite en nightcore")
        follow.setChecked(media.get("follow_nightcore", True))
        follow.toggled.connect(lambda v: self.set_value("media", "follow_nightcore", v))
        spin_card.add_row(None, follow)
        layout.addWidget(spin_card)

        detail_card = Card("Détails")
        tonearm = QCheckBox("Bras de lecture (vinyle)")
        tonearm.setChecked(media.get("tonearm", True))
        tonearm.toggled.connect(lambda v: self.set_value("media", "tonearm", v))
        detail_card.add_row(None, tonearm)
        detail_card.add_hint("Le bras se pose à la lecture, se relève en pause "
                             "et progresse vers le centre au fil du morceau.")

        shine = QCheckBox("Reflet de lumière")
        shine.setChecked(media.get("shine", True))
        shine.toggled.connect(lambda v: self.set_value("media", "shine", v))
        detail_card.add_row(None, shine)

        insert = QCheckBox("Animation d'insertion au changement de piste")
        insert.setChecked(media.get("insert_animation", True))
        insert.toggled.connect(lambda v: self.set_value("media", "insert_animation", v))
        detail_card.add_row(None, insert)

        click = QCheckBox("Cliquer la pochette lance / met en pause")
        click.setChecked(media.get("click_toggles_play", True))
        click.toggled.connect(lambda v: self.set_value("media", "click_toggles_play", v))
        detail_card.add_row(None, click)

        label_ratio = SliderRow(12, 70, float(media.get("label_ratio", 0.36)) * 100,
                                suffix=" %")
        label_ratio.valueChanged.connect(
            lambda v: self.set_value("media", "label_ratio", round(v / 100, 3)))
        detail_card.add_row("Étiquette (vinyle)", label_ratio)

        body = ColorButton(media.get("body_color", "#141414"))
        body.colorChanged.connect(lambda c: self.set_value("media", "body_color", c))
        detail_card.add_row("Couleur du support", body)

        accent = ColorButton(media.get("accent_color", "#c8a45a"))
        accent.colorChanged.connect(lambda c: self.set_value("media", "accent_color", c))
        detail_card.add_row("Couleur de la cellule", accent)

        colorize = QCheckBox("Colorer le support d'après la pochette")
        colorize.setChecked(media.get("colorize", True))
        colorize.toggled.connect(lambda v: self.set_value("media", "colorize", v))
        detail_card.add_row(None, colorize)
        detail_card.add_hint("Coché, les deux couleurs ci-dessus sont remplacées "
                             "par celles du morceau en cours : coque, sillons, "
                             "bande et bras s'accordent à la pochette.")
        layout.addWidget(detail_card)

        layout.addStretch()
        return page

    # -- page : visualiseur ------------------------------------------------

    def page_visualizer(self):
        page, layout = self._page()
        viz = self.config["visualizer"]

        card = Card("Visualiseur")
        enabled = QCheckBox("Activer le visualiseur")
        enabled.setChecked(viz.get("enabled", True))
        enabled.toggled.connect(lambda v: self.set_value("visualizer", "enabled", v))
        card.add_row(None, enabled)

        style = QComboBox()
        style.addItems(["bars", "wave", "circle"])
        style.setCurrentText(viz.get("style", "bars"))
        style.currentTextChanged.connect(lambda v: self.set_value("visualizer", "style", v))
        card.add_row("Style", style)

        bars = SliderRow(4, 120, viz.get("num_bars", 60))
        bars.valueChanged.connect(lambda v: self.set_value("visualizer", "num_bars", int(v)))
        card.add_row("Nombre de bandes", bars)

        start = ColorButton(viz.get("color_start", "#ffffff"))
        start.colorChanged.connect(lambda c: self.set_value("visualizer", "color_start", c))
        card.add_row("Couleur (bas)", start)

        end = ColorButton(viz.get("color_end", "#ffffff"))
        end.colorChanged.connect(lambda c: self.set_value("visualizer", "color_end", c))
        card.add_row("Couleur (haut)", end)

        height = SliderRow(20, 300, viz.get("height", 120), suffix=" px")
        height.valueChanged.connect(lambda v: self.set_value("visualizer", "height", int(v)))
        card.add_row("Hauteur", height)

        intensity = SliderRow(0.1, 5.0, float(viz.get("intensity", 5.0)),
                              step=0.1, scale=0.1, decimals=1, suffix=" ×")
        intensity.valueChanged.connect(
            lambda v: self.set_value("visualizer", "intensity", round(v, 2)))
        card.add_row("Intensité", intensity)
        card.add_hint("L'analyse tourne maintenant en tâche de fond : changer de "
                      "piste ne fige plus l'interface.")
        layout.addWidget(card)

        layout.addStretch()
        return page

    # -- page : nightcore ---------------------------------------------------

    def page_nightcore(self):
        page, layout = self._page()
        nc = self.config["nightcore"]

        card = Card("Nightcore")
        explain = QLabel(
            "Le nightcore accélère le morceau <b>et</b> monte le pitch — mais ce "
            "n'est pas deux effets : relire les mêmes échantillons plus vite fait "
            "monter toutes les fréquences du même ratio. C'est ce seul "
            "rééchantillonnage que fait le bouton 🌙 (ou la touche <b>N</b>)."
        )
        explain.setWordWrap(True)
        explain.setObjectName("hint")
        card.add_row(None, explain)

        self.nc_ratio = SliderRow(
            nightcore.MIN_RATIO, nightcore.MAX_RATIO,
            nightcore.clamp_ratio(nc.get("ratio", 1.25)),
            step=0.01, scale=0.01, decimals=2, suffix=" ×")
        self.nc_ratio.valueChanged.connect(self.on_ratio_changed)
        card.add_row("Vitesse", self.nc_ratio)

        self.nc_semitones = QLabel()
        self.nc_semitones.setObjectName("hint")
        card.add_row("Pitch", self.nc_semitones)

        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        for label, value in (("Léger 1.15×", 1.15), ("Classique 1.25×", 1.25),
                             ("Intense 1.35×", 1.35)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, v=value: self.nc_ratio.slider.setValue(int(v * 100)))
            preset_layout.addWidget(btn)
        card.add_row("Préréglages", preset_row)

        at_startup = QCheckBox("Activer le nightcore au démarrage")
        at_startup.setChecked(nc.get("enabled_at_startup", False))
        at_startup.toggled.connect(
            lambda v: self.set_value("nightcore", "enabled_at_startup", v))
        card.add_row(None, at_startup)

        prefetch = QCheckBox("Préparer la piste suivante à l'avance")
        prefetch.setChecked(nc.get("auto_render_next", True))
        prefetch.toggled.connect(
            lambda v: self.set_value("nightcore", "auto_render_next", v))
        card.add_row(None, prefetch)
        card.add_hint("Évite le petit temps de calcul au changement de piste.")
        layout.addWidget(card)

        cache_card = Card("Cache des rendus")
        self.cache_label = QLabel()
        self.cache_label.setObjectName("hint")
        cache_card.add_row("Espace utilisé", self.cache_label)
        clear_btn = QPushButton("Vider le cache nightcore")
        clear_btn.clicked.connect(self.clear_nightcore_cache)
        cache_card.add_row(None, clear_btn)
        cache_card.add_hint(
            f"Les rendus sont stockés dans {nightcore.CACHE_DIR} et réutilisés "
            "d'une session à l'autre. Ils se purgent tout seuls au-delà de "
            f"{nightcore.MAX_CACHE_BYTES // (1024 * 1024)} Mo.")
        layout.addWidget(cache_card)

        self.update_nightcore_labels()
        layout.addStretch()
        return page

    def on_ratio_changed(self, value):
        self.set_value("nightcore", "ratio", round(value, 3))
        self.update_nightcore_labels()

    def update_nightcore_labels(self):
        ratio = nightcore.clamp_ratio(self.config["nightcore"].get("ratio", 1.25))
        semis = nightcore.ratio_to_semitones(ratio)
        note = ""
        if ratio <= 1.001:
            note = " — lecture normale"
        elif ratio > 1.35:
            note = " — au-delà de 1.35×, les voix commencent à baver"
        elif abs(ratio - 1.25) < 0.005:
            note = " — le ratio classique de la scène nightcore"
        self.nc_semitones.setText(f"+{semis:.2f} demi-tons{note}")
        size_mb = nightcore.cache_size_bytes() / (1024 * 1024)
        self.cache_label.setText(f"{size_mb:.0f} Mo")

    def clear_nightcore_cache(self):
        freed = nightcore.clear_cache() / (1024 * 1024)
        self.update_nightcore_labels()
        QMessageBox.information(self, "Cache vidé", f"{freed:.0f} Mo libérés.")

    # -- page : animations --------------------------------------------------

    def page_animations(self):
        page, layout = self._page()
        anim = self.config["animations"]

        card = Card("Animations")
        enabled = QCheckBox("Activer les animations")
        enabled.setChecked(anim.get("enabled", True))
        enabled.toggled.connect(lambda v: self.set_value("animations", "enabled", v))
        card.add_row(None, enabled)

        hover = QCheckBox("Agrandir les boutons au survol")
        hover.setChecked(anim.get("hover_enabled", True))
        hover.toggled.connect(lambda v: self.set_value("animations", "hover_enabled", v))
        card.add_row(None, hover)

        click = QCheckBox("Enfoncer les boutons au clic")
        click.setChecked(anim.get("click_enabled", True))
        click.toggled.connect(lambda v: self.set_value("animations", "click_enabled", v))
        card.add_row(None, click)

        glow = QCheckBox("Halo au survol")
        glow.setChecked(anim.get("glow_enabled", True))
        glow.toggled.connect(lambda v: self.set_value("animations", "glow_enabled", v))
        card.add_row(None, glow)

        ripple = QCheckBox("Onde partant du point cliqué")
        ripple.setChecked(anim.get("ripple_enabled", True))
        ripple.toggled.connect(lambda v: self.set_value("animations", "ripple_enabled", v))
        card.add_row(None, ripple)

        spin = QCheckBox("Rotation de l'icône (boucle, aléatoire, recharger…)")
        spin.setChecked(anim.get("spin_enabled", True))
        spin.toggled.connect(lambda v: self.set_value("animations", "spin_enabled", v))
        card.add_row(None, spin)

        pulse = QCheckBox("Battement des bascules actives")
        pulse.setChecked(anim.get("pulse_enabled", True))
        pulse.toggled.connect(lambda v: self.set_value("animations", "pulse_enabled", v))
        card.add_row(None, pulse)

        glow_strength = SliderRow(0, 200, float(anim.get("glow_strength", 1.0)) * 100,
                                  suffix=" %")
        glow_strength.valueChanged.connect(
            lambda v: self.set_value("animations", "glow_strength", round(v / 100, 2)))
        card.add_row("Intensité du halo", glow_strength)

        fade = QCheckBox("Fondu à l'ouverture de la fenêtre")
        fade.setChecked(anim.get("window_fade_in", True))
        fade.toggled.connect(lambda v: self.set_value("animations", "window_fade_in", v))
        card.add_row(None, fade)

        duration = SliderRow(50, 1000, anim.get("duration", 150), suffix=" ms")
        duration.valueChanged.connect(lambda v: self.set_value("animations", "duration", int(v)))
        card.add_row("Durée", duration)

        hover_scale = SliderRow(100, 200, float(anim.get("hover_scale", 1.1)) * 100, suffix=" %")
        hover_scale.valueChanged.connect(
            lambda v: self.set_value("animations", "hover_scale", round(v / 100, 3)))
        card.add_row("Échelle au survol", hover_scale)

        click_scale = SliderRow(50, 100, float(anim.get("click_scale", 0.95)) * 100, suffix=" %")
        click_scale.valueChanged.connect(
            lambda v: self.set_value("animations", "click_scale", round(v / 100, 3)))
        card.add_row("Échelle au clic", click_scale)
        card.add_hint("Ces réglages sont maintenant réellement lus par le lecteur. "
                      "L'agrandissement se fait dans une marge réservée : les "
                      "boutons voisins ne bougent plus au survol.")
        layout.addWidget(card)

        layout.addStretch()
        return page

    # -- page : couleurs de la pochette ------------------------------------

    def page_colorize(self):
        page, layout = self._page()
        section = self.config.setdefault("colorize", theme.DEFAULT_CONFIG["colorize"].copy())

        card = Card("Couleurs tirées de la pochette")
        enabled = QCheckBox("Colorer le lecteur d'après le morceau en cours")
        enabled.setChecked(section.get("enabled", False))
        enabled.toggled.connect(lambda v: self.set_value("colorize", "enabled", v))
        card.add_row(None, enabled)
        card.add_hint("Le lecteur extrait deux couleurs de la pochette (une "
                      "dominante, un accent) et repeint fond, boutons, barres, "
                      "visualiseur et support. Vos couleurs ne sont pas écrasées : "
                      "décocher restitue votre thème tel quel.")

        strength = SliderRow(0, 100, float(section.get("strength", 0.9)) * 100, suffix=" %")
        strength.valueChanged.connect(
            lambda v: self.set_value("colorize", "strength", round(v / 100, 2)))
        card.add_row("Intensité", strength)
        card.add_hint("À 0 %, le lecteur reste neutre ; à 100 %, il prend "
                      "pleinement la teinte de la pochette.")

        animate = QCheckBox("Fondu de couleur au changement de piste")
        animate.setChecked(section.get("animate", True))
        animate.toggled.connect(lambda v: self.set_value("colorize", "animate", v))
        card.add_row(None, animate)
        layout.addWidget(card)

        parts = Card("Ce qui est coloré")
        for key, label in (("background", "Fond de la fenêtre"),
                           ("buttons", "Boutons"),
                           ("bars", "Barres de progression et de volume"),
                           ("visualizer", "Visualiseur"),
                           ("media", "Support (vinyle, CD, cassette)")):
            box = QCheckBox(label)
            box.setChecked(section.get(key, True))
            box.toggled.connect(lambda v, k=key: self.set_value("colorize", k, v))
            parts.add_row(None, box)
        parts.add_hint("Le lecteur bascule aussi ce mode d'un clic sur le bouton "
                       "palette, ou avec la touche K.")
        layout.addWidget(parts)

        layout.addStretch()
        return page

    # -- thèmes / sauvegarde ------------------------------------------------

    def apply_preset(self, index):
        if index <= 0:
            return
        preset = PRESETS[self.preset_combo.itemText(index)]
        self.config["window"]["background_color"] = preset["window"]
        for name in theme.BUTTON_ORDER:
            btn = self.config["buttons"].setdefault(name, {})
            btn["color"] = preset["buttons"] if name != "close" else "#a33"
            btn["text_color"] = theme.readable_text_on(btn["color"])
        self.config["progress_bar"]["color"] = preset["bar"]
        self.config["progress_bar"]["background_color"] = preset["accent"]
        self.config["volume_bar"]["slider_color"] = preset["bar"]
        self.config["volume_bar"]["background_color"] = preset["accent"]
        self.config["visualizer"]["color_start"] = preset["viz_start"]
        self.config["visualizer"]["color_end"] = preset["viz_end"]
        self.preset_combo.setCurrentIndex(0)
        self.rebuild_pages()
        self.touch()

    def reset_config(self):
        answer = QMessageBox.question(
            self, "Réinitialiser",
            "Restaurer toute la configuration par défaut ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.config = theme.merge_defaults(theme.DEFAULT_CONFIG, {})
            self.rebuild_pages()
            self.touch()

    def rebuild_pages(self):
        """Reconstruit les pages pour refléter une config remplacée d'un bloc."""
        row = self.nav.currentRow()
        self._loading = True
        try:
            while self.pages.count():
                widget = self.pages.widget(0)
                self.pages.removeWidget(widget)
                widget.deleteLater()
            for builder in (self.page_window, self.page_buttons, self.page_playback,
                            self.page_media, self.page_visualizer,
                            self.page_nightcore, self.page_animations,
                            self.page_colorize):
                self.pages.addWidget(self._scrollable(builder()))
        finally:
            self._loading = False
        self.nav.setCurrentRow(max(0, row))
        self.pages.setCurrentIndex(max(0, row))

    def save_config(self, explicit=False):
        try:
            theme.save_config(self.config, CONFIG_FILE)
        except Exception as exc:
            self.status_label.setText(f"⚠️ Échec de l'enregistrement : {exc}")
            return
        self._dirty = False
        self.status_label.setText(
            "✅ Enregistré — le lecteur s'est mis à jour" if not explicit
            else "✅ Configuration enregistrée")
        QTimer.singleShot(2500, lambda: self.status_label.setText(""))
        print("✅ Configuration enregistrée")

    def closeEvent(self, event):
        if self._dirty and not self.live_check.isChecked():
            answer = QMessageBox.question(
                self, "Modifications non enregistrées",
                "Enregistrer avant de fermer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.save_config(explicit=True)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ConfigUI()
    win.show()
    sys.exit(app.exec())
