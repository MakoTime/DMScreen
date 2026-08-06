from PySide6.QtWidgets import QFileDialog, QMainWindow
from constants import ScreenType
from dm_screen import DMScreen
from layer_manager import LayerManager
from menu import MenuBar
from player_handler import PlayerHandler
from player_controls import PlayerControlsPanel
from player_screen import PlayerScreen
from zoom_handler import ZoomHandler
from project_io import load_project, save_project


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
        self.menu_bar.save_requested.connect(self.save_project)
        self.menu_bar.open_requested.connect(self.open_project)
        self.menu_bar.new_requested.connect(self.new_project)
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

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self.dm_window,
            "Save DMScreen Project",
            "",
            "DMScreen Project (*.dms)",
        )
        if path:
            save_project(path, self.dm_screen.frame, self.layer_manager)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self.dm_window,
            "Open DMScreen Project",
            "",
            "DMScreen Project (*.dms)",
        )
        if not path:
            return
        frame, layers = load_project(path)
        self.dm_screen.frame.set_size(frame["width"], frame["height"])
        self.dm_screen.frame.set_background_color(frame["background"])
        self.layer_manager.replace_layers(layers)
        self.dm_screen.sync_frame_settings()
        self.player_screen.sync_frame_settings_from(self.dm_screen.frame)

    def new_project(self):
        self.dm_screen.frame.set_size(1920, 1080)
        self.dm_screen.frame.set_background_color("black")
        self.dm_screen.reset_project_overlays()
        self.layer_manager.replace_layers([])
        self.dm_screen.create_default_layers()
        self.dm_screen.sync_frame_settings()
        self.player_screen.sync_frame_settings_from(self.dm_screen.frame)

    def show_player_screen(self):
        self.player_handler.show_player()

    def hide_player_screen(self):
        self.player_handler.close_player()