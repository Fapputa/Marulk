"""
Effet Nightcore : accélération + montée du pitch.

L'astuce (confirmée : c'est bien un seul et même traitement) :
un fichier audio n'est qu'une liste d'échantillons + une cadence de lecture.
Si on relit la même liste plus vite, chaque cycle de l'onde se termine plus tôt,
donc TOUTES les fréquences montent exactement du même ratio. Accélérer et
"pitcher up" ne sont pas deux effets à enchaîner : c'est la même opération.

On ne touche donc jamais aux échantillons, on se contente de réécrire le
fichier en déclarant une fréquence d'échantillonnage plus élevée. SDL (pygame)
rééchantillonne ensuite vers la sortie audio, et le tour est joué.

Ratio classique : 1.25 (+3.86 demi-tons), le standard de la scène nightcore.
Au-delà de ~1.35 les voix commencent à baver.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile

# Ratio historique de la scène nightcore (125 % de la vitesse d'origine).
DEFAULT_RATIO = 1.25

# Bornes raisonnables : en dessous on tombe dans le "slowed + reverb",
# au dessus les voix deviennent inécoutables.
MIN_RATIO = 1.0
MAX_RATIO = 1.6

# Budget disque du cache (les WAV rééchantillonnés sont volumineux).
MAX_CACHE_BYTES = 768 * 1024 * 1024

CACHE_DIR = os.path.join(tempfile.gettempdir(), "marulk_nightcore")


def ratio_to_semitones(ratio: float) -> float:
    """Combien de demi-tons ce ratio fait-il monter le morceau."""
    if ratio <= 0:
        return 0.0
    return 12.0 * math.log2(ratio)


def semitones_to_ratio(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


def clamp_ratio(ratio: float) -> float:
    return max(MIN_RATIO, min(MAX_RATIO, float(ratio)))


def is_available() -> bool:
    """Le rendu rapide (soundfile) est-il utilisable ?"""
    try:
        import soundfile  # noqa: F401
        return True
    except Exception:
        return shutil.which("ffmpeg") is not None


def cache_path(src_path: str, ratio: float) -> str:
    """Chemin du fichier nightcore correspondant à (source, ratio)."""
    try:
        stat = os.stat(src_path)
        signature = f"{os.path.abspath(src_path)}|{stat.st_size}|{int(stat.st_mtime)}|{ratio:.4f}"
    except OSError:
        signature = f"{os.path.abspath(src_path)}|{ratio:.4f}"
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    base = os.path.splitext(os.path.basename(src_path))[0][:40]
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip()
    return os.path.join(CACHE_DIR, f"{safe}_{digest}.wav")


def render(src_path: str, ratio: float = DEFAULT_RATIO, force: bool = False) -> str:
    """
    Produit (ou récupère depuis le cache) la version nightcore de `src_path`.
    Retourne le chemin du fichier à donner à pygame.
    """
    ratio = clamp_ratio(ratio)
    if ratio == 1.0:
        return src_path

    os.makedirs(CACHE_DIR, exist_ok=True)
    out_path = cache_path(src_path, ratio)

    if not force and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        os.utime(out_path, None)  # marque comme récemment utilisé
        return out_path

    try:
        _render_soundfile(src_path, out_path, ratio)
    except Exception as exc:
        print(f"⚠️  Nightcore via soundfile impossible ({exc}), bascule sur ffmpeg...")
        _render_ffmpeg(src_path, out_path, ratio)

    prune_cache()
    return out_path


def _render_soundfile(src_path: str, out_path: str, ratio: float) -> None:
    """Voie rapide : on relit les échantillons tels quels, cadence augmentée."""
    import soundfile as sf

    data, sample_rate = sf.read(src_path, dtype="int16")
    tmp = out_path + ".part"
    # Le coeur de l'effet tient dans ce seul `int(sample_rate * ratio)`.
    sf.write(tmp, data, int(round(sample_rate * ratio)),
             format="WAV", subtype="PCM_16")
    os.replace(tmp, out_path)


def _render_ffmpeg(src_path: str, out_path: str, ratio: float) -> None:
    """Repli : même principe, exprimé avec le filtre asetrate de ffmpeg."""
    sample_rate = _probe_sample_rate(src_path) or 44100
    tmp = out_path + ".part"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
        "-af", f"asetrate={int(round(sample_rate * ratio))},aresample={sample_rate}",
        "-c:a", "pcm_s16le", "-f", "wav", tmp,
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, out_path)


def _probe_sample_rate(src_path: str):
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", src_path],
            check=True, capture_output=True, text=True,
        ).stdout
        streams = json.loads(out).get("streams") or []
        if streams:
            return int(streams[0]["sample_rate"])
    except Exception:
        return None
    return None


def cache_size_bytes() -> int:
    if not os.path.isdir(CACHE_DIR):
        return 0
    total = 0
    for name in os.listdir(CACHE_DIR):
        try:
            total += os.path.getsize(os.path.join(CACHE_DIR, name))
        except OSError:
            pass
    return total


def prune_cache(max_bytes: int = MAX_CACHE_BYTES) -> None:
    """Supprime les rendus les plus anciens tant qu'on dépasse le budget."""
    if not os.path.isdir(CACHE_DIR):
        return
    entries = []
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        try:
            entries.append((os.path.getatime(path), os.path.getsize(path), path))
        except OSError:
            pass

    total = sum(size for _, size, _ in entries)
    for _, size, path in sorted(entries):
        if total <= max_bytes:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def clear_cache() -> int:
    """Vide entièrement le cache. Retourne le nombre d'octets libérés."""
    freed = cache_size_bytes()
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    return freed
