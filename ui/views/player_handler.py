from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class PlayerHandler(QWidget):
    """Controls the visibility of the separate player window."""

    bring_player_requested = Signal()

    def __init__(self, player_window, parent=None):
        super().__init__(parent)
        self.player_window = player_window
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.show_button = QPushButton("Show Player Window")
        self.bring_player_button = QPushButton("Bring Player")
        self.close_button = QPushButton("Close Player Window")
        self.show_button.clicked.connect(self.show_player)
        self.bring_player_button.clicked.connect(self.bring_player_requested.emit)
        self.close_button.clicked.connect(self.close_player)

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.addWidget(self.show_button)
        layout.addWidget(self.bring_player_button)
        layout.addWidget(self.close_button)

    def show_player(self):
        self.player_window.showMaximized()
        self.player_window.raise_()
        self.player_window.activateWindow()

    def close_player(self):
        self.player_window.close()