from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QColorDialog,
    QFormLayout,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QSpinBox,
)

from player_handler import PlayerHandler
from screen import Frame


class FrameEditorDialog(QDialog):
    """Dialog for editing the fixed frame dimensions and background color."""

    def __init__(self, frame: Frame, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Frame")
        self.width_spin = self._size_spin(frame.size.width())
        self.height_spin = self._size_spin(frame.size.height())
        self.background_button = QPushButton(frame.background_color.name())
        self.background_color = QColor(frame.background_color)
        self.background_button.clicked.connect(self.choose_background)

        form = QFormLayout(self)
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)
        form.addRow("Background", self.background_button)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _size_spin(value: int):
        spin = QSpinBox()
        spin.setRange(1, 10000)
        spin.setValue(max(1, value))
        return spin

    def choose_background(self):
        color = QColorDialog.getColor(
            self.background_color,
            self,
            "Choose frame background",
        )
        if color.isValid():
            self.background_color = color
            self.background_button.setText(color.name())


class MenuBar(QMenuBar):
    """Application menu bar for DM-window actions."""

    frame_changed = Signal()
    save_requested = Signal()
    open_requested = Signal()
    new_requested = Signal()

    def __init__(
        self,
        player_handler: PlayerHandler,
        frame: Frame,
        parent=None,
    ):
        super().__init__(parent)
        self.player_handler = player_handler
        self.frame = frame
        self.dm_window = parent if isinstance(parent, QMainWindow) else None

        self.file_menu = self.addMenu("File")
        self.new_action = QAction("New", self)
        self.open_action = QAction("Open", self)
        self.save_action = QAction("Save", self)
        self.save_as_action = QAction("Save As", self)
        for action in (
            self.new_action,
            self.open_action,
            self.save_action,
            self.save_as_action,
        ):
            self.file_menu.addAction(action)

        self.edit_menu = self.addMenu("Edit")
        self.edit_frame_action = QAction("Edit Frame", self)
        self.edit_frame_action.triggered.connect(self.edit_frame)
        self.edit_menu.addAction(self.edit_frame_action)

        self.player_menu = self.addMenu("Player")
        self.show_player_action = QAction("Show Player Window", self)
        self.close_player_action = QAction("Close Player Window", self)
        self.show_player_action.triggered.connect(
            self._show_player
        )
        self.close_player_action.triggered.connect(
            self.player_handler.close_player
        )
        self.save_action.triggered.connect(self.save_requested.emit)
        self.save_as_action.triggered.connect(self.save_requested.emit)
        self.open_action.triggered.connect(self.open_requested.emit)
        self.new_action.triggered.connect(self.new_requested.emit)
        self.player_menu.addAction(self.show_player_action)
        self.player_menu.addAction(self.close_player_action)

        self.window_menu = self.addMenu("Window")
        self.maximize_dm_action = self._window_action(
            "Maximize DM Window", self.dm_window, "maximize"
        )
        self.fullscreen_dm_action = self._window_action(
            "Fullscreen DM Window", self.dm_window, "fullscreen"
        )
        player_window = self.player_handler.player_window
        self.maximize_player_action = self._window_action(
            "Maximize Player Window", player_window, "maximize"
        )
        self.fullscreen_player_action = self._window_action(
            "Fullscreen Player Window", player_window, "fullscreen"
        )
        self.window_menu.addActions(
            (
                self.maximize_dm_action,
                self.fullscreen_dm_action,
                self.maximize_player_action,
                self.fullscreen_player_action,
            )
        )
        self.sync_window_modes()

    def _show_player(self):
        self.player_handler.show_player()
        self.sync_window_modes()

    def sync_window_modes(self):
        self._sync_window_actions(self.dm_window)
        self._sync_window_actions(self.player_handler.player_window)

    def _window_action(self, text, window, mode):
        action = QAction(text, self)
        action.setCheckable(True)
        action.setEnabled(window is not None)
        if window is not None:
            action.triggered.connect(
                lambda checked: self._set_window_mode(window, mode, checked)
            )
        return action

    def _set_window_mode(self, window, mode, checked):
        if mode == "maximize":
            if checked:
                window.showMaximized()
            else:
                window.showNormal()
        elif checked:
            window.showFullScreen()
        else:
            window.showNormal()
        self._sync_window_actions(window)

    def _sync_window_actions(self, window):
        if window is None:
            return
        is_dm = window is self.dm_window
        maximize_action = (
            self.maximize_dm_action if is_dm else self.maximize_player_action
        )
        fullscreen_action = (
            self.fullscreen_dm_action
            if is_dm
            else self.fullscreen_player_action
        )
        state = window.windowState()
        maximize_action.setChecked(bool(state & Qt.WindowState.WindowMaximized))
        fullscreen_action.setChecked(
            bool(state & Qt.WindowState.WindowFullScreen)
        )

    def edit_frame(self):
        dialog = FrameEditorDialog(self.frame, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_frame_settings(
                dialog.width_spin.value(),
                dialog.height_spin.value(),
                dialog.background_color,
            )

    def apply_frame_settings(self, width: int, height: int, color: QColor):
        self.frame.set_size(width, height)
        self.frame.set_background_color(color)
        self.frame_changed.emit()
