from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)
from constants import PLAYER_ZOOM_MAX, ScreenType
from dm_screen import DMScreen
from layer_manager import LayerManager
from menu import MenuBar
from player_handler import PlayerHandler
from player_controls import PlayerControlsPanel
from player_screen import PlayerScreen
from zoom_handler import ZoomHandler
from project_io import load_project, save_project
from scenes import Scene


class DMController:
    def __init__(self):
        self.dm_window = QMainWindow()
        self.player_window = QMainWindow()
        self.dm_window.closeEvent = self._dm_window_close_event

        self.layer_manager = LayerManager()
        cache_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
        ) / "scene-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        self.cache_root = cache_root
        self._clear_scene_cache()
        QCoreApplication.instance().aboutToQuit.connect(
            self._clear_scene_cache
        )

        self.player_screen = PlayerScreen(self.layer_manager)
        self.player_window.setCentralWidget(self.player_screen)
        self.player_handler = PlayerHandler(self.player_window)
        self.player_handler.bring_player_requested.connect(
            self.bring_player_to_active_scene
        )
        self.zoom_handler = ZoomHandler()
        self.player_controls = PlayerControlsPanel(self.player_handler)
        self.dm_screen = DMScreen(
            self.layer_manager,
            self.player_controls,
            self.zoom_handler,
            self.player_screen,
        )
        self.dm_screen.pending_player_pan.connect(
            self._pan_pending_player_view
        )
        self.dm_screen.pending_player_zoom.connect(
            self._zoom_pending_player_view
        )
        self.dm_screen.player_close_requested.connect(
            self.player_screen.destroy_from_dm
        )
        self.layer_manager.replace_layers([])
        self.layer_manager.set_player_attached(False)
        self.dm_screen.set_scene_available(False)
        self.scenes = []
        self.active_scene_index = -1
        self.player_scene_index = -1
        self._restoring_player_view = False
        self.dm_screen.scene_tabs.set_scene_names([])
        self.dm_screen.scene_tabs.add_requested.connect(self.add_scene)
        self.dm_screen.scene_tabs.current_changed.connect(self.select_scene)
        self.dm_screen.scene_tabs.rename_requested.connect(self.rename_scene)
        self.dm_screen.scene_tabs.close_requested.connect(self.close_scene)
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
        self.player_screen.display_widget.view_changed.connect(
            self._store_player_view
        )
        self.player_screen.zoom_changed.connect(self._store_player_view)

        self.dm_window.setCentralWidget(self.dm_screen)
        self.menu_bar = MenuBar(
            self.player_handler,
            self.dm_screen.frame,
            self.dm_window,
        )
        self.menu_bar.frame_changed.connect(self.dm_screen.sync_frame_settings)
        self.menu_bar.frame_changed.connect(self.mark_active_scene_dirty)
        self.menu_bar.save_requested.connect(self.save_project)
        self.menu_bar.save_as_requested.connect(self.save_as_project)
        self.menu_bar.save_all_requested.connect(self.save_all_projects)
        self.menu_bar.open_requested.connect(self.open_project)
        self.menu_bar.new_requested.connect(self.new_project)
        self.menu_bar.clear_all_scenes_requested.connect(self.clear_all_scenes)
        self.menu_bar.rename_scene_requested.connect(self.rename_active_scene)
        self.dm_screen.frame_changed.connect(
            self._sync_player_frame_if_attached
        )
        self.dm_window.setMenuBar(self.menu_bar)

        self.player_window.hide()

    def _dm_window_close_event(self, event):
        self.dm_screen.close()
        event.accept()

    def set_screen_size(self, screen_type, width, height):
        if screen_type == ScreenType.DM:
            self.dm_window.resize(width, height)
        elif screen_type == ScreenType.PLAYER:
            self.player_window.resize(width, height)

    def start(self):
        self.dm_window.showMaximized()
        self.menu_bar.sync_window_modes()

    def save_project(self):
        for scene in self._select_scenes("Save Scenes"):
            self._load_scene(scene)
            path = scene.linked_file_path
            if path is None:
                path, _ = QFileDialog.getSaveFileName(
                    self.dm_window,
                    f"Save {scene.name}",
                    f"{scene.name}.dms",
                    "DMScreen Project (*.dms)",
                )
            if not path:
                continue
            save_project(
                path,
                scene.frame,
                scene.layer_manager,
                scene.name,
                self._scene_player_view(scene),
            )
            scene.linked_file_path = Path(path)
            scene.mark_clean()
        self._refresh_scene_tabs()

    def save_as_project(self):
        for scene in self._select_scenes("Save Scenes As"):
            self._load_scene(scene)
            path, _ = QFileDialog.getSaveFileName(
                self.dm_window,
                f"Save {scene.name} As",
                str(scene.linked_file_path or f"{scene.name}.dms"),
                "DMScreen Project (*.dms)",
            )
            if not path:
                continue
            save_project(
                path,
                scene.frame,
                scene.layer_manager,
                scene.name,
                self._scene_player_view(scene),
            )
            scene.linked_file_path = Path(path)
            scene.mark_clean()
        self._refresh_scene_tabs()

    def save_all_projects(self):
        for scene in self.scenes:
            if not self._save_scene(scene):
                break
        self._refresh_scene_tabs()

    @property
    def active_scene(self):
        if 0 <= self.active_scene_index < len(self.scenes):
            return self.scenes[self.active_scene_index]
        return None

    def add_scene(self):
        scene = Scene.create(f"Scene {len(self.scenes) + 1}", self.cache_root)
        scene.layer_manager.replace_layers(DMScreen.default_layers())
        scene.layer_manager.set_player_attached(not self.scenes)
        scene.mark_clean()
        self.scenes.append(scene)
        self.dm_screen.scene_tabs.set_scene_names(
            [item.name for item in self.scenes]
        )
        self._refresh_scene_tabs()
        if self.active_scene_index < 0:
            self.active_scene_index = 0
            self.player_scene_index = 0
            self.layer_manager = scene.layer_manager
            self.dm_screen.set_scene(scene.layer_manager, scene.frame)
            self.dm_screen.set_scene_available(True)
            self.dm_screen.set_player_view_scene(scene)
            self.player_screen.set_layer_manager(scene.layer_manager)
            self.player_screen.sync_frame_settings_from(scene.frame)
            self._restore_player_view(scene)
        else:
            self.select_scene(len(self.scenes) - 1)

    def _cache_scene(self, scene):
        if scene.cache_path is None:
            return False
        try:
            scene.cache_path.parent.mkdir(parents=True, exist_ok=True)
            save_project(
                scene.cache_path,
                scene.frame,
                scene.layer_manager,
                scene.name,
                self._scene_player_view(scene),
            )
            return True
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _remove_scene_cache(scene):
        if scene.cache_path is None:
            return
        try:
            scene.cache_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _clear_scene_cache(self):
        if not self.cache_root.exists():
            return
        for cache_path in self.cache_root.glob("*.dms"):
            try:
                cache_path.unlink()
            except OSError:
                pass

    def _unload_scene(self, scene):
        if scene is None:
            return
        if scene.layer_manager is self.player_screen.layer_manager:
            return
        if self._cache_scene(scene):
            scene.layer_manager.replace_layers([])

    def _load_scene(self, scene):
        if scene.layer_manager.layers:
            return
        if scene.cache_path is None or not scene.cache_path.exists():
            return
        was_dirty = scene.is_dirty
        frame, layers, scene_name, player_view = load_project(
            scene.cache_path,
            include_metadata=True,
        )
        scene.frame.set_size(frame["width"], frame["height"])
        scene.frame.set_background_color(frame["background"])
        scene.layer_manager.replace_layers(layers)
        if scene_name:
            scene.name = scene_name
        self._apply_scene_player_view(scene, player_view)
        if not was_dirty:
            scene.mark_clean()

    def select_scene(self, index: int):
        if index < 0 or index >= len(self.scenes):
            return
        if index == self.active_scene_index:
            return
        old_scene = self.active_scene
        self._unload_scene(old_scene)
        self.active_scene_index = index
        scene = self.active_scene
        self._load_scene(scene)
        self.layer_manager = scene.layer_manager
        if hasattr(self, "menu_bar"):
            self.menu_bar.frame = scene.frame
        self.dm_screen.set_scene(scene.layer_manager, scene.frame)
        self.dm_screen.set_scene_available(True)
        self.dm_screen.set_player_view_scene(scene)
        self.dm_screen.scene_tabs.set_current_index(index)
        self.dm_screen.scene_tabs.set_add_enabled(True)
        self.dm_screen.update_synchronized_tools()
        self._refresh_scene_tabs()

    def _refresh_scene_tabs(self):
        self.dm_screen.scene_tabs.set_scene_labels(
            [
                f"{scene.name}"
                f"{'*' if scene.is_dirty else ''}"
                f"{' [Player]' if index == self.player_scene_index else ''}"
                for index, scene in enumerate(self.scenes)
            ]
        )
        self.dm_screen.scene_tabs.set_add_enabled(True)

    def mark_active_scene_dirty(self):
        if self.active_scene is not None:
            self.active_scene.mark_dirty()

    def rename_scene(self, index):
        if index < 0 or index >= len(self.scenes):
            return
        scene = self.scenes[index]
        name, accepted = QInputDialog.getText(
            self.dm_window,
            "Rename Scene",
            "Scene name:",
            text=scene.name,
        )
        if accepted and name.strip():
            scene.name = name.strip()
            scene.mark_dirty()
            self._refresh_scene_tabs()

    def rename_active_scene(self):
        self.rename_scene(self.active_scene_index)

    def close_scene(self, index):
        if index < 0 or index >= len(self.scenes):
            return
        scene = self.scenes[index]
        if scene.is_dirty:
            choice = QMessageBox.question(
                self.dm_window,
                "Close Scene",
                f"Discard unsaved changes to {scene.name}?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Discard:
                return
        closing_player_scene = self.player_scene_index == index
        if closing_player_scene:
            self._store_player_view()
        if self.player_scene_index > index:
            self.player_scene_index -= 1
        scene.layer_manager.replace_layers([])
        self._remove_scene_cache(scene)
        self.scenes.pop(index)
        if self.active_scene_index > index:
            self.active_scene_index -= 1
        elif self.active_scene_index >= len(self.scenes):
            self.active_scene_index = len(self.scenes) - 1
        if not self.scenes:
            self.player_scene_index = -1
            self.layer_manager = LayerManager()
            self.layer_manager.set_player_attached(False)
            self.dm_screen.set_scene(self.layer_manager, self.dm_screen.frame)
            self.dm_screen.set_scene_available(False)
            self.dm_screen.set_player_view_scene(None)
            self.player_screen.set_layer_manager(self.layer_manager)
            self.dm_screen.scene_tabs.set_scene_names([])
            self._refresh_scene_tabs()
            self._clear_scene_cache()
            return
        if closing_player_scene:
            self.player_scene_index = self.active_scene_index
            self.scenes[self.player_scene_index].layer_manager.set_player_attached(True)
            self.player_screen.set_layer_manager(
                self.scenes[self.player_scene_index].layer_manager
            )
            self.player_screen.sync_frame_settings_from(
                self.scenes[self.player_scene_index].frame
            )
            self._restore_player_view(self.scenes[self.player_scene_index])
        self.layer_manager = self.active_scene.layer_manager
        self.menu_bar.frame = self.active_scene.frame
        self.dm_screen.set_scene(self.active_scene.layer_manager, self.active_scene.frame)
        self.dm_screen.set_scene_available(True)
        self.dm_screen.set_player_view_scene(self.active_scene)
        self.dm_screen.scene_tabs.set_current_index(self.active_scene_index)
        self._refresh_scene_tabs()

    def _select_scenes(self, title):
        dialog = QDialog(self.dm_window)
        dialog.setWindowTitle(title)
        list_widget = QListWidget(dialog)
        for scene in self.scenes:
            item = QListWidgetItem(scene.name, list_widget)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(list_widget)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []
        return [
            scene
            for index, scene in enumerate(self.scenes)
            if list_widget.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _sync_player_frame_if_attached(self):
        if self.active_scene is not None and self.player_scene_index == self.active_scene_index:
            self.player_screen.sync_frame_settings_from(self.active_scene.frame)

    @staticmethod
    def _scene_player_view(scene):
        return {
            "zoom": scene.player_zoom,
            "pan_x": scene.player_pan_x,
            "pan_y": scene.player_pan_y,
        }

    @staticmethod
    def _apply_scene_player_view(scene, player_view):
        scene.player_zoom = max(
            0.1,
            min(PLAYER_ZOOM_MAX, float(player_view.get("zoom", 1.0))),
        )
        scene.player_pan_x = int(player_view.get("pan_x", 0))
        scene.player_pan_y = int(player_view.get("pan_y", 0))

    def _store_player_view(self, *_args):
        if self._restoring_player_view:
            return
        if self.player_scene_index < 0 or self.player_scene_index >= len(self.scenes):
            return
        scene = self.scenes[self.player_scene_index]
        display = self.player_screen.display_widget
        scene.player_zoom = display.zoom
        scene.player_pan_x = display.pan_offset.x()
        scene.player_pan_y = display.pan_offset.y()
        self.dm_screen.update_player_highlight(scene.player_zoom, scene)

    def _pan_pending_player_view(self, delta):
        scene = self.active_scene
        if scene is None or self.player_scene_index == self.active_scene_index:
            return
        scene.player_pan_x += delta.x()
        scene.player_pan_y += delta.y()
        self.dm_screen.update_player_highlight(scene.player_zoom, scene)

    def _zoom_pending_player_view(self, steps):
        scene = self.active_scene
        if scene is None or self.player_scene_index == self.active_scene_index:
            return
        scene.player_zoom = max(
            0.1,
            min(PLAYER_ZOOM_MAX, scene.player_zoom * (1.1 ** steps)),
        )
        self.dm_screen.update_player_highlight(scene.player_zoom, scene)

    def _restore_player_view(self, scene):
        display = self.player_screen.display_widget
        self._restoring_player_view = True
        try:
            display.set_zoom(scene.player_zoom)
            if self.player_controls is not None:
                was_blocked = self.player_controls.player_zoom_spin.blockSignals(
                    True
                )
                self.player_controls.player_zoom_spin.setValue(
                    scene.player_zoom
                )
                self.player_controls.player_zoom_spin.blockSignals(was_blocked)
            display.pan_offset.setX(scene.player_pan_x)
            display.pan_offset.setY(scene.player_pan_y)
            display.update()
            display.view_changed.emit(display.visible_source_rect())
        finally:
            self._restoring_player_view = False

    def bring_player_to_active_scene(self):
        if self.active_scene is None:
            return
        if self.player_scene_index == self.active_scene_index:
            return
        self._store_player_view()
        if self.player_scene_index >= 0:
            self.scenes[self.player_scene_index].layer_manager.set_player_attached(False)
        self.player_scene_index = self.active_scene_index
        scene = self.active_scene
        scene.layer_manager.set_player_attached(True)
        self.player_screen.set_layer_manager(scene.layer_manager)
        self.player_screen.sync_frame_settings_from(scene.frame)
        self._restore_player_view(scene)
        self.dm_screen.update_synchronized_tools()
        self._refresh_scene_tabs()

    def open_project(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self.dm_window,
            "Open DMScreen Project",
            "",
            "DMScreen Project (*.dms)",
        )
        if not paths:
            return
        first_opened_index = len(self.scenes)
        for path in paths:
            scene = Scene.create(Path(path).stem, self.cache_root)
            scene.layer_manager.set_player_attached(False)
            self.scenes.append(scene)
            frame, layers, scene_name, player_view = load_project(
                path,
                include_metadata=True,
            )
            scene.name = scene_name or Path(path).stem
            scene.linked_file_path = Path(path)
            scene.frame.set_size(frame["width"], frame["height"])
            scene.frame.set_background_color(frame["background"])
            scene.layer_manager.replace_layers(layers)
            self._apply_scene_player_view(scene, player_view)
            scene.mark_clean()
        self._refresh_scene_tabs()
        if self.active_scene_index < 0 and self.scenes:
            self.active_scene_index = 0
            self.player_scene_index = 0
            self.scenes[0].layer_manager.set_player_attached(True)
            self.layer_manager = self.scenes[0].layer_manager
            self.dm_screen.set_scene(self.scenes[0].layer_manager, self.scenes[0].frame)
            self.dm_screen.set_scene_available(True)
            self.dm_screen.set_player_view_scene(self.scenes[0])
            self.player_screen.set_layer_manager(self.scenes[0].layer_manager)
            self.player_screen.sync_frame_settings_from(self.scenes[0].frame)
            self._restore_player_view(self.scenes[0])
        elif self.active_scene is not None:
            self.select_scene(first_opened_index)

    def new_project(self):
        self.clear_all_scenes()

    def _scene_needs_save_confirmation(self, scene):
        return scene.is_dirty or scene.linked_file_path is None

    def _confirm_scene_close(self, scene):
        if not self._scene_needs_save_confirmation(scene):
            return True
        choice = QMessageBox.question(
            self.dm_window,
            "Clear All Scenes",
            f"Save changes to {scene.name} before clearing scenes?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self._save_scene(scene)
        return True

    def _save_scene(self, scene):
        self._load_scene(scene)
        path = scene.linked_file_path
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self.dm_window,
                f"Save {scene.name}",
                f"{scene.name}.dms",
                "DMScreen Project (*.dms)",
            )
        if not path:
            return False
        save_project(
            path,
            scene.frame,
            scene.layer_manager,
            scene.name,
            self._scene_player_view(scene),
        )
        scene.linked_file_path = Path(path)
        scene.mark_clean()
        return True

    def clear_all_scenes(self):
        for scene in self.scenes:
            if not self._confirm_scene_close(scene):
                return

        for scene in self.scenes:
            scene.layer_manager.replace_layers([])
            self._remove_scene_cache(scene)

        self.scenes = []
        self.active_scene_index = -1
        self.player_scene_index = -1
        self.layer_manager = LayerManager()
        self.layer_manager.set_player_attached(False)
        self.dm_screen.reset_project_overlays()
        self.dm_screen.set_scene(self.layer_manager, self.dm_screen.frame)
        self.dm_screen.set_scene_available(False)
        self.player_screen.set_layer_manager(self.layer_manager)
        self.dm_screen.update_synchronized_tools()
        self.dm_screen.scene_tabs.set_scene_names([])
        self._refresh_scene_tabs()
        self._clear_scene_cache()

    def show_player_screen(self):
        self.player_handler.show_player()

    def hide_player_screen(self):
        self.player_handler.close_player()