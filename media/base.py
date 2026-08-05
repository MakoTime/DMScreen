from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QImage


class LayerMedia(QObject):
    """Interface for visual content rendered by a layer."""

    frame_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    @property
    def render_scale(self) -> float:
        return 1.0

    def frame_at(self, time_ms: int = 0) -> QImage:
        raise NotImplementedError

    def copy(self) -> "LayerMedia":
        raise NotImplementedError

    def current_frame(self) -> QImage:
        return self.frame_at(0)

    def frame_array(self):
        return None

    @property
    def size(self) -> QSize:
        return self.current_frame().size()

    def is_empty(self) -> bool:
        return self.current_frame().isNull()

    def stop(self):
        pass
