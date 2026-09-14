"""
Source unique de vérité pour la configuration et le style.

Avant, `main.py` et `config_ui.py` embarquaient chacun leur propre idée de ce
qui était configurable : plusieurs options réglables dans l'UI (forme "circle",
bordures, opacité, couleur de texte par bouton, échelles d'animation...)
n'étaient tout simplement jamais lues par le lecteur. Tout passe désormais par
ce module, donc une option visible dans la fenêtre de configuration est une
option qui agit vraiment.
"""

import copy
import json
import os

from PyQt6.QtGui import QColor

CONFIG_FILE = "config.json"

# Boutons pilotant la lecture / la fenêtre, dans l'ordre d'affichage.
BUTTON_ORDER = [
    "play", "rewind", "forward", "stop", "shuffle", "loop", "nightcore",
    "mute", "skin", "viz", "playlist", "pin", "colorize",
    "config", "search", "reload", "minimize", "close",
]

# Libellés lisibles pour la fenêtre de configuration.
BUTTON_LABELS = {
    "play": "Lecture / Pause",
    "rewind": "Piste précédente",
    "forward": "Piste suivante",
    "loop": "Boucle",
    "nightcore": "Nightcore",
    "stop": "Arrêt",
    "shuffle": "Lecture aléatoire",
    "mute": "Couper le son",
    "skin": "Changer de support",
    "viz": "Style du visualiseur",
    "playlist": "Afficher la playlist",
    "pin": "Toujours au-dessus",
    "colorize": "Couleurs de la pochette",
    "config": "Configuration",
    "search": "Téléchargeur",
    "reload": "Recharger",
    "minimize": "Réduire",
    "close": "Fermer",
}

# Les boutons sont dessinés par core/icons.py (chemins vectoriels). Ces
# symboles ne servent plus qu'aux libellés texte de la fenêtre de
# configuration, où l'icône est de toute façon affichée à côté.
BUTTON_GLYPHS = {
    "play": "▶",
    "rewind": "⏮",
    "forward": "⏭",
    "stop": "⏹",
    "shuffle": "⤨",
    "loop": "↻",
    "nightcore": "☽",
    "mute": "🔇",
    "skin": "◍",
    "viz": "▁▄█",
    "playlist": "☰",
    "pin": "📌",
    "colorize": "◒",
    "config": "☼",
    "search": "♫",
    "reload": "⤷",
    "minimize": "—",
    "close": "✕",
}

SHAPES = ["rounded", "square", "circle"]


def _button_defaults(color="#613583", text_color="#FFFFFF", size=(30, 30), shape="rounded"):
    return {
        "shape": shape,
        "color": color,
        "text_color": text_color,
        "size": list(size),
        "image_path": "",
        "border_width": 0,
        "border_color": "#000000",
        "opacity": 1.0,
    }


DEFAULT_CONFIG = {
    "window": {
        "width": 270,
        "height": 450,
        "title": "Marulk",
        "background_color": "#9141ac",
        "background_image_path": "",
        "opacity": 1.0,
    },
    "animations": {
        "enabled": True,
        "hover_enabled": True,
        "click_enabled": True,
        # Halo au survol, onde qui part du point cliqué, rotation de l'icône
        # pour les actions qui « tournent », battement des bascules actives.
        "glow_enabled": True,
        "ripple_enabled": True,
        "spin_enabled": True,
        "pulse_enabled": True,
        "glow_strength": 1.0,
        "window_fade_in": True,
        "duration": 150,
        "hover_scale": 1.1,
        "click_scale": 0.95,
    },
    "buttons": {
        "font_family": "Arial",
        "font_path": "",
        "font_size": 12,
        "text_color": "#FFFFFF",
        "play": _button_defaults("#613583", size=(50, 50)),
        "loop": _button_defaults("#613583"),
        "nightcore": _button_defaults("#7b3fa0"),
        "rewind": _button_defaults("#613583", size=(40, 40)),
        "forward": _button_defaults("#613583", size=(40, 40)),
        "stop": _button_defaults("#613583"),
        "shuffle": _button_defaults("#7b3fa0"),
        "mute": _button_defaults("#613583", size=(26, 26)),
        "skin": _button_defaults("#613583", size=(26, 26)),
        "viz": _button_defaults("#613583", size=(26, 26)),
        "playlist": _button_defaults("#613583", size=(26, 26)),
        "pin": _button_defaults("#ffffff", text_color="#000000", size=(26, 26)),
        "colorize": _button_defaults("#ffffff", text_color="#000000", size=(26, 26)),
        "config": _button_defaults("#ffffff", text_color="#000000"),
        "search": _button_defaults("#ffffff", text_color="#000000"),
        "reload": _button_defaults("#ffffff", text_color="#000000"),
        "minimize": _button_defaults("#ffffff", text_color="#000000"),
        "close": _button_defaults("#ff5555"),
    },
    "progress_bar": {
        "color": "#d09dd2",
        "background_color": "#350b4a",
        "height": 10,
        "radius": 10,
        "show_time": True,
        # `animated` = reflet qui balaie la partie déjà lue.
        "animated": True,
        # gradient | glass | neon | segments | flat
        "style": "gradient",
        "glow": True,
        "knob": True,
    },
    "visualizer": {
        "enabled": True,
        "num_bars": 60,
        "color_start": "#ffffff",
        "color_end": "#ffffff",
        "intensity": 5.0,
        "style": "bars",
        "height": 120,
    },
    "volume_bar": {
        "background_color": "#62a0ea",
        "slider_color": "#ffffff",
        "height": 10,
        "slider_shape": "rounded",
        "radius": 5,
        "default_volume": 70,
        "style": "gradient",
        "glow": True,
        "knob": True,
        "animated": False,
    },
    "overlay": {
        "show_on_hover": False,
        "opacity": 0.8,
        "color": "#000000",
    },
    "nightcore": {
        # 1.25 = le ratio historique de la scène nightcore (+3.86 demi-tons).
        "ratio": 1.25,
        "enabled_at_startup": False,
        "auto_render_next": True,
    },
    "media": {
        # none | gif | vinyl | cd | cassette
        "skin": "vinyl",
        "size": 120,
        "spin": True,
        "rpm": 33.3,
        # En nightcore, le disque tourne aussi plus vite : c'est ce que fait
        # réellement la bande.
        "follow_nightcore": True,
        "insert_animation": True,
        "tonearm": True,
        "shine": True,
        "label_ratio": 0.36,
        "body_color": "#141414",
        "accent_color": "#c8a45a",
        # Le support (vinyle, CD, cassette) prend les couleurs de la pochette
        # au lieu du noir/or figé.
        "colorize": True,
        "click_toggles_play": True,
    },
    # Mode « couleurs de la pochette » : le lecteur entier se teint aux
    # couleurs du morceau en cours.
    "colorize": {
        "enabled": False,
        "strength": 0.9,
        "animate": True,
        "background": True,
        "buttons": True,
        "bars": True,
        "visualizer": True,
        "media": True,
    },
    "playlist": {
        "visible": True,
        "height": 80,
        "text_color": "#ffffff",
        "background_opacity": 0.25,
    },
}


def merge_defaults(defaults, loaded):
    """Complète `loaded` avec tout ce qui manque, récursivement."""
    if not isinstance(loaded, dict):
        return copy.deepcopy(defaults)
    result = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_defaults(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path=CONFIG_FILE):
    """Charge la config en garantissant que toutes les clés existent."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return merge_defaults(DEFAULT_CONFIG, json.load(f))
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config, path=CONFIG_FILE):
    """Écriture atomique : jamais de config.json tronqué en cas de crash."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Helpers de style
# --------------------------------------------------------------------------

def rgba(color, opacity=1.0):
    """'#rrggbb' + opacité -> chaîne rgba() utilisable en Qt StyleSheet."""
    c = QColor(color)
    if not c.isValid():
        c = QColor("#000000")
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {max(0.0, min(1.0, float(opacity))):.3f})"


def readable_text_on(color):
    """Noir ou blanc, selon ce qui reste lisible sur `color`."""
    c = QColor(color)
    if not c.isValid():
        return "#ffffff"
    luminance = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


# Les boutons et les barres sont désormais peints par core/widgets.py : leur
# style ne passe plus par une feuille de style Qt (un QSS ne sait ni faire un
# halo, ni une onde de clic). Ne restent ici que les helpers de couleur et le
# QSS de la playlist, qui est un vrai QListWidget.

def playlist_qss(cfg, progress_cfg):
    selected = progress_cfg.get("background_color", "#350b4a")
    text_color = cfg.get("text_color", "#ffffff")
    return f"""
        QListWidget {{
            background: {rgba('#000000', cfg.get('background_opacity', 0.25))};
            color: {text_color};
            border: none;
            border-radius: 6px;
            outline: none;
        }}
        QListWidget::item {{ padding: 2px 4px; }}
        QListWidget::item:hover {{ background: {rgba(selected, 0.5)}; }}
        QListWidget::item:selected, QListWidget::item:selected:!active {{
            background: {selected};
            color: {readable_text_on(selected)};
            border-radius: 4px;
        }}
        QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
        QScrollBar::handle:vertical {{
            background: {rgba(selected, 0.8)}; border-radius: 3px; min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """


# --------------------------------------------------------------------------
# Mode « couleurs de la pochette »
# --------------------------------------------------------------------------

# Rôle visuel de chaque bouton : les commandes de lecture ressortent, les
# utilitaires de la barre de titre restent discrets.
PRIMARY_BUTTONS = {"play", "rewind", "forward", "stop", "shuffle", "loop", "nightcore"}
DANGER_BUTTONS = {"close"}


def derive_from_palette(config, pal, strength=None):
    """
    Renvoie une copie de `config` repeinte aux couleurs de `pal`.

    Seules les couleurs changent : tailles, formes, polices, options de
    comportement restent celles choisies par l'utilisateur. Le lecteur peut donc
    passer en couleurs automatiques et revenir à son thème sans rien perdre.
    """
    cfg = copy.deepcopy(config)
    section = cfg.get("colorize", {})
    if strength is None:
        strength = float(section.get("strength", 0.9))
    strength = max(0.0, min(1.0, strength))

    background = pal.background(strength)
    surface = pal.surface(strength)
    primary = pal.primary(strength)
    highlight = pal.highlight(strength)
    soft = pal.soft(strength)

    if section.get("background", True):
        cfg["window"]["background_color"] = background.name()

    if section.get("buttons", True):
        buttons = cfg.setdefault("buttons", {})
        for name in BUTTON_ORDER:
            one = buttons.get(name)
            if not isinstance(one, dict):
                continue
            if name in DANGER_BUTTONS:
                # Le bouton « fermer » doit rester identifiable : on le teinte
                # sans lui retirer son rouge.
                color = pal.mix(QColor("#e05555"), primary, 0.35 * strength)
            elif name in PRIMARY_BUTTONS:
                color = primary
            else:
                color = surface
            one["color"] = color.name()
            one["text_color"] = readable_text_on(color.name())
        buttons["text_color"] = readable_text_on(surface.name())

    if section.get("bars", True):
        cfg["progress_bar"]["color"] = highlight.name()
        cfg["progress_bar"]["background_color"] = surface.darker(120).name()
        cfg["volume_bar"]["slider_color"] = highlight.name()
        cfg["volume_bar"]["background_color"] = surface.name()

    if section.get("visualizer", True):
        cfg["visualizer"]["color_start"] = primary.name()
        cfg["visualizer"]["color_end"] = soft.name()

    if section.get("media", True):
        cfg["media"]["body_color"] = pal.tone(pal.dominant, 0.45, 0.20).name()
        cfg["media"]["accent_color"] = highlight.name()

    cfg["playlist"]["text_color"] = readable_text_on(background.name())
    return cfg
