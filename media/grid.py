import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .base import LayerMedia


def detect_grid_parameters(image: QImage):
    if image.isNull():
        return None
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(rgba.bits(), dtype=np.uint8, count=rgba.sizeInBytes()).reshape(
        rgba.height(), rgba.bytesPerLine()
    )
    pixels = pixels[:, : rgba.width() * 4].reshape(rgba.height(), rgba.width(), 4)
    gray = cv2.cvtColor(pixels[:, :, :3], cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    minimum_length = max(20, min(image.width(), image.height()) // 8)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=max(20, minimum_length // 2),
        minLineLength=minimum_length, maxLineGap=8,
    )
    if lines is None:
        return None

    horizontal = []
    vertical = []
    for line in np.asarray(lines).reshape(-1, 4):
        x1, y1, x2, y2 = map(int, line)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx >= dy * 4:
            horizontal.append((y1 + y2) / 2)
        elif dy >= dx * 4:
            vertical.append((x1 + x2) / 2)

    spacing_x = _spacing_from_positions(vertical)
    spacing_y = _spacing_from_positions(horizontal)
    if spacing_x is None and spacing_y is None:
        return None
    spacing_x = spacing_x or spacing_y
    spacing_y = spacing_y or spacing_x
    offset_x = round(min(vertical) % spacing_x) if vertical else 0
    offset_y = round(min(horizontal) % spacing_y) if horizontal else 0
    return spacing_x, spacing_y, offset_x, offset_y


def _spacing_from_positions(positions):
    if len(positions) < 2:
        return None
    positions = sorted(positions)
    clusters = []
    for position in positions:
        if not clusters or position - clusters[-1][-1] > 4:
            clusters.append([position])
        else:
            clusters[-1].append(position)
    differences = np.diff([sum(cluster) / len(cluster) for cluster in clusters])
    differences = differences[differences >= 5]
    return round(float(np.median(differences))) if len(differences) else None


class GridMedia(LayerMedia):
    def __init__(self, width: int = 1920, height: int = 1080, parent=None):
        super().__init__(parent)
        self.width = max(16, int(width))
        self.height = max(16, int(height))
        self.spacing_x = 100
        self.spacing_y = 100
        self.offset_x = 0
        self.offset_y = 0
        self.line_width = 2
        self.color = QColor("#d7e4e8")
        self._image = QImage()
        self._render()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    def copy(self) -> "GridMedia":
        copied = GridMedia(self.width, self.height)
        copied.spacing_x, copied.spacing_y = self.spacing_x, self.spacing_y
        copied.offset_x, copied.offset_y = self.offset_x, self.offset_y
        copied.line_width = self.line_width
        copied.color = QColor(self.color)
        copied._render()
        return copied

    def set_parameters(self, spacing_x, spacing_y, offset_x, offset_y, line_width, color):
        spacing = max(2, int(round((spacing_x + spacing_y) / 2)))
        self.spacing_x = spacing
        self.spacing_y = spacing
        self.offset_x, self.offset_y = int(offset_x), int(offset_y)
        self.line_width = max(1, min(20, int(line_width)))
        self.color = QColor(color)
        self._render()
        self.frame_changed.emit()

    def detect_from_image(self, image: QImage) -> bool:
        detected = detect_grid_parameters(image)
        if detected is None:
            return False
        spacing_x, spacing_y, self.offset_x, self.offset_y = detected
        spacing = max(2, round((spacing_x + spacing_y) / 2))
        self.spacing_x = self.spacing_y = spacing
        self._render()
        self.frame_changed.emit()
        return True

    @staticmethod
    def detect_parameters(image: QImage):
        return detect_grid_parameters(image)

    def _render(self):
        self._image = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        self._image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._image)
        painter.setPen(QPen(self.color, self.line_width))
        for x in range(self.offset_x % self.spacing_x, self.width, self.spacing_x):
            painter.drawLine(x, 0, x, self.height)
        for y in range(self.offset_y % self.spacing_y, self.height, self.spacing_y):
            painter.drawLine(0, y, self.width, y)
        painter.end()
