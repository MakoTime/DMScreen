from dataclasses import dataclass
from threading import Lock

import numpy as np

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
)
from PySide6.QtCore import QObject, QPoint, QRect, QSize, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QPen
from layer_manager import Layer, LayerManager
from layer_media import MaskMedia
from mouse_action import MouseActionMenu, MouseActionState


@dataclass
class RenderState:
    image: QImage
    offset: QPoint
    scale: tuple[float, float]
    alpha: float
    render_scale: float
    mask_image: QImage | None = None
    image_array: np.ndarray | None = None
    mask_array: np.ndarray | None = None


class RenderWorker(QObject):
    """Latest-frame renderer that keeps image processing off the GUI thread."""

    work_requested = Signal()
    rendered = Signal(int, QImage)

    def __init__(self, frame_size: QSize, background_color=QColor("black"), parent=None):
        super().__init__(parent)
        self.frame_size = QSize(frame_size)
        self.background_color = QColor(background_color)
        self.frame = Frame(
            *self.frame_size.toTuple(),
            output_scale=0.5,
            background_color=self.background_color,
        )
        self._lock = Lock()
        self._pending: tuple[int, list[RenderState]] | None = None
        self._scheduled = False
        self._stopped = False
        self.work_requested.connect(self.process)

    def submit(self, request_id: int, states: list[RenderState]):
        with self._lock:
            if self._stopped:
                return
            self._pending = (request_id, states)
            if self._scheduled:
                return
            self._scheduled = True
        self.work_requested.emit()

    def stop(self):
        with self._lock:
            self._stopped = True
            self._pending = None

    @Slot()
    def process(self):
        with self._lock:
            pending = self._pending
            self._pending = None
            self._scheduled = False
            stopped = self._stopped
        if stopped or pending is None:
            return

        request_id, states = pending
        self.frame.set_size(*self.frame_size.toTuple())
        self.frame.set_background_color(self.background_color)
        canvas = self.frame.render_states(states)
        self.rendered.emit(request_id, canvas)


class Frame:
    """Fixed drawing surface that clips every layer to its own bounds."""

    def __init__(
        self,
        width: int = 0,
        height: int = 0,
        output_scale: float = 1.0,
        background_color: QColor | None = None,
    ):
        self._size = QSize(max(0, width), max(0, height))
        self.output_scale = max(0.01, min(1.0, output_scale))
        self.background_color = QColor(background_color or "black")
        self._inverse_masks = {}

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
            for layer in layers
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
        for state in drawable_states:
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

    def __init__(self, parent=None):
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
        self.setMouseTracking(True)

    def set_source_pixmap(self, pixmap: QPixmap):
        self._source_pixmap = pixmap
        self._update_pixmap()

    def set_zoom(self, zoom: float):
        self.zoom = max(0.1, min(4.0, float(zoom)))
        self._update_pixmap()

    def set_mouse_action_state(self, state):
        self.mouse_action_state = state
        if state in (MouseActionState.PAN, MouseActionState.PLAYER_PAN):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
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

    def resizeEvent(self, event):
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
        self.frame = Frame(1920, 1080)  # Default size, can be changed later
        self._render_request_id = 0
        self._render_thread = QThread(self)
        self._render_worker = RenderWorker(
            self.frame.size,
            self.frame.background_color,
        )
        self._render_worker.moveToThread(self._render_thread)
        self._render_worker.rendered.connect(self._set_rendered_canvas)
        self._render_thread.start()

        # Shared display area
        self.display_widget = AspectRatioLabel()
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
        self.display_widget.set_zoom(zoom)
        self.zoom_changed.emit(self.display_widget.zoom)

    def build_ui(self):
        raise NotImplementedError

    def draw(self):
        """Draw visible layers from the bottom layer to the top layer."""
        mask_layers = {
            layer.layer_id: layer
            for layer in self.layer_manager.layers
            if isinstance(layer.media, MaskMedia)
        }
        states = [
            self.frame._state_from_layer(layer, mask_layers)
            for layer in self.layer_manager.layers
            if getattr(layer, self.visibility_attribute)
        ]
        states = [state for state in states if state is not None]
        self._render_request_id += 1
        self._render_worker.submit(self._render_request_id, states)

    def sync_frame_settings(self):
        """Apply the current frame settings to the background renderer."""
        self._render_worker.frame_size = self.frame.size
        self._render_worker.background_color = QColor(self.frame.background_color)
        self.draw()
        self.frame_changed.emit()

    def sync_frame_settings_from(self, source_frame: Frame):
        """Mirror frame size and background settings from another screen."""
        self.frame.set_size(
            source_frame.size.width(),
            source_frame.size.height(),
        )
        self.frame.set_background_color(source_frame.background_color)
        self._render_worker.frame_size = self.frame.size
        self._render_worker.background_color = QColor(
            self.frame.background_color
        )
        self.draw()

    @Slot(int, QImage)
    def _set_rendered_canvas(self, request_id: int, canvas: QImage):
        if request_id != self._render_request_id:
            return
        if canvas.isNull():
            self.display_widget.set_source_pixmap(QPixmap())
            return

        self.display_widget.set_source_pixmap(QPixmap.fromImage(canvas))

    def closeEvent(self, event):
        self.layer_manager.unsubscribe_from_updates(self.draw)
        self.layer_manager.unsubscribe_from_media_updates(self.draw)
        self._render_worker.stop()
        self._render_thread.quit()
        self._render_thread.wait()
        super().closeEvent(event)