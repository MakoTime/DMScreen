import unittest

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMainWindow

from menu import MenuBar
from player_handler import PlayerHandler
from screen import Frame


class TestMenuBar(unittest.TestCase):
    def setUp(self):
        self.dm_window = QMainWindow()
        self.player_window = QMainWindow()
        self.player_handler = PlayerHandler(self.player_window)
        self.frame = Frame(1920, 1080)
        self.menu_bar = MenuBar(
            self.player_handler,
            self.frame,
            self.dm_window,
        )

    def tearDown(self):
        self.menu_bar.deleteLater()
        self.player_handler.deleteLater()
        self.dm_window.close()
        self.dm_window.deleteLater()
        self.player_window.close()
        self.player_window.deleteLater()
        QApplication.processEvents()

    def test_player_menu_exposes_show_and_close_actions(self):
        self.assertEqual(
            [action.text() for action in self.menu_bar.actions()],
            ["File", "Edit", "Player", "Window"],
        )
        self.assertEqual(
            [action.text() for action in self.menu_bar.file_menu.actions()],
            [
                "New",
                "Open",
                "Save",
                "Save As",
                "Save All Scenes",
                "Clear All Scenes",
            ],
        )
        self.assertEqual(
            [action.text() for action in self.menu_bar.edit_menu.actions()],
            ["Edit Frame", "Rename Scene"],
        )
        self.assertEqual(
            [action.text() for action in self.menu_bar.player_menu.actions()],
            ["Show Player Window", "Close Player Window"],
        )
        self.assertEqual(
            [action.text() for action in self.menu_bar.window_menu.actions()],
            [
                "Maximize DM Window",
                "Fullscreen DM Window",
                "Maximize Player Window",
                "Fullscreen Player Window",
            ],
        )

    def test_apply_frame_settings_updates_frame(self):
        changed = []
        self.menu_bar.frame_changed.connect(lambda: changed.append(True))
        self.menu_bar.apply_frame_settings(800, 600, QColor("#203040"))
        self.assertEqual(self.frame.size.width(), 800)
        self.assertEqual(self.frame.size.height(), 600)
        self.assertEqual(self.frame.background_color, QColor("#203040"))
        self.assertEqual(changed, [True])

    def test_save_and_save_as_emit_distinct_signals(self):
        saved = []
        saved_as = []
        self.menu_bar.save_requested.connect(lambda: saved.append(True))
        self.menu_bar.save_as_requested.connect(lambda: saved_as.append(True))

        self.menu_bar.save_action.trigger()
        self.menu_bar.save_as_action.trigger()

        self.assertEqual(saved, [True])
        self.assertEqual(saved_as, [True])

    def test_player_menu_actions_control_player_window(self):
        self.menu_bar.show_player_action.trigger()
        QApplication.processEvents()
        self.assertTrue(self.player_window.isVisible())
        self.assertTrue(self.player_window.isMaximized())

        self.menu_bar.close_player_action.trigger()
        QApplication.processEvents()
        self.assertFalse(self.player_window.isVisible())

    def test_window_menu_toggles_dm_and_player_modes(self):
        self.menu_bar.maximize_dm_action.trigger()
        QApplication.processEvents()
        self.assertTrue(self.dm_window.isMaximized())
        self.assertFalse(self.dm_window.isFullScreen())

        self.menu_bar.fullscreen_dm_action.trigger()
        QApplication.processEvents()
        self.assertTrue(self.dm_window.isFullScreen())
        self.assertFalse(self.menu_bar.maximize_dm_action.isChecked())

        self.menu_bar.fullscreen_player_action.trigger()
        QApplication.processEvents()
        self.assertTrue(self.player_window.isFullScreen())
        self.assertFalse(self.menu_bar.maximize_player_action.isChecked())

        self.menu_bar.maximize_player_action.trigger()
        QApplication.processEvents()
        self.assertTrue(self.player_window.isMaximized())
        self.assertFalse(self.player_window.isFullScreen())


if __name__ == "__main__":
    unittest.main()