from PySide6.QtWidgets import QMainWindow
from constants import ScreenType
from dm_screen import DMScreen
from layer_manager import LayerManager
from menu import MenuBar
from player_handler import PlayerHandler
from player_controls import PlayerControlsPanel
from player_screen import PlayerScreen
from zoom_handler import ZoomHandler


class DMController:
    def __init__(self):
        self.dm_window = QMainWindow()
        self.player_window = QMainWindow()

        self.layer_manager = LayerManager()

        self.player_screen = PlayerScreen(self.layer_manager)
        self.player_window.setCentralWidget(self.player_screen)
        self.player_handler = PlayerHandler(self.player_window)
        self.zoom_handler = ZoomHandler()
        self.player_controls = PlayerControlsPanel(self.player_handler)
        self.dm_screen = DMScreen(
            self.layer_manager,
            self.player_controls,
            self.zoom_handler,
            self.player_screen,
        )
        self.zoom_handler.dm_zoom_changed.connect(self.dm_screen.set_zoom)
        self.player_controls.player_zoom_changed.connect(
            self.player_screen.set_zoom
        )
        self.player_controls.player_zoom_changed.connect(
            self.dm_screen.update_player_highlight
        )
        self.dm_screen.zoom_changed.connect(self.zoom_handler.dm_zoom_spin.setValue)
        self.player_screen.zoom_changed.connect(
            self.player_controls.player_zoom_spin.setValue
        )
        self.player_screen.display_widget.viewport_changed.connect(
            lambda: self.dm_screen.update_player_highlight(
                self.player_controls.player_zoom_spin.value()
            )
        )
        self.player_screen.display_widget.view_changed.connect(
            self.dm_screen.set_player_viewport_rect
        )

        self.dm_window.setCentralWidget(self.dm_screen)
        self.menu_bar = MenuBar(
            self.player_handler,
            self.dm_screen.frame,
            self.dm_window,
        )
        self.menu_bar.frame_changed.connect(self.dm_screen.sync_frame_settings)
        self.dm_screen.frame_changed.connect(
            lambda: self.player_screen.sync_frame_settings_from(
                self.dm_screen.frame
            )
        )
        self.dm_window.setMenuBar(self.menu_bar)

        self.player_window.hide()

    def set_screen_size(self, screen_type, width, height):
        if screen_type == ScreenType.DM:
            self.dm_window.resize(width, height)
        elif screen_type == ScreenType.PLAYER:
            self.player_window.resize(width, height)

    def start(self):
        self.dm_window.showMaximized()
        self.menu_bar.sync_window_modes()

    def show_player_screen(self):
        self.player_handler.show_player()

    def hide_player_screen(self):
        self.player_handler.close_player()