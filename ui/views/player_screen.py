from PySide6.QtCore import QThread
from PySide6.QtWidgets import QLabel
from constants import PLAYER_ZOOM_MAX
from screen import Screen

class PlayerScreen(Screen):
    visibility_attribute = "player_visible"
    render_thread_priority = QThread.Priority.HighPriority

    def __init__(self, layer_manager, parent=None):
        self._destroying_from_dm = False
        super().__init__(
            layer_manager,
            parent=parent,
            show_mouse_action_menu=False,
        )
        self.display_widget.max_zoom = PLAYER_ZOOM_MAX
        self.display_widget.limit_render_size = True

    def build_ui(self):
        # Player-specific controls (or none)
        pass

    def destroy_from_dm(self):
        if self._destroying_from_dm:
            return
        self._destroying_from_dm = True
        window = self.window()
        self.close()
        if window is not None:
            window.close()
        self.deleteLater()