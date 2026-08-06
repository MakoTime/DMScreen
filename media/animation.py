from math import hypot

import numpy as np
from PySide6.QtCore import QElapsedTimer, QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage

from .base import LayerMedia
from .gpu_animation import GpuAnimationRenderer
from .noise import NoiseField
from performance import PerformanceChecker


class AnimationWorker(QObject):
    frame_ready = Signal(QImage)
    phase_ready = Signal(float)
    stopped = Signal()

    def __init__(self, width, height, performance):
        super().__init__()
        self.width = width
        self.height = height
        self.render_scale = min(1.0, AnimationMedia.MAX_RENDER_WIDTH / width)
        self.render_width = max(16, round(width * self.render_scale))
        self.render_height = max(16, round(height * self.render_scale))
        self.speed = 0.08
        self.noise_scale = 0.012
        self.direction = (1.0, 0.0)
        self.color_a = (16, 24, 32)
        self.color_b = (215, 228, 232)
        self.transparent_b = False
        self.performance = performance
        self.phase = 0.0
        self._timer = None
        self._elapsed_timer = QElapsedTimer()
        self._pixels = None
        self._noise_field = None
        self._gpu = GpuAnimationRenderer(width, height, self.render_scale)

    @Slot()
    def start(self):
        self._pixels = np.empty(
            (self.render_height, self.render_width, 4), dtype=np.uint8
        )
        self._gpu.initialize()
        self._rebuild_noise_field()
        self._render()
        self._elapsed_timer.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.advance)
        self._timer.start()

    @Slot()
    def advance(self):
        with self.performance.measure("media.animation.advance"):
            elapsed_ms = max(0, self._elapsed_timer.restart())
            self.phase += self.speed * elapsed_ms / 33.0
            self._render()

    @Slot()
    def render(self):
        self._render()

    @Slot(object, object, bool, float, float, object)
    def set_parameters(
        self,
        color_a,
        color_b,
        transparent_b,
        speed,
        noise_scale,
        direction,
    ):
        self.color_a = tuple(color_a)
        self.color_b = tuple(color_b)
        self.transparent_b = transparent_b
        self.speed = speed
        self.noise_scale = noise_scale
        self.direction = tuple(direction)
        self._rebuild_noise_field()
        self._render()

    @Slot()
    def stop(self):
        if self._timer is not None:
            self._timer.stop()
        self._gpu.close()
        self.stopped.emit()

    @Slot()
    def pause(self):
        if self._timer is not None:
            self._timer.stop()

    @Slot()
    def resume(self):
        if self._timer is not None:
            self._timer.start()

    def _rebuild_noise_field(self):
        self._noise_field = NoiseField(
            self.render_width,
            self.render_height,
            self.noise_scale / self.render_scale,
        )

    def _render(self):
        with self.performance.measure("media.animation.render"):
            gpu_image = self._gpu.render(
                self.phase,
                self.noise_scale,
                self.direction,
                self.color_a,
                self.color_b,
                self.transparent_b,
            )
            if gpu_image is not None:
                self.phase_ready.emit(self.phase)
                self.frame_ready.emit(gpu_image)
                return
            noise = self._noise_field.render(self.phase, self.direction)
            first = np.asarray(self.color_a, dtype=np.float32)
            second = np.asarray(self.color_b, dtype=np.float32)
            if self.transparent_b:
                self._pixels[:, :, :3] = first.astype(np.uint8)
                self._pixels[:, :, 3] = ((1.0 - noise) * 255).astype(np.uint8)
            else:
                self._pixels[:, :, :3] = (
                    first + (second - first) * noise[:, :, None]
                ).astype(np.uint8)
                self._pixels[:, :, 3] = 255
            image = QImage(
                self._pixels.data,
                self.render_width,
                self.render_height,
                self.render_width * 4,
                QImage.Format.Format_RGBA8888,
            ).copy()
            if self.render_scale < 1.0:
                image = image.scaled(
                    self.width,
                    self.height,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            self.phase_ready.emit(self.phase)
            self.frame_ready.emit(image)


class AnimationMedia(LayerMedia):
    MAX_RENDER_WIDTH = 640
    advance_requested = Signal()
    render_requested = Signal()
    parameters_requested = Signal(object, object, bool, float, float, object)
    stop_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()

    def __init__(self, width: int = 160, height: int = 90, parent=None):
        super().__init__(parent)
        self.width = max(16, int(width))
        self.height = max(16, int(height))
        self._render_scale = min(1.0, self.MAX_RENDER_WIDTH / self.width)
        self._render_width = max(16, round(self.width * self._render_scale))
        self._render_height = max(16, round(self.height * self._render_scale))
        self.speed = 0.08
        self.noise_scale = 0.012
        self.direction = (1.0, 0.0)
        self.color_a = QColor("#101820")
        self.color_b = QColor("#d7e4e8")
        self.transparent_b = False
        self.performance = PerformanceChecker()
        self._phase = 0.0
        self._image = QImage()
        self._pixels = np.empty((self.height, self.width, 4), dtype=np.uint8)
        self._thumbnail_image = QImage(
            self.width,
            self.height,
            QImage.Format.Format_RGBA8888,
        )
        self._thumbnail_image.fill(self.color_a)
        self._image = QImage(self._thumbnail_image)
        self._thread = QThread(self)
        self._worker = AnimationWorker(self.width, self.height, self.performance)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self.advance_requested.connect(self._worker.advance)
        self.render_requested.connect(self._worker.render)
        self.parameters_requested.connect(self._worker.set_parameters)
        self.stop_requested.connect(self._worker.stop)
        self.pause_requested.connect(self._worker.pause)
        self.resume_requested.connect(self._worker.resume)
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.phase_ready.connect(self._on_phase_ready)
        self._worker.stopped.connect(
            self._thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    def gpu_render_data(self):
        return {
            "phase": self._phase,
            "noise_scale": self.noise_scale / self._render_scale,
            "direction": self.direction,
            "color_a": tuple(channel / 255.0 for channel in self.color_a.getRgb()[:3]),
            "color_b": tuple(channel / 255.0 for channel in self.color_b.getRgb()[:3]),
            "transparent_b": self.transparent_b,
            "width": self.width,
            "height": self.height,
        }

    def thumbnail_frame(self) -> QImage:
        return self._thumbnail_image

    def copy(self) -> "AnimationMedia":
        copied = AnimationMedia(self.width, self.height)
        copied.speed = self.speed
        copied.noise_scale = self.noise_scale
        copied.direction = tuple(self.direction)
        copied.color_a = QColor(self.color_a)
        copied.color_b = QColor(self.color_b)
        copied.transparent_b = self.transparent_b
        copied._phase = self._phase
        copied.parameters_requested.emit(
            copied.color_a.getRgb()[:3],
            copied.color_b.getRgb()[:3],
            copied.transparent_b,
            copied.speed,
            copied.noise_scale,
            copied.direction,
        )
        return copied

    def set_parameters(self, color_a, color_b, transparent_b, speed, noise_scale, direction=(1.0, 0.0)):
        self.color_a = QColor(color_a)
        self.color_b = QColor(color_b)
        self.transparent_b = transparent_b
        self.speed = max(0.0, min(1.0, float(speed)))
        self.noise_scale = max(0.003, min(0.08, float(noise_scale)))
        self.direction = (float(direction[0]), float(direction[1]))
        self.parameters_requested.emit(
            self.color_a.getRgb()[:3],
            self.color_b.getRgb()[:3],
            self.transparent_b,
            self.speed,
            self.noise_scale,
            self.direction,
        )

    def normalize_direction(self):
        length = hypot(*self.direction)
        self.direction = (
            (self.direction[0] / length, self.direction[1] / length)
            if length > 0.0 else (1.0, 0.0)
        )
        self.parameters_requested.emit(
            self.color_a.getRgb()[:3],
            self.color_b.getRgb()[:3],
            self.transparent_b,
            self.speed,
            self.noise_scale,
            self.direction,
        )

    def stop(self):
        if self._thread.isRunning():
            self.stop_requested.emit()
            self._thread.wait(1000)

    def pause(self):
        if self._thread.isRunning():
            self.pause_requested.emit()

    def resume(self):
        if self._thread.isRunning():
            self.resume_requested.emit()

    def _advance(self):
        with self.performance.measure("media.animation.advance"):
            self.advance_requested.emit()
        self.performance.record("media.animation.render", 0.0)

    def _render(self):
        self.render_requested.emit()

    @Slot(QImage)
    def _on_frame_ready(self, image):
        self._image = QImage(image)
        output = np.frombuffer(
            self._image.constBits(), dtype=np.uint8
        ).reshape(self.height, self._image.bytesPerLine() // 4, 4)
        self._pixels[:] = output[:, :self.width]
        if self._thumbnail_image.isNull():
            self._thumbnail_image = QImage(self._image)
        self.frame_changed.emit()

    @Slot(float)
    def _on_phase_ready(self, phase):
        self._phase = phase

    def frame_array(self):
        return self._pixels
