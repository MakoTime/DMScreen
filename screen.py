from threading import Lock
from time import perf_counter

import numpy as np

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
)
from PySide6.QtCore import QObject, QPoint, QRect, QSize, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QPen
from layer_manager import Layer, LayerManager
from layer_media import AnimationMedia, MaskMedia
from mouse_action import MouseActionMenu, MouseActionState
from performance import PerformanceChecker
from render_models import RenderState
from media.gpu_composition import GpuCompositionRenderer


class RenderEngine(QObject):
    """Latest-frame render coordinator and background render executor."""

    work_requested = Signal()
    rendered = Signal(int, QImage)

    def __init__(
        self,
        frame_size: QSize,
        background_color=QColor("black"),
        performance: PerformanceChecker | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.frame_size = QSize(frame_size)
        self.background_color = QColor(background_color)
        self.performance = performance or PerformanceChecker()
        self.frame = Frame(
            *self.frame_size.toTuple(),
            output_scale=0.5,
            background_color=self.background_color,
            performance=self.performance,
        )
        self._lock = Lock()
        self._pending: dict[str, RenderState] = {}
        self._pending_request_id = 0
        self._has_pending = False
        self._latest: tuple[int, QImage] | None = None
        self._generation = 0
        self._scheduled = False
        self._processing = False
        self._stopped = False
        self._gpu_compositor = GpuCompositionRenderer()
        self.work_requested.connect(self.process)

    def submit(self, request_id: int, states: list[RenderState]):
        """Replace each layer task and remove tasks for deleted layers."""
        tasks = {
            state.layer_id or f"index:{index}": state
            for index, state in enumerate(states)
        }
        with self._lock:
            if self._stopped:
                return
            self._pending = tasks
            self._pending_request_id = request_id
            self._has_pending = True
            self._generation += 1
            self._latest = None
            if self._scheduled or self._processing:
                return
            self._scheduled = True
        self.work_requested.emit()

    def cancel_layer(self, layer_id: str):
        """Remove a layer task before it can be included in a render."""
        with self._lock:
            self._pending.pop(layer_id, None)
            self._generation += 1

    def result(self) -> tuple[int, QImage] | None:
        """Return the most recently completed render result, if available."""
        with self._lock:
            if self._latest is None:
                return None
            request_id, canvas = self._latest
            return request_id, QImage(canvas)

    def stop(self):
        with self._lock:
            self._stopped = True
            self._pending.clear()
            self._has_pending = False
            self._generation += 1

    @Slot()
    def process(self):
        with self._lock:
            states = list(self._pending.values())
            request_id = self._pending_request_id
            generation = self._generation
            self._pending.clear()
            has_pending = self._has_pending
            self._has_pending = False
            self._scheduled = False
            if has_pending:
                self._processing = True
            stopped = self._stopped
        if stopped or not has_pending:
            return

        self.frame.set_size(*self.frame_size.toTuple())
        self.frame.set_background_color(self.background_color)
        with self.performance.measure("worker.render_frame"):
            canvas = None
            if all(state.mask_image is None for state in states):
                if not self._gpu_compositor.available:
                    self._gpu_compositor.initialize()
                if self._gpu_compositor.available:
                    output_size = QSize(
                        max(1, round(self.frame_size.width() * self.frame.output_scale)),
                        max(1, round(self.frame_size.height() * self.frame.output_scale)),
                    )
                    canvas = self._gpu_compositor.render(
                        states,
                        output_size,
                        self.background_color,
                        self.frame.output_scale,
                    )
            if canvas is None:
                canvas = self.frame.render_states(states)
        with self._lock:
            is_current = not self._stopped and generation == self._generation
            if is_current:
                self._latest = (request_id, QImage(canvas))
            self._processing = False
            schedule_follow_up = bool(self._has_pending) and not self._scheduled
            if schedule_follow_up:
                self._scheduled = True
        if is_current:
            self.rendered.emit(request_id, canvas)
        if schedule_follow_up:
            self.work_requested.emit()


RenderWorker = RenderEngine


class Frame:
    """Fixed drawing surface that clips every layer to its own bounds."""

    def __init__(
        self,
        width: int = 0,
        height: int = 0,
        output_scale: float = 1.0,
        background_color: QColor | None = None,
        performance: PerformanceChecker | None = None,
    ):
        self._size = QSize(max(0, width), max(0, height))
        self.output_scale = max(0.01, min(1.0, output_scale))
        self.background_color = QColor(background_color or "black")
        self.performance = performance or PerformanceChecker()
        self._inverse_masks = {}
        self.layer_timings: dict[str, float] = {}

    @property
    def size(self) -> QSize:
        return QSize(self._size)

    def set_size(self, width: int, height: int):
        self._size = QSize(max(0, width), max(0, height))

    def set_background_color(self, color: QColor):
        self.background_color = QColor(color)

    def draw(
        self,
        layers: list[Layer],
        mask_sources: list[Layer] | None = None,
    ) -> QImage:
        """Render layers at their offsets, clipping them to the frame."""
        mask_layers = {
            layer.layer_id: layer
            for layer in [*(mask_sources or []), *layers]
            if isinstance(layer.media, MaskMedia)
        }
        states = [
            self._state_from_layer(layer, mask_layers)
            for layer in reversed(layers)
        ]
        states = [state for state in states if state is not None]
        return self.render_states(states)

    def render_states(self, states: list[RenderState]) -> QImage:
        """Render detached image snapshots without accessing Qt media objects."""
        drawable_states = [state for state in states if not state.image.isNull()]
        if self._size.isEmpty() and drawable_states:
            first_image = drawable_states[0].image
            self.set_size(first_image.width(), first_image.height())

        if self._size.isEmpty():
            return QImage()

        output_size = QSize(
            max(1, round(self._size.width() * self.output_scale)),
            max(1, round(self._size.height() * self.output_scale)),
        )
        canvas = QImage(output_size, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(self.background_color)

        painter = QPainter(canvas)
        painter.setClipRect(QRect(QPoint(0, 0), output_size))
        self.layer_timings = {}
        for state in drawable_states:
            started = perf_counter()
            image = state.image
            scale_x, scale_y = state.scale
            image_array = state.image_array
            mask_array = state.mask_array
            if (
                image_array is None
                and state.mask_image is not None
                and state.mask_image.size() == image.size()
            ):
                image_array = self._rgba_pixels(image)
                mask_array = self._rgba_pixels(state.mask_image)[:, :, 3] > 0
            fast_mask = (
                image_array is not None
                and mask_array is not None
                and image_array.shape[:2] == mask_array.shape
                and scale_x == 1.0
                and scale_y == 1.0
                and state.offset.isNull()
            )
            if fast_mask:
                pixels = image_array.copy()
                pixels[mask_array, 3] = 0
                image = QImage(
                    pixels.data,
                    pixels.shape[1],
                    pixels.shape[0],
                    pixels.strides[0],
                    QImage.Format.Format_RGBA8888,
                ).copy()
                scale_x = self.output_scale
                scale_y = self.output_scale
                offset = QPoint()
            else:
                if state.render_scale < 1.0:
                    image, scale_x, scale_y = self._reduce_for_processing(
                        image,
                        scale_x,
                        scale_y,
                        state.render_scale,
                    )
                if state.mask_image is not None:
                    image = self._mask_image(
                        image,
                        state.mask_image,
                        QPoint(
                            round(state.offset.x() * self.output_scale),
                            round(state.offset.y() * self.output_scale),
                        ),
                        (scale_x * self.output_scale, scale_y * self.output_scale),
                        output_size,
                        self._inverse_masks,
                    )
                    scale_x = 1.0
                    scale_y = 1.0
                else:
                    scale_x *= self.output_scale
                    scale_y *= self.output_scale
                offset = QPoint(
                    round(state.offset.x() * self.output_scale),
                    round(state.offset.y() * self.output_scale),
                )
            scaled_size = QSize(
                max(1, round(image.width() * scale_x)),
                max(1, round(image.height() * scale_y)),
            )
            painter.setOpacity(max(0.0, min(1.0, state.alpha)))
            painter.drawImage(
                QRect(offset, scaled_size),
                image,
            )
            layer_name = state.layer_name or "Unnamed layer"
            duration_ms = (perf_counter() - started) * 1000.0
            self.layer_timings[layer_name] = (
                self.layer_timings.get(layer_name, 0.0) + duration_ms
            )
            self.performance.record(f"worker.layer.{layer_name}", duration_ms)
        painter.end()
        return canvas

    @staticmethod
    def _rgba_pixels(image: QImage) -> np.ndarray:
        rgba_image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(
            rgba_image.constBits(),
            dtype=np.uint8,
            count=rgba_image.bytesPerLine() * rgba_image.height(),
        ).copy().reshape(
            (rgba_image.height(), rgba_image.bytesPerLine() // 4, 4)
        )[:, : rgba_image.width()]

    @staticmethod
    def _state_from_layer(
        layer: Layer,
        mask_layers: dict[str, Layer] | None = None,
    ) -> RenderState | None:
        if layer.media is None or layer.media.is_empty():
            return None
        image = QImage(layer.media.current_frame())
        mask_image = None
        mask_array = None
        image_array = None
        if mask_layers is not None and layer.mask_layer_id is not None:
            mask_layer = mask_layers.get(layer.mask_layer_id)
            if mask_layer is not None and isinstance(mask_layer.media, MaskMedia):
                mask_image = QImage(mask_layer.media.current_frame())
        return RenderState(
            image=image,
            offset=QPoint(layer.offset),
            scale=tuple(layer.scale),
            alpha=layer.alpha,
            render_scale=layer.media.render_scale,
            mask_image=mask_image,
            image_array=image_array,
            mask_array=mask_array,
            layer_name=layer.name,
            layer_id=layer.layer_id,
            animation=(
                layer.media.gpu_render_data()
                if isinstance(layer.media, AnimationMedia)
                else None
            ),
        )

    def _mask_image(
        self,
        image,
        mask_image,
        offset,
        scale,
        output_size,
        inverse_masks,
    ):
        target_size = QSize(
            max(1, round(image.width() * scale[0])),
            max(1, round(image.height() * scale[1])),
        )
        masked = QImage(target_size, QImage.Format.Format_ARGB32_Premultiplied)
        masked.fill(Qt.GlobalColor.transparent)
        painter = QPainter(masked)
        painter.drawImage(QRect(QPoint(), target_size), image)
        painter.end()

        cache_key = (mask_image.cacheKey(), output_size.width(), output_size.height())
        inverse_frame_mask = inverse_masks.get(cache_key)
        if inverse_frame_mask is None:
            if len(inverse_masks) >= 8:
                inverse_masks.clear()
            inverse_frame_mask = self._inverse_mask(mask_image, output_size)
            inverse_masks[cache_key] = inverse_frame_mask

        frame_rect = QRect(offset, target_size)
        inverse_mask = QImage(target_size, QImage.Format.Format_ARGB32_Premultiplied)
        inverse_mask.fill(Qt.GlobalColor.white)
        source_rect = frame_rect.intersected(inverse_frame_mask.rect())
        if not source_rect.isEmpty():
            destination_rect = QRect(
                source_rect.topLeft() - frame_rect.topLeft(),
                source_rect.size(),
            )
            painter = QPainter(inverse_mask)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Source
            )
            painter.drawImage(destination_rect, inverse_frame_mask, source_rect)
            painter.end()
        painter = QPainter(masked)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        painter.drawImage(QPoint(), inverse_mask)
        painter.end()
        return masked

    @staticmethod
    def _inverse_mask(mask_image, output_size):
        mask = mask_image.convertToFormat(QImage.Format.Format_RGBA8888)
        if mask.size() != output_size:
            mask = mask.scaled(
                output_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        pixels = np.frombuffer(
            mask.constBits(),
            dtype=np.uint8,
            count=mask.bytesPerLine() * mask.height(),
        ).copy().reshape(
            (mask.height(), mask.bytesPerLine() // 4, 4)
        )
        pixels[:, : output_size.width(), 3] = np.where(
            pixels[:, : output_size.width(), 3] > 0,
            0,
            255,
        )
        return QImage(
            pixels.data,
            mask.width(),
            mask.height(),
            mask.bytesPerLine(),
            QImage.Format.Format_RGBA8888,
        ).copy().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    @classmethod
    def _reduce_for_processing(
        cls,
        image: QImage,
        scale_x: float,
        scale_y: float,
        render_scale: float,
    ) -> tuple[QImage, float, float]:
        reduction = max(0.01, min(1.0, render_scale))
        reduced = image.scaled(
            max(1, round(image.width() * reduction)),
            max(1, round(image.height() * reduction)),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )
        return reduced, scale_x / reduction, scale_y / reduction


class AspectRatioLabel(QLabel):
    viewport_changed = Signal()
    zoom_changed = Signal(float)
    view_changed = Signal(object)
    pan_delta = Signal(object)
    highlight_pan_delta = Signal(object)
    wheel_zoom_delta = Signal(float)
    mask_stroke = Signal(object)
    mask_stroke_finished = Signal()
    ping_requested = Signal(object)

    def __init__(self, performance=None, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.setMinimumSize(0, 0)
        self.zoom = 1.0
        self.pan_offset = QPoint()
        self.highlight_rect = None
        self.mouse_action_state = MouseActionState.SELECT
        self._pan_start = None
        self._highlight_pan_start = None
        self._mask_stroke_active = False
        self._mask_brush_size = 20
        self._mask_frame_size = QSize()
        self._mask_cursor_pos = None
        self._ping_position = None
        self._ping_started = None
        self._ping_duration = 0.8
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(16)
        self._ping_timer.timeout.connect(self._advance_ping)
        self.last_pixmap_update_ms = 0.0
        self.performance = performance or PerformanceChecker()
        self.setMouseTracking(True)

    def set_source_pixmap(self, pixmap: QPixmap):
        with self.performance.measure("ui.display.set_source_pixmap"):
            started = perf_counter()
            self._source_pixmap = pixmap
            self._update_pixmap()
            self.last_pixmap_update_ms = (perf_counter() - started) * 1000.0

    def set_zoom(self, zoom: float):
        with self.performance.measure("ui.display.set_zoom"):
            self.zoom = max(0.1, min(4.0, float(zoom)))
            self._update_pixmap()

    def set_mouse_action_state(self, state):
        self.mouse_action_state = state
        if state in (MouseActionState.PAN, MouseActionState.PLAYER_PAN):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif state is MouseActionState.PING:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif state in (
            MouseActionState.MASK,
            MouseActionState.MASK_FILL_ADD,
            MouseActionState.MASK_FILL_REMOVE,
        ):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if state not in (
            MouseActionState.MASK,
            MouseActionState.MASK_FILL_ADD,
            MouseActionState.MASK_FILL_REMOVE,
        ):
            self._mask_cursor_pos = None
        self.update()

    def set_mask_brush_size(self, brush_size):
        self._mask_brush_size = max(1, int(brush_size))
        self.update()

    def set_mask_frame_size(self, size):
        self._mask_frame_size = QSize(size)
        self.update()

    def _display_rect(self):
        if self.pixmap() is None or self.pixmap().isNull():
            return QRect()
        rect = self.pixmap().rect()
        rect.moveCenter(self.rect().center() + self.pan_offset)
        return rect

    def visible_source_rect(self):
        display_rect = self._display_rect()
        if display_rect.isEmpty():
            return (0.0, 0.0, 1.0, 1.0)
        visible = display_rect.intersected(self.rect())
        return (
            max(0.0, min(1.0, (visible.left() - display_rect.left()) / display_rect.width())),
            max(0.0, min(1.0, (visible.top() - display_rect.top()) / display_rect.height())),
            max(0.0, min(1.0, visible.width() / display_rect.width())),
            max(0.0, min(1.0, visible.height() / display_rect.height())),
        )

    def _clamp_pan(self):
        rect = self._display_rect()
        x_limit = max(0, (rect.width() - self.width()) // 2)
        y_limit = max(0, (rect.height() - self.height()) // 2)
        self.pan_offset.setX(max(-x_limit, min(x_limit, self.pan_offset.x())))
        self.pan_offset.setY(max(-y_limit, min(y_limit, self.pan_offset.y())))

    def pan_by(self, delta):
        self.pan_offset += delta
        self._clamp_pan()
        self.update()
        self.view_changed.emit(self.visible_source_rect())

    def wheelEvent(self, event):
        if self.mouse_action_state not in (
            MouseActionState.PAN,
            MouseActionState.PLAYER_PAN,
        ):
            event.ignore()
            return
        steps = event.angleDelta().y() / 120.0
        if self.mouse_action_state is MouseActionState.PLAYER_PAN:
            self.wheel_zoom_delta.emit(steps)
            event.accept()
            return
        self.set_zoom(self.zoom * (1.1 ** steps))
        self.zoom_changed.emit(self.zoom)
        self.view_changed.emit(self.visible_source_rect())
        event.accept()

    def mousePressEvent(self, event):
        self._mask_cursor_pos = event.position().toPoint()
        if (
            self.mouse_action_state is MouseActionState.PING
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.ping_requested.emit(event.position().toPoint())
            event.accept()
            return
        if (
            self.mouse_action_state
            in (
                MouseActionState.MASK,
                MouseActionState.MASK_FILL_ADD,
                MouseActionState.MASK_FILL_REMOVE,
            )
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._mask_stroke_active = True
            self.mask_stroke.emit(event.position().toPoint())
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.mouse_action_state is MouseActionState.PLAYER_PAN
            and self._highlight_contains(event.position().toPoint())
        ):
            self._highlight_pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            self.mouse_action_state in (
                MouseActionState.PAN,
                MouseActionState.PLAYER_PAN,
            )
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._mask_cursor_pos = event.position().toPoint()
        self.update()
        if self._mask_stroke_active:
            self.mask_stroke.emit(event.position().toPoint())
            event.accept()
            return
        if self._highlight_pan_start is not None:
            current = event.position().toPoint()
            self.highlight_pan_delta.emit(
                self._highlight_pan_start - current
            )
            self._highlight_pan_start = current
            event.accept()
            return
        if self._pan_start is not None:
            current = event.position().toPoint()
            delta = current - self._pan_start
            self._pan_start = current
            if self.mouse_action_state is MouseActionState.PLAYER_PAN:
                self.pan_delta.emit(delta)
            else:
                self.pan_by(delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._mask_stroke_active
        ):
            self._mask_stroke_active = False
            self.mask_stroke_finished.emit()
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._highlight_pan_start is not None
        ):
            self._highlight_pan_start = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if self.mouse_action_state is MouseActionState.PAN
                else Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._mask_cursor_pos = None
        self.update()
        super().leaveEvent(event)

    def _highlight_contains(self, point):
        if self.highlight_rect is None:
            return False
        display_rect = self._display_rect()
        if display_rect.isEmpty():
            return False
        highlight = self.highlight_rect
        rect = QRect(
            display_rect.left() + round(display_rect.width() * highlight[0]),
            display_rect.top() + round(display_rect.height() * highlight[1]),
            round(display_rect.width() * highlight[2]),
            round(display_rect.height() * highlight[3]),
        )
        return rect.contains(point)

    def set_highlight_rect(self, rect):
        self.highlight_rect = rect
        self.update()

    def set_ping_position(self, position):
        self._ping_position = (float(position[0]), float(position[1]))
        self._ping_started = perf_counter()
        self._ping_timer.start()
        self.update()

    def _advance_ping(self):
        if (
            self._ping_started is None
            or perf_counter() - self._ping_started >= self._ping_duration
        ):
            self._ping_started = None
            self._ping_position = None
            self._ping_timer.stop()
        self.update()

    def resizeEvent(self, event):
        with self.performance.measure("ui.display.resize"):
            super().resizeEvent(event)
            self._update_pixmap()
            self.viewport_changed.emit()

    def _update_pixmap(self):
        if self._source_pixmap.isNull():
            super().clear()
            return

        if self.width() <= 0 or self.height() <= 0:
            return

        fit_scale = min(
            self.width() / self._source_pixmap.width(),
            self.height() / self._source_pixmap.height(),
        )
        scaled_pixmap = self._source_pixmap.scaled(
            max(1, round(self._source_pixmap.width() * fit_scale * self.zoom)),
            max(1, round(self._source_pixmap.height() * fit_scale * self.zoom)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.pan_offset = QPoint(self.pan_offset)
        super().setPixmap(scaled_pixmap)
        self._clamp_pan()
        self.view_changed.emit(self.visible_source_rect())

    def paintEvent(self, event):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        pixmap_rect = self._display_rect()
        painter = QPainter(self)
        painter.drawPixmap(pixmap_rect, pixmap)
        self._draw_ping(painter, pixmap_rect)
        if self.highlight_rect is None:
            self._draw_mask_brush(painter, pixmap_rect)
            painter.end()
            return

        highlight = self.highlight_rect
        x = pixmap_rect.left() + round(pixmap_rect.width() * highlight[0])
        y = pixmap_rect.top() + round(pixmap_rect.height() * highlight[1])
        width = round(pixmap_rect.width() * highlight[2])
        height = round(pixmap_rect.height() * highlight[3])
        painter.setPen(QPen(QColor("#ffd166"), 3))
        painter.drawRect(x, y, width, height)
        self._draw_mask_brush(painter, pixmap_rect)
        painter.end()

    def _draw_ping(self, painter, display_rect):
        if self._ping_position is None or self._ping_started is None:
            return
        progress = min(
            1.0,
            max(0.0, (perf_counter() - self._ping_started) / self._ping_duration),
        )
        center = QPoint(
            display_rect.left() + round(display_rect.width() * self._ping_position[0]),
            display_rect.top() + round(display_rect.height() * self._ping_position[1]),
        )
        base_radius = max(
            8, round(min(display_rect.width(), display_rect.height()) * 0.035)
        )
        spread = max(
            10, round(min(display_rect.width(), display_rect.height()) * 0.12)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for offset, alpha in ((0.0, 220), (0.28, 140)):
            wave_progress = min(1.0, max(0.0, progress - offset))
            radius = base_radius + round(spread * wave_progress)
            color = QColor("#ffd166")
            color.setAlpha(round(alpha * (1.0 - wave_progress)))
            painter.setPen(
                QPen(color, max(2, round(3 * (1.0 - wave_progress))))
            )
            painter.drawEllipse(center, radius, radius)

    def _draw_mask_brush(self, painter, display_rect):
        if (
            self.mouse_action_state is not MouseActionState.MASK
            or self._mask_cursor_pos is None
            or not display_rect.contains(self._mask_cursor_pos)
        ):
            return
        frame_width = max(
            1,
            self._mask_frame_size.width()
            if not self._mask_frame_size.isEmpty()
            else self._source_pixmap.width(),
        )
        radius = max(
            1,
            round(
                self._mask_brush_size
                * display_rect.width()
                / frame_width
                / 2
            ),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#ffd166"), 2))
        painter.drawEllipse(self._mask_cursor_pos, radius, radius)


class Screen(QWidget):
    visibility_attribute = "visible"
    render_thread_priority = QThread.Priority.NormalPriority
    frame_changed = Signal()
    zoom_changed = Signal(float)

    def __init__(
        self,
        layer_manager: LayerManager,
        parent=None,
        show_mouse_action_menu=True,
    ):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layer_manager = layer_manager
        self.performance = PerformanceChecker()
        self.frame = Frame(1920, 1080)  # Default size, can be changed later
        self._render_request_id = 0
        self._last_render_signature = None
        self._render_thread = QThread(self)
        self._render_engine = RenderEngine(
            self.frame.size,
            self.frame.background_color,
            performance=self.performance,
        )
        self._render_engine.moveToThread(self._render_thread)
        self._render_engine.rendered.connect(self._set_rendered_canvas)
        self._render_thread.finished.connect(self._render_engine.deleteLater)
        self._render_thread.start()
        self._render_thread.setPriority(self.render_thread_priority)

        # Shared display area
        self.display_widget = AspectRatioLabel(self.performance)
        self.layout.addWidget(self.display_widget)
        self.mouse_action_menu = None
        if show_mouse_action_menu:
            self.mouse_action_menu = MouseActionMenu(self.display_widget)
            self.mouse_action_menu.state_changed.connect(
                self.display_widget.set_mouse_action_state
            )
            self.mouse_action_menu.adjustSize()
            self.mouse_action_menu.move(8, 8)
            self.mouse_action_menu.raise_()
        self.display_widget.zoom_changed.connect(self.set_zoom)
        self.layer_manager.subscribe_to_updates(self.draw)
        self.layer_manager.subscribe_to_media_updates(self.draw)

        self.build_ui()
        self.draw()

    def set_zoom(self, zoom: float):
        with self.performance.measure("ui.screen.set_zoom"):
            self.display_widget.set_zoom(zoom)
        self.zoom_changed.emit(self.display_widget.zoom)

    def build_ui(self):
        raise NotImplementedError

    def draw(self):
        """Draw visible layers from the bottom layer to the top layer."""
        signature = tuple(
            (
                id(layer),
                getattr(layer, self.visibility_attribute),
                layer.offset.x(),
                layer.offset.y(),
                layer.scale,
                layer.alpha,
                layer.mask_layer_id,
                id(layer.media),
                layer.media.current_frame().cacheKey()
                if layer.media is not None
                else None,
            )
            for layer in self.layer_manager.layers
        )
        if signature == self._last_render_signature:
            return
        self._last_render_signature = signature
        mask_layers = {
            layer.layer_id: layer
            for layer in self.layer_manager.layers
            if isinstance(layer.media, MaskMedia)
        }
        states = [
            self.frame._state_from_layer(layer, mask_layers)
            for layer in reversed(self.layer_manager.layers)
            if getattr(layer, self.visibility_attribute)
        ]
        states = [state for state in states if state is not None]
        self._render_request_id += 1
        self._render_engine.submit(self._render_request_id, states)

    def sync_frame_settings(self):
        """Apply the current frame settings to the background renderer."""
        self._render_engine.frame_size = self.frame.size
        self._render_engine.background_color = QColor(self.frame.background_color)
        self._last_render_signature = None
        self.draw()
        self.frame_changed.emit()

    def sync_frame_settings_from(self, source_frame: Frame):
        """Mirror frame size and background settings from another screen."""
        self.frame.set_size(
            source_frame.size.width(),
            source_frame.size.height(),
        )
        self.frame.set_background_color(source_frame.background_color)
        self._render_engine.frame_size = self.frame.size
        self._render_engine.background_color = QColor(
            self.frame.background_color
        )
        self._last_render_signature = None
        self.draw()

    @Slot(int, QImage)
    def _set_rendered_canvas(self, request_id: int, canvas: QImage):
        with self.performance.measure("ui.screen.receive_render"):
            if request_id != self._render_request_id:
                return
            if canvas.isNull():
                self.display_widget.set_source_pixmap(QPixmap())
                return

            self.display_widget.set_source_pixmap(QPixmap.fromImage(canvas))

    def closeEvent(self, event):
        self.layer_manager.unsubscribe_from_updates(self.draw)
        self.layer_manager.unsubscribe_from_media_updates(self.draw)
        self._render_engine.rendered.disconnect(self._set_rendered_canvas)
        self._render_engine.stop()
        self._render_thread.quit()
        self._render_thread.wait()
        super().closeEvent(event)