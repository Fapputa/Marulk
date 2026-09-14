"""
Icônes vectorielles dessinées à la main.

Pourquoi ne pas se contenter de caractères Unicode : « ❮❮ » n'est pas un bouton
« piste précédente », c'est un chevron typographique, et son rendu dépend
entièrement de la police installée — avec une police décorative (le lecteur
laisse l'utilisateur en choisir une), la moitié des symboles tombe en tofu.

Ici, chaque icône est un chemin tracé dans un carré de 100×100 puis mis à
l'échelle du bouton. Rendu identique partout, net à toute taille, et la couleur
suit le thème (donc la pochette, en mode couleurs automatiques).
"""

import math

from PyQt6.QtCore import Qt, QRectF, QPointF, QSize
from PyQt6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush, QPixmap, QIcon, QTransform
)

BOX = 100.0  # repère de dessin


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _triangle(cx, cy, size, direction=1):
    """Triangle plein pointant à droite (direction=1) ou à gauche (-1)."""
    path = QPainterPath()
    half = size / 2
    path.moveTo(cx - half * 0.86 * direction, cy - half)
    path.lineTo(cx + half * 0.96 * direction, cy)
    path.lineTo(cx - half * 0.86 * direction, cy + half)
    path.closeSubpath()
    return path


def _bar(cx, cy, w, h, radius=None):
    path = QPainterPath()
    r = w * 0.35 if radius is None else radius
    path.addRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), r, r)
    return path


def _arrow_head(path, tip, angle_deg, size):
    """Pointe de flèche triangulaire au bout d'un arc."""
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -uy, ux
    path.moveTo(tip.x() + ux * size, tip.y() + uy * size)
    path.lineTo(tip.x() - ux * size * 0.35 + px * size * 0.85,
                tip.y() - uy * size * 0.35 + py * size * 0.85)
    path.lineTo(tip.x() - ux * size * 0.35 - px * size * 0.85,
                tip.y() - uy * size * 0.35 - py * size * 0.85)
    path.closeSubpath()


# ---------------------------------------------------------------------------
# Icônes : chacune renvoie (chemins_pleins, chemins_traits, épaisseur)
# ---------------------------------------------------------------------------

def _icon_play():
    return [_triangle(56, 50, 58, 1)], [], 0


def _icon_pause():
    return [_bar(38, 50, 15, 54), _bar(62, 50, 15, 54)], [], 0


def _icon_stop():
    path = QPainterPath()
    path.addRoundedRect(QRectF(28, 28, 44, 44), 8, 8)
    return [path], [], 0


def _icon_prev():
    """⏮ : la barre butoir + le triangle, le vrai pictogramme de transport."""
    return [_bar(28, 50, 13, 52, 4), _triangle(58, 50, 50, -1)], [], 0


def _icon_next():
    return [_bar(72, 50, 13, 52, 4), _triangle(42, 50, 50, 1)], [], 0


def _icon_rewind():
    """Double triangle : recul rapide."""
    return [_triangle(38, 50, 46, -1), _triangle(68, 50, 46, -1)], [], 0


def _icon_forward():
    return [_triangle(32, 50, 46, 1), _triangle(62, 50, 46, 1)], [], 0


def _arc_with_head(rect, start, sweep, head_size=13):
    """
    Arc + pointe de flèche posée exactement au bout du tracé.

    La pointe est placée via pointAtPercent/angleAtPercent plutôt que par un
    calcul trigonométrique refait à la main : impossible qu'elle dérive si on
    retouche l'arc.
    """
    stroke = QPainterPath()
    stroke.arcMoveTo(rect, start)
    stroke.arcTo(rect, start, sweep)
    head = QPainterPath()
    _arrow_head(head, stroke.pointAtPercent(1.0),
                -stroke.angleAtPercent(1.0), head_size)
    return stroke, head


def _icon_loop(one=False):
    stroke, head = _arc_with_head(QRectF(20, 24, 60, 52), 120, -300)
    fills = [head]
    if one:
        # Le « 1 » de la répétition d'une seule piste.
        digit = QPainterPath()
        digit.moveTo(43, 44)
        digit.lineTo(52, 37)
        digit.lineTo(52, 64)
        return fills, [stroke, digit], 9
    return fills, [stroke], 11


def _icon_loop_one():
    return _icon_loop(one=True)


def _icon_shuffle():
    """Deux trajets qui se croisent : c'est le geste, pas une simple double flèche."""
    a = QPainterPath()
    a.moveTo(14, 30)
    a.lineTo(34, 30)
    a.cubicTo(52, 30, 50, 70, 68, 70)
    b = QPainterPath()
    b.moveTo(14, 70)
    b.lineTo(34, 70)
    b.cubicTo(52, 70, 50, 30, 68, 30)
    heads = QPainterPath()
    _arrow_head(heads, QPointF(72, 70), 0, 12)
    _arrow_head(heads, QPointF(72, 30), 0, 12)
    return [heads], [a, b], 10


def _icon_moon():
    """
    ☽ — croissant obtenu en soustrayant un disque décalé d'un autre.
    Un vrai croissant, pas l'émoji 🌙 dont le rendu dépend de la police.
    """
    outer = QPainterPath()
    outer.addEllipse(QRectF(20, 14, 62, 72))
    inner = QPainterPath()
    inner.addEllipse(QRectF(40, 8, 62, 78))
    return [outer.subtracted(inner)], [], 0


def _icon_gear():
    path = QPainterPath()
    teeth = 8
    r_out, r_in, cx, cy = 44.0, 33.0, 50.0, 50.0
    for i in range(teeth * 2):
        angle = math.pi * i / teeth
        r = r_out if i % 2 == 0 else r_in
        # Dents légèrement biseautées : une roue crénelée, pas une étoile.
        for delta in (-0.10, 0.10):
            a = angle + delta * (1 if i % 2 == 0 else 0.6)
            point = QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r)
            if path.elementCount() == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(QRectF(cx - 15, cy - 15, 30, 30))
    return [path.subtracted(hole)], [], 0


def _icon_search():
    stroke = QPainterPath()
    stroke.addEllipse(QRectF(22, 20, 44, 44))
    handle = QPainterPath()
    handle.moveTo(62, 62)
    handle.lineTo(80, 80)
    return [], [stroke, handle], 11


def _icon_reload():
    stroke, head = _arc_with_head(QRectF(22, 22, 56, 56), 60, 300, 14)
    return [head], [stroke], 11


def _icon_minimize():
    return [_bar(50, 62, 48, 10, 5)], [], 0


def _icon_close():
    a = QPainterPath()
    a.moveTo(28, 28)
    a.lineTo(72, 72)
    b = QPainterPath()
    b.moveTo(72, 28)
    b.lineTo(28, 72)
    return [], [a, b], 12


def _speaker_body():
    path = QPainterPath()
    path.moveTo(16, 40)
    path.lineTo(32, 40)
    path.lineTo(52, 20)
    path.lineTo(52, 80)
    path.lineTo(32, 60)
    path.lineTo(16, 60)
    path.closeSubpath()
    return path


def _icon_volume():
    waves = []
    for i, radius in enumerate((14, 24)):
        arc = QPainterPath()
        rect = QRectF(60 - radius, 50 - radius, radius * 2, radius * 2)
        arc.arcMoveTo(rect, -55)
        arc.arcTo(rect, -55, 110)
        waves.append(arc)
    return [_speaker_body()], waves, 9


def _icon_mute():
    a = QPainterPath()
    a.moveTo(64, 36)
    a.lineTo(88, 64)
    b = QPainterPath()
    b.moveTo(88, 36)
    b.lineTo(64, 64)
    return [_speaker_body()], [a, b], 10


def _icon_pin():
    """Punaise : « garder au-dessus »."""
    path = QPainterPath()
    path.moveTo(38, 16)
    path.lineTo(72, 16)
    path.lineTo(66, 24)
    path.lineTo(70, 50)
    path.lineTo(80, 58)
    path.lineTo(30, 58)
    path.lineTo(40, 50)
    path.lineTo(44, 24)
    path.closeSubpath()
    needle = QPainterPath()
    needle.moveTo(55, 58)
    needle.lineTo(55, 86)
    return [path], [needle], 8


def _icon_palette():
    """Trois pastilles : le mode « couleurs de la pochette »."""
    body = QPainterPath()
    body.addEllipse(QRectF(14, 14, 72, 72))
    for cx, cy in ((38, 34), (64, 44), (44, 64)):
        hole = QPainterPath()
        hole.addEllipse(QRectF(cx - 9, cy - 9, 18, 18))
        body = body.subtracted(hole)
    return [body], [], 0


def _icon_disc():
    body = QPainterPath()
    body.addEllipse(QRectF(12, 12, 76, 76))
    hole = QPainterPath()
    hole.addEllipse(QRectF(42, 42, 16, 16))
    ring = QPainterPath()
    ring.addEllipse(QRectF(28, 28, 44, 44))
    return [body.subtracted(hole)], [ring], 5


def _icon_equalizer():
    # Barres posées sur une même ligne de base : une silhouette d'égaliseur.
    baseline = 80.0
    bars = [_bar(x, baseline - h / 2, 12, h, 6)
            for x, h in ((26, 34), (42, 62), (58, 44), (74, 70))]
    return bars, [], 0


def _icon_list():
    parts = []
    for y in (30, 50, 70):
        parts.append(_bar(30, y, 12, 12, 6))
        parts.append(_bar(62, y, 44, 10, 5))
    return parts, [], 0


def _icon_heart():
    path = QPainterPath()
    path.moveTo(50, 82)
    path.cubicTo(4, 52, 20, 14, 50, 34)
    path.cubicTo(80, 14, 96, 52, 50, 82)
    path.closeSubpath()
    return [path], [], 0


ICONS = {
    "play": _icon_play,
    "pause": _icon_pause,
    "stop": _icon_stop,
    "prev": _icon_prev,
    "next": _icon_next,
    "rewind": _icon_prev,
    "forward": _icon_next,
    "loop": _icon_loop,
    "loop_one": _icon_loop_one,
    "shuffle": _icon_shuffle,
    "nightcore": _icon_moon,
    "moon": _icon_moon,
    "config": _icon_gear,
    "search": _icon_search,
    "reload": _icon_reload,
    "minimize": _icon_minimize,
    "close": _icon_close,
    "volume": _icon_volume,
    "mute": _icon_mute,
    "pin": _icon_pin,
    "colorize": _icon_palette,
    "skin": _icon_disc,
    "viz": _icon_equalizer,
    "playlist": _icon_list,
    "like": _icon_heart,
}


def has_icon(name):
    return name in ICONS


def paint(painter, name, rect, color, rotation=0.0, scale=1.0):
    """Dessine l'icône `name` dans `rect`, avec rotation/échelle facultatives."""
    builder = ICONS.get(name)
    if builder is None:
        return
    fills, strokes, width = builder()

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center())
    factor = min(rect.width(), rect.height()) / BOX * scale
    if rotation:
        painter.rotate(rotation)
    painter.scale(factor, factor)
    painter.translate(-BOX / 2, -BOX / 2)

    color = QColor(color)
    if fills:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        for path in fills:
            painter.drawPath(path)
    if strokes:
        pen = QPen(color, width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for path in strokes:
            painter.drawPath(path)
    painter.restore()


def pixmap(name, size, color, ratio=1.0):
    """Icône rendue en QPixmap (utile pour QIcon / aperçus)."""
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    paint(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    return pm


def icon(name, size, color):
    return QIcon(pixmap(name, size, color))
