from PySide6.QtWidgets import QLabel
from screen import Screen

class PlayerScreen(Screen):
    visibility_attribute = "player_visible"

    def __init__(self, layer_manager, parent=None):
        super().__init__(
            layer_manager,
            parent=parent,
            show_mouse_action_menu=False,
        )

    def build_ui(self):
        # Player-specific controls (or none)
        pass