from math import hypot

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage

from .base import LayerMedia
from .noise import NoiseField


class AnimationMedia(LayerMedia):
    def __init__(self, width: int = 160, height: int = 90, parent=None):
        super().__init__(parent)
        self.width = max(16, int(width))
        self.height = max(16, int(height))
        self.speed = 0.08
        self.noise_scale = 0.012
        self.direction = (1.0, 0.0)
        self.color_a = QColor("#101820")
        self.color_b = QColor("#d7e4e8")
        self.transparent_b = False
        self._phase = 0.0
        self._image = QImage()
        self._pixels = np.empty((self.height, self.width, 4), dtype=np.uint8)
        self._noise_field = NoiseField(self.width, self.height, self.noise_scale)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self._render()
        self._timer.start()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    def copy(self) -> "AnimationMedia":
        copied = AnimationMedia(self.width, self.height)
        copied.speed = self.speed
        copied.noise_scale = self.noise_scale
        copied.direction = tuple(self.direction)
        copied.color_a = QColor(self.color_a)
        copied.color_b = QColor(self.color_b)
        copied.transparent_b = self.transparent_b
        copied._phase = self._phase
        copied._rebuild_noise_field()
        copied._render()
        return copied

    def set_parameters(self, color_a, color_b, transparent_b, speed, noise_scale, direction=(1.0, 0.0)):
        self.color_a = QColor(color_a)
        self.color_b = QColor(color_b)
        self.transparent_b = transparent_b
        self.speed = max(0.0, min(1.0, float(speed)))
        self.noise_scale = max(0.003, min(0.08, float(noise_scale)))
        self.direction = (float(direction[0]), float(direction[1]))
        self._rebuild_noise_field()
        self._render()
        self.frame_changed.emit()

    def normalize_direction(self):
        length = hypot(*self.direction)
        self.direction = (
            (self.direction[0] / length, self.direction[1] / length)
            if length > 0.0 else (1.0, 0.0)
        )
        self._render()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        self._phase += self.speed
        self._render()
        self.frame_changed.emit()

    def _rebuild_noise_field(self):
        self._noise_field = NoiseField(self.width, self.height, self.noise_scale)

    def _render(self):
        noise = self._noise_field.render(self._phase, self.direction)
        first = np.array(self.color_a.getRgb()[:3], dtype=np.float32)
        second = np.array(self.color_b.getRgb()[:3], dtype=np.float32)
        if self.transparent_b:
            self._pixels[:, :, :3] = first.astype(np.uint8)
            self._pixels[:, :, 3] = ((1.0 - noise) * 255).astype(np.uint8)
        else:
            self._pixels[:, :, :3] = (first + (second - first) * noise[:, :, None]).astype(np.uint8)
            self._pixels[:, :, 3] = 255
        self._image = QImage(
            self._pixels.data,
            self.width,
            self.height,
            self.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()

    def frame_array(self):
        return self._pixels
