"""
Extraction de palette depuis une pochette.

Le lecteur peut se teindre entièrement aux couleurs du morceau en cours : fond,
boutons, barres, visualiseur, disque. Tout part d'ici.

La méthode : on réduit la pochette à une vignette, on range les pixels dans des
casiers teinte/saturation/valeur, et on pondère chaque casier par sa saturation.
Sans cette pondération, une pochette sombre renvoie systématiquement du gris —
techniquement dominant, visuellement inutilisable. On veut la couleur qu'un
humain citerait s'il regardait la pochette, pas la moyenne arithmétique.
"""

import colorsys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap

# Taille de la vignette d'analyse : assez grande pour rester fidèle, assez
# petite pour que l'extraction soit imperceptible à chaque changement de piste.
THUMB = 56

HUE_BINS = 16
SAT_BINS = 3
VAL_BINS = 4


def _bucket(h, s, v):
    return (min(HUE_BINS - 1, int(h * HUE_BINS)),
            min(SAT_BINS - 1, int(s * SAT_BINS)),
            min(VAL_BINS - 1, int(v * VAL_BINS)))


def _hue_distance(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


class Palette:
    """Jeu de couleurs cohérent tiré d'une pochette."""

    def __init__(self, dominant, accent, neutral):
        self.dominant = QColor(dominant)
        self.accent = QColor(accent)
        self.neutral = QColor(neutral)

    # -- variations ----------------------------------------------------

    def _hsv(self, color):
        return color.hueF() if color.hueF() >= 0 else 0.0, color.saturationF(), color.valueF()

    def tone(self, color, saturation, value):
        """Même teinte, saturation/valeur imposées."""
        h, s, _ = self._hsv(color)
        # Une couleur quasi grise n'a pas de teinte exploitable : on garde sa
        # désaturation plutôt que d'inventer un ton criard.
        sat = saturation if s > 0.08 else min(saturation, 0.12)
        return QColor.fromHsvF(max(0.0, min(1.0, h)),
                               max(0.0, min(1.0, sat)),
                               max(0.0, min(1.0, value)))

    def background(self, strength=1.0):
        return self.mix(QColor("#141118"), self.tone(self.dominant, 0.55, 0.22), strength)

    def surface(self, strength=1.0):
        return self.mix(QColor("#20202a"), self.tone(self.dominant, 0.45, 0.34), strength)

    def primary(self, strength=1.0):
        return self.mix(QColor("#5a5a68"), self.tone(self.dominant, 0.58, 0.52), strength)

    def highlight(self, strength=1.0):
        return self.mix(QColor("#c9c9d6"), self.tone(self.accent, 0.72, 0.86), strength)

    def soft(self, strength=1.0):
        return self.mix(QColor("#8f8f9e"), self.tone(self.accent, 0.35, 0.93), strength)

    @staticmethod
    def mix(a, b, t):
        """Interpolation linéaire RGB entre deux couleurs (t = 0 → a, 1 → b)."""
        t = max(0.0, min(1.0, float(t)))
        a, b = QColor(a), QColor(b)
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    def __repr__(self):
        return (f"Palette(dominant={self.dominant.name()}, "
                f"accent={self.accent.name()}, neutral={self.neutral.name()})")


NEUTRAL_PALETTE = Palette("#6b5a8a", "#c9a7e8", "#8a8a96")


def extract(source):
    """
    Palette d'un QPixmap / QImage / chemin de fichier.

    Renvoie toujours une palette utilisable : une pochette illisible retombe sur
    NEUTRAL_PALETTE plutôt que sur du noir.
    """
    image = _to_image(source)
    if image is None or image.isNull():
        return NEUTRAL_PALETTE

    image = image.scaled(THUMB, THUMB,
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
    image = image.convertToFormat(QImage.Format.Format_ARGB32)

    buckets = {}
    total_weight = 0.0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = QColor(image.pixel(x, y))
            if pixel.alpha() < 24:
                continue
            h, s, v = colorsys.rgb_to_hsv(pixel.redF(), pixel.greenF(), pixel.blueF())
            if v < 0.06:
                continue  # noir pur : il ne dit rien de la pochette
            # Une couleur franche pèse plus qu'un gris de fond.
            weight = 0.25 + s * s * 2.4 + v * 0.35
            key = _bucket(h, s, v)
            entry = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            entry[0] += weight
            entry[1] += pixel.redF() * weight
            entry[2] += pixel.greenF() * weight
            entry[3] += pixel.blueF() * weight
            total_weight += weight

    if not buckets or total_weight <= 0:
        return NEUTRAL_PALETTE

    ranked = sorted(buckets.values(), key=lambda e: e[0], reverse=True)
    colors = [QColor.fromRgbF(e[1] / e[0], e[2] / e[0], e[3] / e[0]) for e in ranked]

    dominant = colors[0]
    dom_hue = dominant.hueF() if dominant.hueF() >= 0 else 0.0

    # L'accent doit trancher : on cherche la première couleur assez éloignée en
    # teinte, sinon on prend la complémentaire de la dominante.
    accent = None
    for color in colors[1:8]:
        hue = color.hueF() if color.hueF() >= 0 else 0.0
        if _hue_distance(hue, dom_hue) > 0.08 and color.saturationF() > 0.18:
            accent = color
            break
    if accent is None:
        accent = QColor.fromHsvF((dom_hue + 0.5) % 1.0,
                                 max(0.35, dominant.saturationF()),
                                 min(1.0, dominant.valueF() + 0.25))

    # Neutre : la couleur la plus terne, utile pour les fonds et bordures.
    neutral = min(colors[:6], key=lambda c: c.saturationF())
    return Palette(dominant, accent, neutral)


def _to_image(source):
    if isinstance(source, QImage):
        return source
    if isinstance(source, QPixmap):
        return None if source.isNull() else source.toImage()
    if isinstance(source, str) and source:
        image = QImage(source)
        return None if image.isNull() else image
    return None


def blend_palettes(a, b, t):
    """Transition douce d'une palette à l'autre (changement de piste)."""
    return Palette(Palette.mix(a.dominant, b.dominant, t),
                   Palette.mix(a.accent, b.accent, t),
                   Palette.mix(a.neutral, b.neutral, t))
