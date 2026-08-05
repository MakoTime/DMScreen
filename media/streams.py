from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QMovie
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

from .base import LayerMedia


class GifMedia(LayerMedia):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._image = QImage()
        self._movie = QMovie(file_path, parent=self)
        self._movie.frameChanged.connect(self._on_frame_changed)
        self._movie.start()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    @property
    def render_scale(self) -> float:
        return 0.5

    def copy(self) -> "GifMedia":
        return GifMedia(self.file_path)

    def _on_frame_changed(self, frame_number: int):
        image = self._movie.currentImage()
        if not image.isNull():
            self._image = QImage(image)
            self.frame_changed.emit()

    def stop(self):
        self._movie.stop()


class VideoMedia(LayerMedia):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self._image = QImage()
        self._sink = QVideoSink(self)
        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_video_frame)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.setSource(QUrl.fromLocalFile(file_path))
        self._player.play()

    def frame_at(self, time_ms: int = 0) -> QImage:
        return self._image

    @property
    def render_scale(self) -> float:
        return 0.5

    def copy(self) -> "VideoMedia":
        return VideoMedia(self.file_path)

    def _on_video_frame(self, frame):
        image = frame.toImage()
        if not image.isNull():
            self._image = image
            self.frame_changed.emit()

    def stop(self):
        self._player.stop()
