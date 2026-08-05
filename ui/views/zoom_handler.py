from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QPushButton, QWidget


class ZoomHandler(QWidget):
    """Controls the DM scene zoom value."""

    dm_zoom_changed = Signal(float)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dm_zoom_spin = self._zoom_spin()
        self.reset_button = QPushButton("Reset DM Zoom")

        form = QFormLayout(self)
        form.addRow("DM Zoom", self.dm_zoom_spin)
        form.addRow(self.reset_button)

        self.dm_zoom_spin.valueChanged.connect(self.dm_zoom_changed)
        self.reset_button.clicked.connect(self.reset)

    @staticmethod
    def _zoom_spin():
        spin = QDoubleSpinBox()
        spin.setRange(0.1, 4.0)
        spin.setSingleStep(0.1)
        spin.setDecimals(1)
        spin.setValue(1.0)
        spin.setSuffix("x")
        return spin

    def reset(self):
        self.dm_zoom_spin.setValue(1.0)
