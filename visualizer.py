import numpy as np
import librosa
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QLinearGradient, QPolygonF


def compute_spectrogram(file_path, nb_bandes=60, sample_rate=22050, hop_length=512):
    """
    Analyse un fichier audio et renvoie un spectrogramme normalisé (0..1).

    Fonction pure et sans Qt : elle peut donc tourner dans un thread de fond,
    ce qui évite de figer l'interface à chaque changement de piste.
    """
    y, sr = librosa.load(file_path, sr=sample_rate, mono=True)
    stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop_length))
    mel_basis = librosa.filters.mel(sr=sr, n_fft=2048, n_mels=nb_bandes)
    spectrogramme = np.dot(mel_basis, stft)
    spectrogramme = librosa.amplitude_to_db(spectrogramme, ref=np.max)
    return np.clip((spectrogramme + 80) / 80, 0.0, 1.0)


class AudioVisualizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        # Valeurs par défaut
        self.nb_bandes = 60
        self.color_start = QColor("#ffffff")
        self.color_end = QColor("#ffffff")
        self.intensity = 5.0
        self.style = "bars"
        self.enabled = True

        self.spectrogramme = None
        self.sample_rate = 22050
        self.hop_length = 512
        self.current_frame = 0
        # Lissage : évite le clignotement des barres d'une frame à l'autre.
        self._smoothed = None
        self._smoothing = 0.35

    def configure(self, config):
        """Récupère les paramètres dynamiques depuis le JSON"""
        viz_config = config.get("visualizer", {})

        self.enabled = viz_config.get("enabled", True)
        self.nb_bandes = max(1, int(viz_config.get("num_bars", 60)))
        self.color_start = QColor(viz_config.get("color_start", "#ffffff"))
        self.color_end = QColor(viz_config.get("color_end", "#ffffff"))
        self.intensity = float(viz_config.get("intensity", 5.0))
        self.style = viz_config.get("style", "bars")

        self.setFixedHeight(max(20, int(viz_config.get("height", 120))))
        self.setVisible(self.enabled)
        self._smoothed = None
        self.update()

    def apply_colors(self, color_start, color_end):
        """Recolorisation seule : utilisée par le mode couleurs de la pochette."""
        self.color_start = QColor(color_start)
        self.color_end = QColor(color_end)
        self.update()

    def load_audio(self, file_path):
        """Analyse synchrone (conservée pour compatibilité)."""
        try:
            self.set_spectrogram(compute_spectrogram(
                file_path, self.nb_bandes, self.sample_rate, self.hop_length))
        except Exception as e:
            print(f"Erreur Equalizer : {e}")
            self.set_spectrogram(None)

    def set_spectrogram(self, spectrogramme):
        """Installe un spectrogramme déjà calculé (éventuellement hors thread UI)."""
        self.spectrogramme = spectrogramme
        self._smoothed = None
        self.current_frame = 0
        self.update()

    def update_visualizer(self, ms):
        if self.spectrogramme is not None and self.enabled:
            secondes = ms / 1000
            self.current_frame = int((secondes * self.sample_rate) / self.hop_length)
            self.update()

    def _current_levels(self):
        """Niveaux lissés de la frame courante, ou None."""
        if self.spectrogramme is None or not self.enabled:
            return None
        if not (0 <= self.current_frame < self.spectrogramme.shape[1]):
            return None
        levels = self.spectrogramme[:, self.current_frame]
        if self._smoothed is None or self._smoothed.shape != levels.shape:
            self._smoothed = levels.copy()
        else:
            a = self._smoothing
            self._smoothed = self._smoothed * (1 - a) + levels * a
        return self._smoothed

    def _gradient(self, x1, y1, x2, y2):
        gradient = QLinearGradient(x1, y1, x2, y2)
        gradient.setColorAt(0, self.color_start)
        gradient.setColorAt(1, self.color_end)
        return gradient

    def paintEvent(self, event):
        if not self.enabled:
            return
        levels = self._current_levels()
        if levels is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        scale = self.intensity / 5.0

        if self.style == "wave":
            self._paint_wave(painter, levels, w, h, scale)
        elif self.style == "circle":
            self._paint_circle(painter, levels, w, h, scale)
        else:
            self._paint_bars(painter, levels, w, h, scale)

    def _paint_bars(self, painter, levels, w, h, scale):
        bar_w = w / len(levels)
        painter.setPen(Qt.PenStyle.NoPen)
        for i, amp in enumerate(levels):
            bar_h = max(2.0, min(float(amp) * h * scale, h))
            painter.setBrush(QBrush(self._gradient(0, h, 0, h - bar_h)))
            radius = min(5, bar_w / 2)
            painter.drawRoundedRect(
                int(i * bar_w + 1), int(h - bar_h),
                max(1, int(bar_w - 2)), int(bar_h), radius, radius)

    def _paint_wave(self, painter, levels, w, h, scale):
        """Courbe pleine : une ligne d'horizon qui ondule avec le spectre."""
        step = w / max(1, len(levels) - 1)
        points = [QPointF(0.0, float(h))]
        for i, amp in enumerate(levels):
            y = h - max(2.0, min(float(amp) * h * scale, h))
            points.append(QPointF(i * step, y))
        points.append(QPointF(float(w), float(h)))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._gradient(0, h, 0, 0)))
        painter.drawPolygon(QPolygonF(points))

        pen = QPen(self.color_end, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points[1:-1]))

    def _paint_circle(self, painter, levels, w, h, scale):
        """Barres rayonnant depuis le centre."""
        import math
        cx, cy = w / 2, h / 2
        base = min(w, h) / 4
        painter.setBrush(Qt.BrushStyle.NoBrush)
        n = len(levels)
        for i, amp in enumerate(levels):
            angle = (i / n) * 2 * math.pi - math.pi / 2
            length = max(2.0, float(amp) * base * scale)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            ratio = i / max(1, n - 1)
            color = QColor(
                int(self.color_start.red() * (1 - ratio) + self.color_end.red() * ratio),
                int(self.color_start.green() * (1 - ratio) + self.color_end.green() * ratio),
                int(self.color_start.blue() * (1 - ratio) + self.color_end.blue() * ratio),
            )
            painter.setPen(QPen(color, max(1, int(min(w, h) / (n * 1.5))), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(cx + cos_a * base, cy + sin_a * base),
                QPointF(cx + cos_a * (base + length), cy + sin_a * (base + length)))
