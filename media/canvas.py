import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .base import LayerMedia


class ImageMedia(LayerMedia):
    def __init__(self, image: QImage | None = None, parent=None):
        super().__init__(parent)
        self._image = QImage(image) if image is not None else QImage()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    def copy(self) -> "ImageMedia":
        return ImageMedia(self._image)

    def set_image(self, image: QImage):
        self._image = QImage(image)
        self.frame_changed.emit()


class DrawMedia(ImageMedia):
    def __init__(self, width: int, height: int, brush_size=20, parent=None):
        self.brush_size = max(1, int(brush_size))
        image = QImage(
            max(1, int(width)),
            max(1, int(height)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        super().__init__(image, parent)

    def copy(self) -> "DrawMedia":
        copied = DrawMedia(
            self._image.width(), self._image.height(), self.brush_size
        )
        copied._image = QImage(self._image)
        return copied

    def _paint(self, brush_size, erase):
        painter = QPainter(self._image)
        if erase:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(QPen(
            QColor("white"),
            max(1, int(brush_size or self.brush_size)),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        return painter

    def paint_at(self, x: int, y: int, brush_size=None, erase=False):
        painter = self._paint(brush_size, erase)
        painter.drawPoint(int(x), int(y))
        painter.end()
        self.frame_changed.emit()

    def paint_line(
        self,
        start_x,
        start_y,
        end_x,
        end_y,
        brush_size=None,
        erase=False,
    ):
        painter = self._paint(brush_size, erase)
        painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))
        painter.end()
        self.frame_changed.emit()


class MaskMedia(ImageMedia):
    def __init__(
        self,
        width: int,
        height: int,
        auto_fill=False,
        brush_size=20,
        parent=None,
    ):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.auto_fill = bool(auto_fill)
        self.brush_size = max(1, int(brush_size))
        super().__init__(self._new_image(), parent)
        self._coverage = None

    def _new_image(self):
        image = QImage(
            self.width,
            self.height,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.white if self.auto_fill else Qt.GlobalColor.transparent)
        return image

    def copy(self) -> "MaskMedia":
        copied = MaskMedia(self.width, self.height, self.auto_fill, self.brush_size)
        copied._image = QImage(self._image)
        return copied

    def set_auto_fill(self, auto_fill: bool):
        self.auto_fill = bool(auto_fill)
        self._image = self._new_image()
        self._coverage = None
        self.frame_changed.emit()

    def fill(self, erase=False):
        self._image.fill(Qt.GlobalColor.transparent if erase else Qt.GlobalColor.white)
        self._coverage = None
        self.frame_changed.emit()

    def frame_array(self):
        if self._coverage is None:
            rgba_image = self._image.convertToFormat(QImage.Format.Format_RGBA8888)
            pixels = np.frombuffer(
                rgba_image.constBits(),
                dtype=np.uint8,
                count=rgba_image.bytesPerLine() * rgba_image.height(),
            ).copy().reshape((rgba_image.height(), rgba_image.bytesPerLine() // 4, 4))
            self._coverage = pixels[:, : self.width, 3] > 0
        return self._coverage

    def flood_fill(self, x, y, erase=False):
        if not (0 <= int(x) < self.width and 0 <= int(y) < self.height):
            return
        rgba_image = self._image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(
            rgba_image.constBits(),
            dtype=np.uint8,
            count=rgba_image.bytesPerLine() * rgba_image.height(),
        ).copy().reshape((rgba_image.height(), rgba_image.bytesPerLine() // 4, 4))
        alpha = pixels[:, : self.width, 3]
        region = np.where(alpha > 0, 255, 0).astype(np.uint8)
        target = region[int(y), int(x)]
        desired = 0 if erase else 255
        if target == desired:
            return
        mask = np.zeros((self.height + 2, self.width + 2), np.uint8)
        cv2.floodFill(region, mask, (int(x), int(y)), desired, flags=4)
        changed = region != np.where(alpha > 0, 255, 0)
        pixels_view = pixels[:, : self.width]
        if erase:
            pixels_view[changed, :3] = 0
            pixels_view[changed, 3] = 0
        else:
            pixels_view[changed, :3] = 255
            pixels_view[changed, 3] = 255
        self._image = QImage(
            pixels.data,
            self.width,
            self.height,
            rgba_image.bytesPerLine(),
            QImage.Format.Format_RGBA8888,
        ).copy().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self._coverage = None
        self.frame_changed.emit()

    def _paint(self, brush_size, erase):
        painter = QPainter(self._image)
        if erase:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(QPen(
            QColor("white"),
            max(1, int(brush_size or self.brush_size)),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        return painter

    def paint_at(self, x: int, y: int, brush_size=None, erase=False):
        painter = self._paint(brush_size, erase)
        painter.drawPoint(int(x), int(y))
        painter.end()
        self._coverage = None
        self.frame_changed.emit()

    def paint_line(self, start_x, start_y, end_x, end_y, brush_size=None, erase=False):
        painter = self._paint(brush_size, erase)
        painter.drawLine(int(start_x), int(start_y), int(end_x), int(end_y))
        painter.end()
        self._coverage = None
        self.frame_changed.emit()
