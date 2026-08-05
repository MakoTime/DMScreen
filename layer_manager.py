from dataclasses import dataclass, field
from uuid import uuid4

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from layer_media import ImageMedia, LayerMedia

@dataclass
class Layer:
    name: str
    media: LayerMedia | QImage | None = None
    visible: bool = True
    player_visible: bool = True
    offset: QPoint = field(default_factory=QPoint)
    scale: tuple[float, float] = (1.0, 1.0)  # (scale_x, scale_y)
    alpha: float = 1.0
    layer_id: str = field(default_factory=lambda: str(uuid4()))
    mask_layer_id: str | None = None

    def __post_init__(self):
        if isinstance(self.media, QImage):
            self.media = ImageMedia(self.media)

class LayerManager:
    def __init__(self):
        self.layers: list[Layer] = []
        self.notify_update_callbacks: list[callable] = []
        self.notify_media_callbacks: list[callable] = []
        self._connected_media: dict[int, LayerMedia] = {}

    def add(self, layer: Layer):
        self.layers.append(layer)
        self._connect_layer_media(layer)
        self.on_update()

    def move(self, old: int, new: int):
        layer = self.layers.pop(old)
        self.layers.insert(new, layer)
        self.on_update()

    def remove(self, index: int):
        layer = self.layers.pop(index)
        connected_media = self._connected_media.pop(id(layer), None)
        if connected_media is not None:
            connected_media.frame_changed.disconnect(self.on_media_update)
            connected_media.stop()
        self.on_update()

    def subscribe_to_updates(self, callback: callable):
        self.notify_update_callbacks.append(callback)

    def subscribe_to_media_updates(self, callback: callable):
        self.notify_media_callbacks.append(callback)

    def unsubscribe_from_updates(self, callback: callable):
        if callback in self.notify_update_callbacks:
            self.notify_update_callbacks.remove(callback)

    def unsubscribe_from_media_updates(self, callback: callable):
        if callback in self.notify_media_callbacks:
            self.notify_media_callbacks.remove(callback)

    def on_update(self):
        for layer in self.layers:
            self._connect_layer_media(layer)
        for callback in self.notify_update_callbacks:
            callback()

    def on_media_update(self):
        for callback in self.notify_media_callbacks:
            callback()

    def _connect_layer_media(self, layer: Layer):
        layer_id = id(layer)
        connected_media = self._connected_media.get(layer_id)
        if connected_media is layer.media:
            return
        if connected_media is not None:
            connected_media.frame_changed.disconnect(self.on_media_update)
            connected_media.stop()
        self._connected_media.pop(layer_id, None)
        if layer.media is not None:
            layer.media.frame_changed.connect(self.on_media_update)
            self._connected_media[layer_id] = layer.media


def __getattr__(name):
    """Keep legacy layer UI imports working after the UI split."""
    if name in {"LayerModel", "LayerTable", "SidePanel", "LayerPanel"}:
        from layer_ui import LayerModel, LayerPanel, LayerTable
        from side_panel import SidePanel

        return {
            "LayerModel": LayerModel,
            "LayerTable": LayerTable,
            "SidePanel": SidePanel,
            "LayerPanel": LayerPanel,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
