"""
Affichage de la pochette : vinyle, CD, cassette ou GIF nu.

Quelques partis pris qui font la différence avec une simple décoration :

  * la rotation est pilotée par la POSITION de lecture, pas par une horloge
    libre. Mettre en pause fige le disque, un saut dans la barre de progression
    le fait sauter aussi : le disque devient un indicateur, pas un gadget ;
  * en nightcore, le disque tourne littéralement plus vite (×1.25), parce que
    c'est exactement ce que fait la bande ;
  * la cassette répartit sa bande entre les deux bobines selon l'avancement, et
    chaque bobine tourne à une vitesse inversement proportionnelle à son rayon,
    comme une vraie mécanique. On lit l'avancement d'un coup d'œil.
"""

import hashlib
import math
import os

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, pyqtProperty, QPropertyAnimation, QEasingCurve
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QPixmap, QMovie, QPainterPath,
    QConicalGradient, QLinearGradient, QRadialGradient, QFont
)
from PyQt6.QtWidgets import QWidget

from core import palette as palette_mod

SKINS = ["none", "gif", "vinyl", "cd", "cassette"]

SKIN_LABELS = {
    "none": "Rien",
    "gif": "GIF seul",
    "vinyl": "Vinyle",
    "cd": "CD",
    "cassette": "Cassette",
}

# Proportions du boîtier de cassette (largeur / hauteur).
CASSETTE_ASPECT = 1.6


def generated_cover(name, size=256):
    """
    Pochette de secours, déterministe : deux teintes tirées du nom du morceau
    plus ses initiales. Une piste sans GIF ni pochette reste présentable.
    """
    digest = hashlib.sha1((name or "?").encode("utf-8")).digest()
    hue = digest[0] / 255.0
    hue2 = (hue + 0.12 + digest[1] / 2550.0) % 1.0

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor.fromHsvF(hue, 0.55, 0.62))
    gradient.setColorAt(1, QColor.fromHsvF(hue2, 0.70, 0.32))
    painter.fillRect(0, 0, size, size, QBrush(gradient))

    initials = "".join(word[0] for word in str(name).split()[:2] if word).upper() or "♪"
    font = QFont()
    font.setPixelSize(int(size * 0.36))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 200))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    return pixmap


class MediaDisplay(QWidget):
    """Pochette animée. `clicked` permet de lire/mettre en pause au clic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Configuration
        self.skin = "vinyl"
        self.base_size = 120
        self._size_limit = None
        self.spin = True
        self.rpm = 33.3
        self.follow_nightcore = True
        self.insert_animation = True
        self.tonearm = True
        self.shine = True
        self.label_ratio = 0.36
        self.body_color = QColor("#141414")
        self.accent_color = QColor("#c8a45a")
        self.colorize = True
        self._palette = None

        # État de lecture
        self._position = 0.0      # secondes
        self._duration = 0.0
        self._playing = False
        self._rate = 1.0

        # Pochette
        self._movie = None
        self._pixmap = None
        self._track_name = ""

        self._insertion = 1.0
        self._insert_anim = None
        self.on_clicked = None

    # -- pochette ------------------------------------------------------

    def set_art(self, gif_path=None, image_path=None, track_name=""):
        """GIF animé en priorité, sinon image fixe, sinon pochette générée."""
        self._track_name = track_name or ""
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._pixmap = None

        if gif_path and os.path.isfile(gif_path):
            self._movie = QMovie(gif_path)
            # Les frames sont récupérées à la main dans paintEvent : on
            # redessine à chaque nouvelle image du GIF.
            self._movie.frameChanged.connect(self.update)
            self._movie.start()
        elif image_path and os.path.isfile(image_path):
            self._pixmap = QPixmap(image_path)
        else:
            self._pixmap = generated_cover(track_name)
        self._palette = None
        self.update()

    def current_art(self):
        if self._movie is not None:
            pixmap = self._movie.currentPixmap()
            if not pixmap.isNull():
                return pixmap
        if self._pixmap is not None and not self._pixmap.isNull():
            return self._pixmap
        return generated_cover(self._track_name)

    # -- état ----------------------------------------------------------

    def set_progress(self, position_ms, duration_ms):
        self._position = max(0.0, position_ms / 1000.0)
        self._duration = max(0.0, duration_ms / 1000.0)
        if self.skin != "none":
            self.update()

    def set_playing(self, playing):
        if playing != self._playing:
            self._playing = playing
            self.update()

    def set_rate(self, rate):
        if rate != self._rate:
            self._rate = float(rate)
            self.update()

    def configure(self, config):
        cfg = config.get("media", {})
        self.skin = cfg.get("skin", "vinyl")
        self.base_size = int(cfg.get("size", 120))
        self.spin = cfg.get("spin", True)
        self.rpm = float(cfg.get("rpm", 33.3))
        self.follow_nightcore = cfg.get("follow_nightcore", True)
        self.insert_animation = cfg.get("insert_animation", True)
        self.tonearm = cfg.get("tonearm", True)
        self.shine = cfg.get("shine", True)
        self.label_ratio = float(cfg.get("label_ratio", 0.36))
        self.body_color = QColor(cfg.get("body_color", "#141414"))
        self.accent_color = QColor(cfg.get("accent_color", "#c8a45a"))
        self.colorize = cfg.get("colorize", True)
        self._palette = None

        self.apply_size()
        self.update()

    def apply_size(self, size=None):
        """
        Pose la taille du support.

        `size` permet de descendre sous la valeur du JSON quand la fenêtre est
        trop petite pour l'accueillir (mode tiled) : le disque rétrécit au lieu
        de pousser les contrôles hors de la fenêtre.
        """
        if size is not None:
            # Limite imposée par la fenêtre : elle doit survivre aux
            # reconfigurations (changement de palette, rechargement du JSON),
            # sinon le support reprend sa taille du JSON et déborde.
            self._size_limit = max(0, int(size))
        size = self.base_size if self._size_limit is None \
            else min(self.base_size, self._size_limit)
        if self.skin == "none" or size <= 0:
            self.setVisible(False)
            self.setFixedSize(0, 0)
            return
        self.setVisible(True)
        if self.skin == "cassette":
            self.setFixedSize(int(size * CASSETTE_ASPECT), size)
        else:
            self.setFixedSize(size, size)

    # -- couleurs -------------------------------------------------------

    def cover_palette(self):
        """
        Palette de la pochette courante, calculée une fois puis mémorisée.

        Pour un GIF on analyse la frame affichée au moment du calcul : une
        pochette animée garde des couleurs stables au lieu de clignoter.
        """
        if self._palette is None:
            self._palette = palette_mod.extract(self.current_art())
        return self._palette

    def colors(self):
        """(corps, accent) : ceux de la pochette, ou ceux du JSON."""
        if not self.colorize:
            return QColor(self.body_color), QColor(self.accent_color)
        pal = self.cover_palette()
        return pal.tone(pal.dominant, 0.52, 0.22), pal.highlight()

    def tint(self, saturation, value, source="dominant"):
        """Variation libre autour de la teinte de la pochette."""
        if not self.colorize:
            return QColor(self.accent_color if source == "accent" else self.body_color)
        pal = self.cover_palette()
        base = pal.accent if source == "accent" else pal.dominant
        return pal.tone(base, saturation, value)

    # -- animation d'insertion -----------------------------------------

    def get_insertion(self):
        return self._insertion

    def set_insertion(self, value):
        self._insertion = float(value)
        self.update()

    insertion = pyqtProperty(float, fget=get_insertion, fset=set_insertion)

    def play_insert(self):
        """Le nouveau support se met en place (glissé + posé)."""
        if not self.insert_animation or self.skin in ("none", "gif"):
            self._insertion = 1.0
            self.update()
            return
        if self._insert_anim is not None:
            self._insert_anim.stop()
        self._insert_anim = QPropertyAnimation(self, b"insertion")
        self._insert_anim.setDuration(620)
        self._insert_anim.setStartValue(0.0)
        self._insert_anim.setEndValue(1.0)
        self._insert_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._insert_anim.start()

    # -- calculs --------------------------------------------------------

    def effective_rate(self):
        return self._rate if self.follow_nightcore else 1.0

    def rotation(self):
        """Angle en degrés, dérivé de la position de lecture."""
        if not self.spin:
            return 0.0
        return (self._position * self.rpm / 60.0) * 360.0 * self.effective_rate()

    def progress(self):
        if self._duration <= 0:
            return 0.0
        return max(0.0, min(1.0, self._position / self._duration))

    # -- rendu ----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and callable(self.on_clicked):
            self.on_clicked()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if self.skin == "none":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self.skin == "gif":
            self._paint_gif(painter)
        elif self.skin == "cassette":
            self._paint_cassette(painter)
        elif self.skin == "cd":
            self._paint_disc(painter, cd=True)
        else:
            self._paint_disc(painter, cd=False)

    def _art_brush(self, rect, art):
        """Pochette recadrée en « cover » dans `rect`."""
        scaled = art.scaled(
            int(rect.width()), int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        brush = QBrush(scaled)
        # Centre le pixmap sur le rectangle visé.
        from PyQt6.QtGui import QTransform
        brush.setTransform(QTransform().translate(
            rect.x() - (scaled.width() - rect.width()) / 2,
            rect.y() - (scaled.height() - rect.height()) / 2))
        return brush

    def _paint_gif(self, painter):
        art = self.current_art()
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._art_brush(rect, art))
        painter.drawRoundedRect(rect, 6, 6)

    # ---- vinyle / CD ---------------------------------------------------

    def _paint_disc(self, painter, cd=False):
        w, h = self.width(), self.height()
        side = min(w, h)
        insertion = self._insertion
        body_color, accent = self.colors()

        # Le disque descend et grandit légèrement en se mettant en place.
        offset_y = (1.0 - insertion) * -side * 0.55
        scale = 0.88 + 0.12 * insertion

        painter.save()
        painter.translate(w / 2, h / 2 + offset_y)
        painter.scale(scale, scale)
        painter.setOpacity(min(1.0, 0.35 + insertion))

        radius = side / 2 - 2
        disc = QRectF(-radius, -radius, radius * 2, radius * 2)

        # Ombre portée sous le disque, teintée elle aussi : une ombre grise sous
        # un disque coloré fait tache.
        painter.setPen(Qt.PenStyle.NoPen)
        shadow_color = QColor(body_color.darker(220))
        shadow = QRadialGradient(QPointF(0, 0), radius * 1.12)
        shadow.setColorAt(0.86, QColor(shadow_color.red(), shadow_color.green(),
                                       shadow_color.blue(), 110))
        shadow.setColorAt(1.0, QColor(shadow_color.red(), shadow_color.green(),
                                      shadow_color.blue(), 0))
        painter.setBrush(QBrush(shadow))
        painter.drawEllipse(disc.adjusted(-radius * 0.12, -radius * 0.12,
                                          radius * 0.12, radius * 0.12))

        painter.save()
        painter.rotate(self.rotation())

        if cd:
            self._paint_cd_body(painter, radius, disc, accent)
        else:
            self._paint_vinyl_body(painter, radius, disc, body_color, accent)

        # Étiquette : petite pastille sur un vinyle, surface imprimée sur un CD.
        if cd:
            label_radius = radius * 0.88
        else:
            label_radius = radius * max(0.12, min(0.8, self.label_ratio))
        label_rect = QRectF(-label_radius, -label_radius, label_radius * 2, label_radius * 2)
        path = QPainterPath()
        path.addEllipse(label_rect)
        painter.save()
        painter.setClipPath(path)
        painter.setBrush(self._art_brush(label_rect, self.current_art()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(label_rect)
        painter.restore()

        # Double liseré autour de l'étiquette, dans la couleur d'accent.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 210),
                            max(1.0, radius * 0.022)))
        painter.drawEllipse(label_rect)
        painter.setPen(QPen(QColor(0, 0, 0, 90), max(0.8, radius * 0.012)))
        painter.drawEllipse(label_rect.adjusted(radius * 0.03, radius * 0.03,
                                                -radius * 0.03, -radius * 0.03))

        if cd:
            # Anneau de gerbage et moyeu translucide du CD.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 90), max(0.8, radius * 0.012)))
            for factor in (0.30, 0.325):
                r = radius * factor
                painter.drawEllipse(QRectF(-r, -r, r * 2, r * 2))
            painter.setPen(Qt.PenStyle.NoPen)
            hub = radius * 0.28
            hub_grad = QConicalGradient(QPointF(0, 0), 20)
            for i in range(9):
                t = i / 8.0
                spectrum = QColor.fromHsvF((t * 0.9) % 1.0, 0.30, 0.99)
                hub_grad.setColorAt(t, self._blend(spectrum, accent, 0.35))
            painter.setBrush(QBrush(hub_grad))
            painter.drawEllipse(QRectF(-hub, -hub, hub * 2, hub * 2))

        # Trou central
        hole = radius * 0.045 if not cd else radius * 0.16
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body_color.darker(190) if not cd else QColor(230, 230, 235))
        painter.drawEllipse(QRectF(-hole, -hole, hole * 2, hole * 2))
        if cd:
            painter.setBrush(self.tint(0.30, 0.12))
            inner = hole * 0.55
            painter.drawEllipse(QRectF(-inner, -inner, inner * 2, inner * 2))

        painter.restore()  # fin de la rotation

        # Reflet fixe (il ne tourne pas avec le disque : c'est la lumière)
        if self.shine:
            sheen = QLinearGradient(-radius, -radius, radius, radius)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 0))
            sheen.setColorAt(0.42, QColor(255, 255, 255, 26))
            sheen.setColorAt(0.5, QColor(255, 255, 255, 60))
            sheen.setColorAt(0.58, QColor(255, 255, 255, 26))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(sheen))
            painter.drawEllipse(disc)

        painter.restore()

        if self.tonearm and not cd:
            self._paint_tonearm(painter, side, insertion, accent)

    @staticmethod
    def _blend(a, b, t):
        """Mélange RGB de deux couleurs (t = 0 → a, 1 → b)."""
        t = max(0.0, min(1.0, t))
        return QColor(int(a.red() + (b.red() - a.red()) * t),
                      int(a.green() + (b.green() - a.green()) * t),
                      int(a.blue() + (b.blue() - a.blue()) * t))

    def _paint_vinyl_body(self, painter, radius, disc, body_color, accent):
        painter.setPen(Qt.PenStyle.NoPen)
        base = QRadialGradient(QPointF(0, 0), radius)
        base.setColorAt(0.0, body_color.lighter(150))
        base.setColorAt(0.65, body_color)
        base.setColorAt(1.0, body_color.darker(140))
        painter.setBrush(QBrush(base))
        painter.drawEllipse(disc)

        # Sillons : teintés d'accent plutôt qu'en blanc, sinon le disque coloré
        # se retrouve strié de gris.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        groove = QColor(accent.red(), accent.green(), accent.blue(), 30)
        painter.setPen(QPen(groove, max(0.6, radius * 0.012)))
        rings = 22
        inner = radius * max(0.14, self.label_ratio) * 1.08
        for i in range(rings):
            r = inner + (radius * 0.94 - inner) * (i / rings)
            painter.drawEllipse(QRectF(-r, -r, r * 2, r * 2))

        # Un repère clair pour bien voir la rotation
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 120),
                            max(1.0, radius * 0.022)))
        painter.drawArc(disc.adjusted(radius * 0.06, radius * 0.06,
                                      -radius * 0.06, -radius * 0.06),
                        30 * 16, 26 * 16)

    def _paint_cd_body(self, painter, radius, disc, accent):
        painter.setPen(Qt.PenStyle.NoPen)
        # Irisation : dégradé conique qui parcourt le spectre, ramené vers la
        # couleur de la pochette pour que le CD appartienne au morceau.
        iridescent = QConicalGradient(QPointF(0, 0), 0)
        pull = 0.42 if self.colorize else 0.0
        for i in range(13):
            t = i / 12.0
            spectrum = QColor.fromHsvF((t * 0.94) % 1.0, 0.42, 0.97)
            iridescent.setColorAt(t, self._blend(spectrum, accent, pull))
        painter.setBrush(QBrush(iridescent))
        painter.drawEllipse(disc)

        # Voile léger : adoucit l'irisation sans l'effacer.
        veil = QRadialGradient(QPointF(0, 0), radius)
        veil.setColorAt(0.0, QColor(245, 245, 250, 60))
        veil.setColorAt(0.72, QColor(210, 210, 220, 30))
        veil.setColorAt(1.0, QColor(140, 140, 158, 90))
        painter.setBrush(QBrush(veil))
        painter.drawEllipse(disc)

    def _paint_tonearm(self, painter, side, insertion, accent):
        """
        Bras de lecture : il se pose quand ça joue, se relève en pause, et
        progresse vers le centre au fil du morceau.
        """
        painter.save()
        pivot = QPointF(self.width() * 0.86, self.height() * 0.14)
        painter.translate(pivot)

        rest_angle = 24.0          # relevé, sur son repose-bras
        start_angle = 52.0         # posé en bord de disque
        end_angle = 74.0           # arrivé près de l'étiquette
        if self._playing:
            angle = start_angle + (end_angle - start_angle) * self.progress()
        else:
            angle = rest_angle
        angle = rest_angle + (angle - rest_angle) * insertion
        painter.rotate(angle)

        length = side * 0.62
        arm = self._blend(QColor(215, 215, 220), accent, 0.30 if self.colorize else 0.0)
        painter.setPen(QPen(arm, max(1.5, side * 0.022),
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(0, 0), QPointF(0, length))

        # Cellule au bout du bras
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        head = side * 0.05
        painter.drawRoundedRect(
            QRectF(-head * 0.7, length - head * 0.6, head * 1.4, head * 1.7),
            head * 0.35, head * 0.35)
        painter.restore()

        # Axe du bras
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._blend(QColor(190, 190, 198), accent, 0.25 if self.colorize else 0.0))
        pivot_r = side * 0.055
        painter.drawEllipse(pivot, pivot_r, pivot_r)
        painter.setBrush(self._blend(QColor(120, 120, 130), accent, 0.35 if self.colorize else 0.0))
        painter.drawEllipse(pivot, pivot_r * 0.45, pivot_r * 0.45)

    # ---- cassette --------------------------------------------------------

    def _paint_cassette(self, painter):
        w, h = self.width(), self.height()
        insertion = self._insertion
        body_color, accent = self.colors()
        # Coque plus claire que le corps d'un vinyle : une cassette est un
        # boîtier plastique, pas un disque noir.
        shell_color = self.tint(0.42, 0.38) if self.colorize else body_color

        # La cassette entre par la gauche.
        painter.save()
        painter.translate(-(1.0 - insertion) * w * 0.75, 0)
        painter.setOpacity(min(1.0, 0.4 + insertion))

        body = QRectF(2, 2, w - 4, h - 4)
        radius = h * 0.07

        painter.setPen(Qt.PenStyle.NoPen)
        shell = QLinearGradient(0, 0, 0, h)
        shell.setColorAt(0, shell_color.lighter(145))
        shell.setColorAt(0.55, shell_color)
        shell.setColorAt(1, shell_color.darker(125))
        painter.setBrush(QBrush(shell))
        painter.drawRoundedRect(body, radius, radius)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 38), 1))
        painter.drawRoundedRect(body.adjusted(2, 2, -2, -2), radius, radius)

        # Étiquette : la pochette, en haut du boîtier
        label = QRectF(w * 0.08, h * 0.09, w * 0.84, h * 0.34)
        path = QPainterPath()
        path.addRoundedRect(label, radius * 0.6, radius * 0.6)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._art_brush(label, self.current_art()))
        painter.drawRect(label)
        # Deux bandes d'accent en haut de l'étiquette, comme sur les jaquettes
        # imprimées de l'époque.
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 190))
        painter.drawRect(QRectF(label.left(), label.top(), label.width(), h * 0.022))
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 110))
        painter.drawRect(QRectF(label.left(), label.top() + h * 0.028,
                                label.width(), h * 0.012))
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.4))
        painter.drawRoundedRect(label, radius * 0.6, radius * 0.6)

        # Fenêtre des bobines
        window = QRectF(w * 0.14, h * 0.48, w * 0.72, h * 0.34)
        painter.setPen(Qt.PenStyle.NoPen)
        inside = self.tint(0.55, 0.11) if self.colorize else QColor(20, 20, 24)
        inside.setAlpha(225)
        painter.setBrush(inside)
        painter.drawRoundedRect(window, radius * 0.5, radius * 0.5)

        progress = self.progress()
        hub_r = h * 0.055
        max_r = min(window.height() * 0.45, window.width() * 0.22)

        # La bande passe de la bobine gauche à la droite.
        left_r = hub_r + (max_r - hub_r) * (1.0 - progress)
        right_r = hub_r + (max_r - hub_r) * progress
        left_c = QPointF(window.center().x() - window.width() * 0.24, window.center().y())
        right_c = QPointF(window.center().x() + window.width() * 0.24, window.center().y())

        tape_dark = self.tint(0.72, 0.28, "accent") if self.colorize else QColor(70, 46, 30)
        tape_light = self.tint(0.66, 0.52, "accent") if self.colorize else QColor(120, 82, 52)

        # Vitesse inversement proportionnelle au rayon, comme une vraie bobine.
        base_angle = self.rotation()
        for center, tape_r, direction in ((left_c, left_r, 1.0), (right_c, right_r, 1.0)):
            self._paint_reel(painter, center, tape_r, hub_r,
                             base_angle * direction * (max_r / max(tape_r, 0.1)) * 0.35,
                             tape_dark, tape_light, accent)

        # Bande tendue entre les deux bobines
        painter.setPen(QPen(tape_light.darker(120), max(1.0, h * 0.012)))
        painter.drawLine(QPointF(left_c.x() + left_r, window.top() + window.height() * 0.5),
                         QPointF(right_c.x() - right_r, window.top() + window.height() * 0.5))

        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(window, radius * 0.5, radius * 0.5)

        # Ouvertures du bas + vis dans les coins : les détails qui font lire
        # « cassette » et non « rectangle ».
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        for i in range(3):
            x = w * (0.3 + i * 0.2)
            painter.drawRoundedRect(QRectF(x, h * 0.87, w * 0.08, h * 0.06), 2, 2)

        screw = self._blend(QColor(210, 210, 216), accent, 0.35 if self.colorize else 0.0)
        painter.setBrush(screw)
        screw_r = h * 0.018
        for sx, sy in ((0.06, 0.06), (0.94, 0.06), (0.06, 0.94), (0.94, 0.94)):
            painter.drawEllipse(QPointF(w * sx, h * sy), screw_r, screw_r)

        painter.restore()

    def _paint_reel(self, painter, center, tape_r, hub_r, angle,
                    tape_dark, tape_light, accent):
        painter.save()
        painter.translate(center)

        # Bande enroulée
        painter.setPen(Qt.PenStyle.NoPen)
        tape = QRadialGradient(QPointF(0, 0), tape_r)
        tape.setColorAt(0.0, tape_dark)
        tape.setColorAt(1.0, tape_light)
        painter.setBrush(QBrush(tape))
        painter.drawEllipse(QRectF(-tape_r, -tape_r, tape_r * 2, tape_r * 2))

        painter.rotate(angle)

        # Moyeu denté
        painter.setBrush(self._blend(QColor(232, 232, 238), accent,
                                     0.30 if self.colorize else 0.0))
        painter.drawEllipse(QRectF(-hub_r, -hub_r, hub_r * 2, hub_r * 2))
        painter.setBrush(tape_dark.darker(150))
        for i in range(6):
            a = math.radians(i * 60)
            tooth = hub_r * 0.34
            painter.drawEllipse(
                QPointF(math.cos(a) * hub_r * 0.55, math.sin(a) * hub_r * 0.55),
                tooth, tooth)
        painter.restore()
