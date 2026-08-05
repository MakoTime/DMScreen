from PySide6.QtWidgets import QVBoxLayout, QWidget

from layer_manager import Layer, LayerManager
from layer_ui import LayerPanel
from screen import Frame
from zoom_handler import ZoomHandler


class SidePanel(QWidget):
    """Vertical sidebar containing layer controls and player controls."""

    def __init__(
        self,
        layer_manager: LayerManager,
        frame: Frame | None = None,
        parent=None,
        frame_changed_callback=None,
        zoom_handler: ZoomHandler | None = None,
    ):
        super().__init__(parent)
        self.layer_panel = LayerPanel(
            layer_manager,
            frame,
            self,
            frame_changed_callback,
        )
        self.zoom_handler = zoom_handler

        layout = QVBoxLayout(self)
        layout.addWidget(self.layer_panel, 1)
        if self.zoom_handler is not None:
            self.zoom_handler.setParent(self)
            layout.addWidget(self.zoom_handler, 0)

    @property
    def table(self):
        return self.layer_panel.table

    @property
    def add_button(self):
        return self.layer_panel.add_button

    @property
    def edit_button(self):
        return self.layer_panel.edit_button

    def add_layer(self, layer: Layer):
        self.layer_panel.add_layer(layer)

    def remove_selected(self):
        self.layer_panel.remove_selected()

    def edit_selected(self):
        self.layer_panel.edit_selected()
