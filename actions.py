import os
import time
import pygame
from mutagen.mp3 import MP3

pygame.mixer.init()
playlist = []
current_index = -1

# --- Substitutions de lecture (nightcore) --------------------------------
# `playlist` garde toujours les fichiers d'origine. Quand un effet est actif,
# on enregistre ici le fichier réellement envoyé à pygame pour un index donné :
#     index -> (chemin_du_rendu, ratio_de_vitesse)
# Tant qu'aucune substitution n'est enregistrée pour la piste courante, tout se
# comporte exactement comme avant (ratio 1.0).
_substitutes = {}

# Temps en ms où la lecture a été mise en pause (ou position de départ)
last_seek_position = 0

# Timestamp (en secondes) du moment où la musique a été lancée/reprise
play_start_time = None

def load_playlist_from_folder(folder_path):
    global playlist, current_index
    playlist.clear()
    current_index = -1
    for filename in os.listdir(folder_path):
        if filename.lower().endswith(('.mp3', '.wav', '.ogg')):
            playlist.append(os.path.join(folder_path, filename))

def register_substitute(index, path, rate):
    """Associe un rendu (nightcore) à une piste de la playlist."""
    if 0 <= index < len(playlist):
        _substitutes[index] = (path, float(rate))


def clear_substitutes():
    """Repasse toute la playlist en lecture normale."""
    _substitutes.clear()


def active_rate(index=None):
    """Ratio de vitesse réellement appliqué (1.0 = lecture normale)."""
    idx = current_index if index is None else index
    entry = _substitutes.get(idx)
    return entry[1] if entry else 1.0


def get_playback_path(index=None):
    """Fichier réellement lu : le rendu nightcore s'il existe, sinon l'original."""
    idx = current_index if index is None else index
    if not (0 <= idx < len(playlist)):
        return None
    entry = _substitutes.get(idx)
    if entry and os.path.isfile(entry[0]):
        return entry[0]
    return playlist[idx]


def get_current_index():
    global current_index
    return current_index

def set_current_index(index):
    global current_index, last_seek_position, play_start_time
    if 0 <= index < len(playlist):
        current_index = index
        last_seek_position = 0
        play_start_time = None

def load_track_by_index(index):
    global current_index, last_seek_position, play_start_time
    if 0 <= index < len(playlist):
        current_index = index
        last_seek_position = 0
        play_start_time = None
        pygame.mixer.music.load(get_playback_path(index))

def play_music():
    global play_start_time
    if current_index == -1 and len(playlist) > 0:
        load_track_by_index(0)
    pygame.mixer.music.play(start=last_seek_position / 1000)
    play_start_time = time.time()

def pause_music():
    global last_seek_position, play_start_time
    if play_start_time is not None:
        elapsed_ms = int((time.time() - play_start_time) * 1000)
        last_seek_position += elapsed_ms
        play_start_time = None
    pygame.mixer.music.pause()

def loop_music():
    global play_start_time
    if current_index == -1 and len(playlist) > 0:
        load_track_by_index(0)
    pygame.mixer.music.play(loops=-1, start=last_seek_position / 1000)
    play_start_time = time.time()

def stop_music():
    global last_seek_position, play_start_time
    pygame.mixer.music.stop()
    last_seek_position = 0
    play_start_time = None

def skip_track():
    global current_index
    if not playlist:
        return
    new_index = (current_index + 1) % len(playlist)
    set_current_index(new_index)
    load_track_by_index(new_index)
    play_music()

def rewind_track():
    global last_seek_position, play_start_time
    last_seek_position = 0
    play_start_time = time.time()
    pygame.mixer.music.play(start=0)

def set_volume(vol):
    pygame.mixer.music.set_volume(vol)

def get_current_position_ms():
    global last_seek_position, play_start_time
    if play_start_time is None:
        return last_seek_position
    elapsed_ms = int((time.time() - play_start_time) * 1000)
    return last_seek_position + elapsed_ms

def get_current_track_duration_ms():
    if current_index == -1 or not playlist:
        return 0
    try:
        audio = MP3(playlist[current_index])
        # En nightcore le morceau est joué plus vite : sa durée est divisée
        # par le ratio, comme la timeline du fichier rendu.
        return int((audio.info.length * 1000) / active_rate())
    except Exception:
        return 0

def seek_to_position(ms):
    global last_seek_position, play_start_time
    if current_index == -1:
        return
    last_seek_position = ms
    play_start_time = time.time()
    pygame.mixer.music.load(get_playback_path(current_index))
    pygame.mixer.music.play(start=ms / 1000)

def get_current_track_name():
    if 0 <= current_index < len(playlist):
        return os.path.basename(playlist[current_index])
    return ""
