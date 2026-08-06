from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QPushButton, QWidget

from constants import PLAYER_ZOOM_MAX
from player_handler import PlayerHandler


class PlayerControlsPanel(QWidget):
    """Right-side controls for the Player window and Player scene view."""

    player_zoom_changed = Signal(float)

    def __init__(self, player_handler: PlayerHandler, parent=None):
        super().__init__(parent)
        self.player_handler = player_handler
        self.player_zoom_spin = self._zoom_spin()
        self.reset_player_zoom_button = QPushButton("Reset Player Zoom")

        form = QFormLayout(self)
        form.addRow(self.player_handler)
        form.addRow("Player Zoom", self.player_zoom_spin)
        form.addRow(self.reset_player_zoom_button)

        self.player_zoom_spin.valueChanged.connect(self.player_zoom_changed)
        self.reset_player_zoom_button.clicked.connect(self.reset_player_zoom)

    @staticmethod
    def _zoom_spin():
        spin = QDoubleSpinBox()
        spin.setRange(0.1, PLAYER_ZOOM_MAX)
        spin.setSingleStep(0.1)
        spin.setDecimals(1)
        spin.setValue(1.0)
        spin.setSuffix("x")
        return spin

    def reset_player_zoom(self):
        self.player_zoom_spin.setValue(1.0)
