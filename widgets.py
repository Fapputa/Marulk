"""
Widgets peints à la main : boutons, barre de progression, barre de volume.

Trois choix structurants :

  * les boutons ne s'appuient plus sur une feuille de style Qt mais sur un
    paintEvent. Un QSS ne sait ni faire un halo, ni une onde de clic, ni une
    icône qui tourne — et l'ancienne animation redimensionnait le widget, donc
    relançait le layout à chaque survol (les voisins sautaient). Ici la taille
    du widget ne bouge jamais : c'est le contenu qui respire, dans une marge
    réservée pour ça ;
  * la barre de progression et celle du volume sont des widgets à part entière,
    avec accroche au survol, poignée lumineuse et reflet mobile. Impossible à
    obtenir avec QProgressBar::chunk ;
  * toutes les couleurs arrivent par `apply_colors()`, jamais en dur : c'est ce
    qui permet au mode « couleurs de la pochette » de repeindre tout le lecteur
    d'une piste à l'autre.
"""

import math

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QSize, QTimer, pyqtProperty, pyqtSignal,
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QPainterPath, QLinearGradient, QFont,
    QRadialGradient, QPixmap, QFontMetrics
)
from PyQt6.QtWidgets import QWidget, QAbstractButton

from core import icons

# Boutons dont l'icône fait un tour sur elle-même quand on clique : ceux dont
# l'action est elle-même une rotation ou un brassage.
SPIN_ON_CLICK = {"reload", "loop", "shuffle", "nightcore", "skin", "viz"}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _with_alpha(color, alpha):
    color = QColor(color)
    color.setAlpha(int(_clamp(alpha) * 255))
    return color


def _lerp_color(a, b, t):
    a, b = QColor(a), QColor(b)
    t = _clamp(t)
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def readable_on(color):
    c = QColor(color)
    luminance = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255
    return QColor("#101014") if luminance > 0.6 else QColor("#ffffff")


# ===========================================================================
# Bouton
# ===========================================================================

class IconButton(QAbstractButton):
    """
    Bouton à icône vectorielle, entièrement peint.

    Animations disponibles (toutes pilotées par la section `animations` du
    JSON) : agrandissement au survol, enfoncement au clic, halo, onde de clic,
    rotation de l'icône, et battement lent quand la bascule est active.
    """

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.icon_name = name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Style (rempli par configure)
        self._cfg = {}
        self._anim_cfg = {}
        self._cfg_size = (30, 30)
        self._base_size = (30, 30)
        self._size_scale = 1.0
        self._pad = 6
        self._shape = "rounded"
        self._bg = QColor("#613583")
        self._fg = QColor("#ffffff")
        self._accent = QColor("#ffffff")
        self._opacity = 1.0
        self._border_width = 0
        self._border_color = QColor("#000000")
        self._image = None
        self._active = False
        self._flat = False

        # États d'animation
        self._scale = 1.0
        self._glow = 0.0
        self._ripple = 0.0
        self._ripple_origin = QPointF()
        self._spin = 0.0
        self._pulse = 0.0
        self._hovered = False

        self._anims = {}
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(33)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_phase = 0.0

    # -- propriétés animables ------------------------------------------

    def _make_prop(name):
        def getter(self):
            return getattr(self, "_" + name)

        def setter(self, value):
            setattr(self, "_" + name, float(value))
            self.update()
        return pyqtProperty(float, fget=getter, fset=setter)

    scale = _make_prop("scale")
    glow = _make_prop("glow")
    ripple = _make_prop("ripple")
    spin = _make_prop("spin")
    del _make_prop

    # -- configuration --------------------------------------------------

    def configure(self, cfg, anim_cfg, fallback_text="#ffffff", accent="#ffffff",
                  flat=False):
        self._cfg = dict(cfg or {})
        self._anim_cfg = dict(anim_cfg or {})
        self._flat = flat

        size = self._cfg.get("size", [30, 30])
        self._cfg_size = (int(size[0]), int(size[1]))
        self._resize()

        self._shape = self._cfg.get("shape", "rounded")
        self._bg = QColor(self._cfg.get("color", "#613583"))
        self._fg = QColor(self._cfg.get("text_color") or fallback_text)
        self._accent = QColor(accent)
        self._opacity = float(self._cfg.get("opacity", 1.0))
        self._border_width = int(self._cfg.get("border_width", 0) or 0)
        self._border_color = QColor(self._cfg.get("border_color", "#000000"))

        path = self._cfg.get("image_path", "")
        self._image = QPixmap(path) if path else None
        if self._image is not None and self._image.isNull():
            self._image = None

        self._refresh_pulse()
        self.update()

    def size_scale(self):
        return self._size_scale

    def set_size_scale(self, factor):
        """
        Réduit le bouton sans toucher au JSON.

        Sert quand la fenêtre est plus étroite que la rangée de boutons (mode
        tiled) : mieux vaut des boutons un peu plus petits que des boutons qui
        sortent du cadre.
        """
        factor = _clamp(float(factor), 0.5, 1.0)
        if abs(factor - self._size_scale) < 0.01:
            return
        self._size_scale = factor
        self._resize()
        self.update()

    def _resize(self):
        w, h = self._cfg_size
        f = self._size_scale
        self._base_size = (max(12, int(round(w * f))), max(12, int(round(h * f))))
        # Marge de respiration : le widget ne change jamais de taille, donc
        # l'agrandissement au survol ne bouscule pas la mise en page.
        hover = float(self._anim_cfg.get("hover_scale", 1.1))
        self._pad = max(2, int(min(self._base_size) * (max(hover, 1.0) - 1.0) + 4 * f))
        self.setFixedSize(self._base_size[0] + self._pad * 2,
                          self._base_size[1] + self._pad * 2)

    def apply_colors(self, background=None, foreground=None, accent=None):
        """Recolorisation à chaud (mode couleurs de la pochette)."""
        if background is not None:
            self._bg = QColor(background)
        if foreground is not None:
            self._fg = QColor(foreground)
        if accent is not None:
            self._accent = QColor(accent)
        self.update()

    def set_icon_name(self, name):
        if name != self.icon_name:
            self.icon_name = name
            self.update()

    def set_active(self, active):
        if bool(active) != self._active:
            self._active = bool(active)
            self._refresh_pulse()
            self.update()

    def is_active(self):
        return self._active

    # -- géométrie -------------------------------------------------------

    def content_rect(self):
        w, h = self._base_size
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _radius(self, rect):
        if self._shape == "circle":
            return min(rect.width(), rect.height()) / 2
        if self._shape == "rounded":
            return max(4.0, min(rect.width(), rect.height()) / 4)
        return 0.0

    def _shape_path(self, rect):
        path = QPainterPath()
        radius = self._radius(rect)
        if radius >= min(rect.width(), rect.height()) / 2:
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, radius, radius)
        return path

    def sizeHint(self):
        return QSize(self._base_size[0] + self._pad * 2,
                     self._base_size[1] + self._pad * 2)

    # -- animations -------------------------------------------------------

    def _enabled(self, key):
        return self._anim_cfg.get("enabled", True) and self._anim_cfg.get(key, True)

    def _animate(self, prop, target, duration, curve=QEasingCurve.Type.OutCubic):
        anim = self._anims.get(prop)
        if anim is not None:
            anim.stop()
        anim = QPropertyAnimation(self, prop.encode())
        anim.setDuration(max(1, int(duration)))
        anim.setStartValue(getattr(self, "_" + prop))
        anim.setEndValue(float(target))
        anim.setEasingCurve(curve)
        self._anims[prop] = anim
        anim.start()

    def _duration(self, factor=1.0):
        return int(self._anim_cfg.get("duration", 150) * factor)

    def _refresh_pulse(self):
        wants = (self._active and self._enabled("pulse_enabled")
                 and self._anim_cfg.get("enabled", True))
        if wants and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif not wants and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._pulse = 0.0
            self.update()

    def _tick_pulse(self):
        self._pulse_phase += 0.08
        self._pulse = (math.sin(self._pulse_phase) + 1) / 2
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        if self._enabled("hover_enabled"):
            self._animate("scale", float(self._anim_cfg.get("hover_scale", 1.1)),
                          self._duration(), QEasingCurve.Type.OutBack)
        if self._enabled("glow_enabled"):
            self._animate("glow", 1.0, self._duration(1.4))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._enabled("hover_enabled"):
            self._animate("scale", 1.0, self._duration(), QEasingCurve.Type.OutCubic)
        if self._enabled("glow_enabled"):
            self._animate("glow", 0.0, self._duration(1.6))
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._enabled("click_enabled"):
                self._animate("scale", float(self._anim_cfg.get("click_scale", 0.95)),
                              self._duration(0.5))
            if self._enabled("ripple_enabled"):
                self._ripple_origin = event.position()
                self._ripple = 0.0
                self._animate("ripple", 1.0, self._duration(3.2),
                              QEasingCurve.Type.OutQuad)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._enabled("click_enabled"):
            target = float(self._anim_cfg.get("hover_scale", 1.1)) \
                if (self._hovered and self._enabled("hover_enabled")) else 1.0
            self._animate("scale", target, self._duration(0.6),
                          QEasingCurve.Type.OutBack)
        super().mouseReleaseEvent(event)

    def click_feedback(self):
        """Rotation d'un tour : appelée quand l'action du bouton l'évoque."""
        if self.name in SPIN_ON_CLICK and self._enabled("spin_enabled"):
            self._spin = 0.0
            self._animate("spin", 360.0, self._duration(4.0),
                          QEasingCurve.Type.OutCubic)

    # -- rendu -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self.content_rect()
        center = rect.center()
        scale = self._scale + self._pulse * 0.04
        scaled = QRectF(0, 0, rect.width() * scale, rect.height() * scale)
        scaled.moveCenter(center)
        path = self._shape_path(scaled)

        # Halo : survol + battement de l'état actif.
        halo = max(self._glow, self._pulse * 0.75 if self._active else 0.0)
        if halo > 0.01 and not self._flat:
            strength = float(self._anim_cfg.get("glow_strength", 1.0))
            color = self._accent if self._active else self._bg.lighter(140)
            radius = max(scaled.width(), scaled.height()) * (0.62 + 0.22 * halo)
            gradient = QRadialGradient(center, radius)
            gradient.setColorAt(0.45, _with_alpha(color, 0.42 * halo * strength))
            gradient.setColorAt(1.0, _with_alpha(color, 0.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawEllipse(center, radius, radius)

        painter.save()
        painter.setOpacity(self._opacity)

        # Corps : léger dégradé vertical, éclairci au survol, assombri au clic.
        top = self._bg.lighter(int(112 + 16 * self._glow))
        bottom = self._bg.darker(int(108 + 6 * (1.0 - self._glow)))
        if self.isDown():
            top, bottom = self._bg.darker(118), self._bg.darker(130)
        if self._active:
            top = _lerp_color(top, self._accent, 0.22)
            bottom = _lerp_color(bottom, self._accent, 0.10)

        if not self._flat:
            body = QLinearGradient(scaled.topLeft(), scaled.bottomLeft())
            body.setColorAt(0.0, top)
            body.setColorAt(1.0, bottom)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(body))
            painter.drawPath(path)

        # Image de fond éventuelle (option `image_path` du JSON).
        if self._image is not None:
            painter.save()
            painter.setClipPath(path)
            art = self._image.scaled(
                int(scaled.width()), int(scaled.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(
                QPointF(scaled.center().x() - art.width() / 2,
                        scaled.center().y() - art.height() / 2), art)
            painter.restore()

        # Onde de clic, contenue dans la forme du bouton.
        if self._ripple > 0.001:
            painter.save()
            painter.setClipPath(path)
            reach = max(scaled.width(), scaled.height()) * 1.35
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_with_alpha(QColor("#ffffff"), 0.30 * (1.0 - self._ripple)))
            painter.drawEllipse(self._ripple_origin,
                                reach * self._ripple, reach * self._ripple)
            painter.restore()

        # Bordure : celle du JSON, ou le liseré d'accent quand la bascule est active.
        border_w = self._border_width
        border_c = self._border_color
        if self._active:
            border_w = max(2, border_w)
            border_c = self._accent
        if border_w:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(border_c, border_w))
            painter.drawPath(path)

        painter.restore()

        # Icône
        icon_color = self._fg
        if self._active:
            icon_color = _lerp_color(self._fg, self._accent, 0.55)
            # Sur fond déjà teinté d'accent, l'accent pur deviendrait illisible.
            if abs(icon_color.lightness() - self._bg.lightness()) < 40:
                icon_color = readable_on(self._bg)
        inner = scaled.adjusted(scaled.width() * 0.24, scaled.height() * 0.24,
                                -scaled.width() * 0.24, -scaled.height() * 0.24)
        if icons.has_icon(self.icon_name) and self._image is None:
            icons.paint(painter, self.icon_name, inner, icon_color,
                        rotation=self._spin)


# ===========================================================================
# Barres
# ===========================================================================

class _Bar(QWidget):
    """
    Base commune aux deux barres : piste en pilule, remplissage dégradé,
    poignée ronde et étiquette flottante.

    Deux règles de géométrie, qui règlent les défauts visuels de l'ancienne
    version :

      * la piste est **rentrée** horizontalement de la taille de la poignée.
        Sans cet encart, la poignée était coupée en deux à 0 % et à 100 %, et
        le remplissage collait au bord du widget ;
      * la marge verticale n'est plus une constante : elle est calculée depuis
        le rayon de la poignée et son halo, donc rien ne déborde du widget —
        ce qui, dans une fenêtre trop courte (mode tiled), se traduisait par
        des barres qui mordaient sur leurs voisins.

    `set_compact()` resserre le tout quand la place manque : la barre reste
    lisible, seule la respiration disparaît.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self.bar_height = 10
        self.radius = 5
        self.fill_color = QColor("#d09dd2")
        self.track_color = QColor("#350b4a")
        self.accent = QColor("#ffffff")
        self.style_name = "gradient"
        self.glow = True
        self.knob = True
        self.animated = True

        self._compact = False
        self._margin = 7
        self._expand = 0.0
        self._hover_ratio = None
        self._dragging = False
        self._phase = 0.0
        self._expand_anim = None

        self._shimmer = QTimer(self)
        self._shimmer.setInterval(33)
        self._shimmer.timeout.connect(self._tick)

    # -- style -----------------------------------------------------------

    def _apply_common(self, cfg):
        self.bar_height = max(3, int(cfg.get("height", 10)))
        self.radius = int(cfg.get("radius", self.bar_height // 2))
        self.style_name = cfg.get("style", "gradient")
        self.glow = bool(cfg.get("glow", True))
        self.knob = bool(cfg.get("knob", True))
        self._relayout()
        self._refresh_shimmer()
        self.update()

    def set_compact(self, compact):
        """Mode serré : marges minimales, halo coupé (fenêtres courtes)."""
        compact = bool(compact)
        if compact != self._compact:
            self._compact = compact
            self._relayout()
            self.update()

    def _relayout(self):
        self._margin = int(math.ceil(self._knob_radius(1.0) + (1 if self._compact else 3)))
        self.setFixedHeight(int(self.bar_height + self._expand_room() + self._margin * 2))

    def _expand_room(self):
        """Place réservée à l'épaississement de la piste au survol."""
        return 0.0 if self._compact else max(2.0, self.bar_height * 0.35)

    def _knob_radius(self, expand=None):
        if not self.knob:
            return self.bar_height / 2
        expand = self._expand if expand is None else expand
        base = self.bar_height * 0.55 + (2.0 if self._compact else 3.0)
        return base * (1.0 + 0.18 * expand)

    def apply_colors(self, fill=None, track=None, accent=None):
        if fill is not None:
            self.fill_color = QColor(fill)
        if track is not None:
            self.track_color = QColor(track)
        if accent is not None:
            self.accent = QColor(accent)
        self.update()

    def _refresh_shimmer(self):
        wants = self.animated and self.style_name in ("gradient", "glass", "neon") \
            and self.isVisible() and self._should_shimmer()
        if wants and not self._shimmer.isActive():
            self._shimmer.start()
        elif not wants and self._shimmer.isActive():
            self._shimmer.stop()

    def _should_shimmer(self):
        return True

    def _tick(self):
        self._phase = (self._phase + 0.009) % 1.0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_shimmer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._shimmer.stop()

    # -- géométrie -------------------------------------------------------

    def track_rect(self):
        height = self.bar_height + self._expand * self._expand_room()
        inset = self._knob_radius(1.0) if self.knob else 0.0
        # Toujours laisser une piste utilisable, même dans une fenêtre étroite.
        inset = min(inset, max(0.0, (self.width() - 24) / 2))
        return QRectF(inset, (self.height() - height) / 2,
                      max(1.0, self.width() - inset * 2), height)

    def _track_path(self, rect=None):
        rect = self.track_rect() if rect is None else rect
        radius = min(self.radius + self._expand, rect.height() / 2) \
            if self.radius else 0.0
        path = QPainterPath()
        if radius <= 0:
            path.addRect(rect)
        else:
            path.addRoundedRect(rect, radius, radius)
        return path

    def ratio_at(self, x):
        rect = self.track_rect()
        return _clamp((x - rect.left()) / max(1.0, rect.width()))

    def value_ratio(self):
        raise NotImplementedError

    # -- survol ------------------------------------------------------------

    def _animate_expand(self, target):
        if self._expand_anim is not None:
            self._expand_anim.stop()
        self._expand_anim = QPropertyAnimation(self, b"expand")
        self._expand_anim.setDuration(160)
        self._expand_anim.setStartValue(self._expand)
        self._expand_anim.setEndValue(float(target))
        self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._expand_anim.start()

    def get_expand(self):
        return self._expand

    def set_expand(self, value):
        self._expand = float(value)
        self.update()

    expand = pyqtProperty(float, fget=get_expand, fset=set_expand)

    def enterEvent(self, event):
        self._animate_expand(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_ratio = None
        self._animate_expand(0.0)
        super().leaveEvent(event)

    # -- rendu partagé ------------------------------------------------------

    def _paint_track(self, painter, path, rect):
        """Piste creusée : dégradé sombre en haut, liseré clair en bas."""
        painter.setPen(Qt.PenStyle.NoPen)
        base = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        base.setColorAt(0.0, self.track_color.darker(135))
        base.setColorAt(0.65, self.track_color)
        base.setColorAt(1.0, self.track_color.lighter(118))
        painter.setBrush(QBrush(base))
        painter.drawPath(path)

        # Cerne discret : détache la barre d'un fond clair comme d'un fond
        # sombre, sans ajouter de couleur.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(QColor("#000000"), 0.22), 1))
        painter.drawPath(path)

    def _fill_gradient(self, rect):
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        if self.style_name == "neon":
            gradient.setColorAt(0.0, self.fill_color.darker(150))
            gradient.setColorAt(0.6, self.fill_color)
            gradient.setColorAt(1.0, _lerp_color(self.fill_color, self.accent, 0.9).lighter(115))
        elif self.style_name == "flat":
            gradient.setColorAt(0.0, self.fill_color)
            gradient.setColorAt(1.0, self.fill_color)
        else:
            gradient.setColorAt(0.0, _lerp_color(self.fill_color, self.accent, 0.28).darker(105))
            gradient.setColorAt(1.0, self.fill_color.lighter(112))
        return gradient

    def _paint_fill(self, painter, path, rect, ratio, playing=True):
        if ratio <= 0.0005:
            return
        filled = QRectF(rect.left(), rect.top(), rect.width() * ratio, rect.height())
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._fill_gradient(rect)))
        painter.drawRect(filled)

        if self.style_name == "segments":
            # Barre découpée en segments : lecture « niveau », très lisible.
            painter.setBrush(_with_alpha(QColor("#000000"), 0.40))
            step = max(5.0, rect.height() * 1.15)
            x = rect.left() + step * 0.72
            while x < filled.right():
                painter.drawRect(QRectF(x, rect.top(), max(1.2, step * 0.20), rect.height()))
                x += step
        elif self.style_name != "flat":
            # Un seul filet de lumière sur le tiers haut : ça donne le relief
            # d'une pilule sans le vernis plastique de l'ancien reflet.
            gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gloss.setColorAt(0.0, _with_alpha(QColor("#ffffff"), 0.26))
            gloss.setColorAt(0.38, _with_alpha(QColor("#ffffff"), 0.05))
            gloss.setColorAt(1.0, _with_alpha(QColor("#000000"), 0.10))
            painter.setBrush(QBrush(gloss))
            painter.drawRect(filled)

        # Reflet qui balaie la partie remplie : le lecteur a l'air vivant même
        # quand la progression est lente.
        if self.animated and self._shimmer.isActive() and filled.width() > 8:
            span = max(24.0, filled.width() * 0.22)
            head = filled.left() - span + (filled.width() + span * 2) * self._phase
            sweep = QLinearGradient(head - span / 2, 0, head + span / 2, 0)
            sweep.setColorAt(0.0, _with_alpha(QColor("#ffffff"), 0.0))
            sweep.setColorAt(0.5, _with_alpha(QColor("#ffffff"), 0.16))
            sweep.setColorAt(1.0, _with_alpha(QColor("#ffffff"), 0.0))
            painter.setBrush(QBrush(sweep))
            painter.drawRect(filled)
        painter.restore()

        if self.glow and self.style_name == "neon":
            painter.save()
            painter.setClipPath(path)
            painter.setPen(QPen(_with_alpha(self.fill_color, 0.45),
                                2 + self._expand * 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()

    def _paint_knob(self, painter, rect, ratio, emphasis=0.0):
        """Pastille claire cerclée d'accent : nette, et jamais rognée."""
        if not self.knob:
            return
        x = rect.left() + rect.width() * ratio
        y = rect.center().y()
        radius = self._knob_radius() + emphasis

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)

        if self.glow and not self._compact:
            halo_r = radius * (1.7 + 0.5 * self._expand)
            halo_r = min(halo_r, self._margin + rect.height() / 2)
            halo = QRadialGradient(QPointF(x, y), halo_r)
            halo.setColorAt(0.0, _with_alpha(self.accent, 0.32 + 0.18 * self._expand))
            halo.setColorAt(0.55, _with_alpha(self.accent, 0.16))
            halo.setColorAt(1.0, _with_alpha(self.accent, 0.0))
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(x, y), halo_r, halo_r)

        # Ombre portée : la poignée flotte au-dessus de la piste.
        painter.setBrush(_with_alpha(QColor("#000000"), 0.28))
        painter.drawEllipse(QPointF(x, y + radius * 0.16), radius, radius)

        body = QRadialGradient(QPointF(x - radius * 0.35, y - radius * 0.45), radius * 1.9)
        body.setColorAt(0.0, QColor("#ffffff"))
        body.setColorAt(1.0, _lerp_color(QColor("#ffffff"), self.accent, 0.55))
        painter.setBrush(QBrush(body))
        painter.drawEllipse(QPointF(x, y), radius, radius)

        # Cerne intérieur : il matérialise la poignée même sur un thème tout
        # blanc, où corps et accent se confondraient.
        ring = _lerp_color(self.fill_color, self.accent, 0.4)
        if readable_on(ring) == QColor("#101014"):
            ring = ring.darker(155)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(ring, 0.9), max(1.0, radius * 0.22)))
        painter.drawEllipse(QPointF(x, y), radius * 0.82, radius * 0.82)

        painter.setPen(QPen(_with_alpha(QColor("#000000"), 0.18), 1))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.restore()

    def _paint_bubble(self, painter, x, text):
        """
        Étiquette flottante logée dans la marge haute.

        Sa police est dimensionnée d'après cette marge : dans une fenêtre
        serrée elle rétrécit au lieu de dépasser sur le widget du dessus.
        """
        top = self.track_rect().top()
        available = max(9.0, top - 1)
        font = QFont(self.font())
        font.setPixelSize(int(_clamp((available - 4) / 1.35, 7, 13)))
        painter.save()
        painter.setFont(font)
        metrics = QFontMetrics(font)

        height = min(available, metrics.height() + 3)
        width = metrics.horizontalAdvance(text) + height * 0.9
        left = _clamp(x - width / 2, 0, max(0.0, self.width() - width))
        rect = QRectF(left, max(0.0, top - height - 1), width, height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_with_alpha(QColor("#101014"), 0.80))
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(_with_alpha(QColor("#ffffff"), 0.92))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class SeekBar(_Bar):
    """Barre de progression : cliquable, survolable, avec aperçu du temps visé."""

    seeked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.position_ms = 0
        self.duration_ms = 0
        self.playing = False

    def configure(self, cfg):
        self.fill_color = QColor(cfg.get("color", "#d09dd2"))
        self.track_color = QColor(cfg.get("background_color", "#350b4a"))
        self.animated = bool(cfg.get("animated", True))
        self._apply_common(cfg)

    def _should_shimmer(self):
        return self.playing

    def set_progress(self, position_ms, duration_ms):
        self.position_ms = max(0, int(position_ms))
        self.duration_ms = max(0, int(duration_ms))
        self.update()

    def set_playing(self, playing):
        if playing != self.playing:
            self.playing = bool(playing)
            self._refresh_shimmer()
            self.update()

    def value_ratio(self):
        if self.duration_ms <= 0:
            return 0.0
        return _clamp(self.position_ms / self.duration_ms)

    # -- interaction -------------------------------------------------------

    def _seek_to(self, x):
        if self.duration_ms > 0:
            self.seeked.emit(int(self.ratio_at(x) * self.duration_ms))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._seek_to(event.position().x())

    def mouseMoveEvent(self, event):
        self._hover_ratio = self.ratio_at(event.position().x())
        if self._dragging:
            self._seek_to(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    # -- rendu ---------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.track_rect()
        path = self._track_path(rect)

        self._paint_track(painter, path, rect)

        # Repère du point visé, sous le remplissage : on voit où l'on va sans
        # perdre de vue où l'on en est.
        if self._hover_ratio is not None and self.duration_ms > 0:
            painter.save()
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_with_alpha(self.fill_color, 0.26))
            painter.drawRect(QRectF(rect.left(), rect.top(),
                                    rect.width() * self._hover_ratio, rect.height()))
            painter.restore()

        self._paint_fill(painter, path, rect, self.value_ratio(), self.playing)
        self._paint_knob(painter, rect, self.value_ratio())

        if self._hover_ratio is not None and self.duration_ms > 0:
            x = rect.left() + rect.width() * self._hover_ratio
            painter.setPen(QPen(_with_alpha(QColor("#ffffff"), 0.65), 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            target = int(self._hover_ratio * self.duration_ms) // 1000
            self._paint_bubble(painter, x, f"{target // 60:02}:{target % 60:02}")


class VolumeBar(_Bar):
    """Barre de volume : glisser, molette, et graduations qui montrent l'échelle."""

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 70
        self.slider_shape = "rounded"
        self.animated = False

    def configure(self, cfg):
        self.fill_color = QColor(cfg.get("slider_color", "#ffffff"))
        self.track_color = QColor(cfg.get("background_color", "#62a0ea"))
        self.slider_shape = cfg.get("slider_shape", "rounded")
        self.animated = bool(cfg.get("animated", False))
        merged = dict(cfg)
        if self.slider_shape == "square":
            merged["radius"] = 0
        self._apply_common(merged)

    def value(self):
        return self._value

    def setValue(self, value):
        value = int(_clamp(float(value), 0, 100))
        if value != self._value:
            self._value = value
            self.valueChanged.emit(value)
        self.update()

    def value_ratio(self):
        return self._value / 100.0

    # -- interaction ---------------------------------------------------------

    def _set_from_x(self, x):
        self.setValue(round(self.ratio_at(x) * 100))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        self._hover_ratio = self.ratio_at(event.position().x())
        if self._dragging:
            self._set_from_x(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def wheelEvent(self, event):
        step = 5 if event.angleDelta().y() > 0 else -5
        self.setValue(self._value + step)
        event.accept()

    # -- rendu ----------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.track_rect()
        path = self._track_path(rect)

        self._paint_track(painter, path, rect)
        self._paint_fill(painter, path, rect, self.value_ratio())

        # Graduations tous les 25 % : elles situent le niveau d'un coup d'œil,
        # et s'effacent presque quand la souris est ailleurs.
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        strength = 0.16 + 0.16 * self._expand
        for i in range(1, 4):
            x = rect.left() + rect.width() * (i / 4)
            over = self.value_ratio() >= i / 4
            painter.setBrush(_with_alpha(QColor("#000000" if over else "#ffffff"), strength))
            painter.drawRect(QRectF(x - 0.6, rect.top(), 1.2, rect.height()))
        painter.restore()

        self._paint_knob(painter, rect, self.value_ratio())

        if self._dragging or self._hover_ratio is not None:
            x = rect.left() + rect.width() * self.value_ratio()
            self._paint_bubble(painter, x, f"{self._value} %")
