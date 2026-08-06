import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLayout, QMainWindow
from PySide6.QtGui import QColor, QPixmap

from layer_manager import Layer, LayerManager
from layer_ui import LayerModel, LayerPanel
from dm_screen import DMScreen
from layer_media import DrawMedia, GridMedia, MaskMedia
from mouse_action import MouseActionMenu, MouseActionState
from player_handler import PlayerHandler
from player_controls import PlayerControlsPanel
from player_screen import PlayerScreen
from screen import Frame
from scenes import Scene
from side_panel import SidePanel
from zoom_handler import ZoomHandler


class TestLayerModel(unittest.TestCase):
    def test_set_data_ignores_invalid_check_state_values(self):
        manager = LayerManager()
        manager.add(Layer("Layer", MaskMedia(8, 8)))
        model = LayerModel(manager)
        index = model.index(0, LayerModel.VISIBLE)

        self.assertFalse(model.setData(index, None, Qt.CheckStateRole))
        self.assertFalse(model.setData(index, "invalid", Qt.CheckStateRole))
        self.assertTrue(model.setData(index, Qt.Checked, Qt.CheckStateRole))
        self.assertTrue(manager.layers[0].visible)


class TestSidePanel(unittest.TestCase):
    def test_adding_layer_opens_its_editor(self):
        manager = LayerManager()
        panel = LayerPanel(manager, Frame(100, 100))
        edited_layers = []
        updates = []
        manager.subscribe_to_updates(lambda: updates.append(True))
        panel.edit_factory.edit = lambda layer: (
            edited_layers.append(layer) or True
        )
        try:
            panel.add_button.click()
            self.assertEqual(len(edited_layers), 1)
            self.assertIs(edited_layers[0], panel.layer_manager.layers[0])
            self.assertTrue(updates)
        finally:
            panel.deleteLater()
            QApplication.processEvents()

    def test_side_panel_is_a_widget_with_layer_controls(self):
        panel = SidePanel(LayerManager(), Frame(100, 100))
        try:
            self.assertIsInstance(panel.layer_panel, LayerPanel)
            self.assertIsNotNone(panel.table)
            self.assertIsNotNone(panel.add_button)
            self.assertIsNotNone(panel.edit_button)
        finally:
            panel.deleteLater()

    def test_side_panel_hosts_zoom_handler(self):
        zoom_handler = ZoomHandler()
        panel = SidePanel(
            LayerManager(),
            Frame(100, 100),
            zoom_handler=zoom_handler,
        )
        try:
            self.assertIs(panel.zoom_handler, zoom_handler)
            self.assertIs(zoom_handler.parentWidget(), panel)
            self.assertIs(panel.layout().itemAt(1).widget(), zoom_handler)
        finally:
            panel.deleteLater()
            QApplication.processEvents()


class TestPlayerHandler(unittest.TestCase):
    def setUp(self):
        self.window = QMainWindow()
        self.handler = PlayerHandler(self.window)

    def tearDown(self):
        self.handler.deleteLater()
        self.window.close()
        self.window.deleteLater()
        QApplication.processEvents()

    def test_show_and_close_player_window(self):
        self.handler.show_player()
        QApplication.processEvents()
        self.assertTrue(self.window.isVisible())

        self.handler.close_player()
        QApplication.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_handler_buttons_are_connected(self):
        self.handler.show_button.click()
        QApplication.processEvents()
        self.assertTrue(self.window.isVisible())

        self.handler.close_button.click()
        QApplication.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_handler_stacks_buttons_without_expanding_vertically(self):
        self.assertEqual(self.handler.layout().count(), 3)
        self.assertEqual(
            self.handler.layout().sizeConstraint(),
            QLayout.SizeConstraint.SetFixedSize,
        )


class TestScreenZoom(unittest.TestCase):
    def test_default_layers_use_a_grid_media_layer(self):
        layers = DMScreen.default_layers()

        self.assertEqual([layer.name for layer in layers], ["Grid", "Background"])
        self.assertIsInstance(layers[0].media, GridMedia)

    def test_screen_zoom_is_independent_per_screen(self):
        first = PlayerScreen(LayerManager())
        second = PlayerScreen(LayerManager())
        try:
            first.set_zoom(1.5)
            second.set_zoom(0.8)
            self.assertEqual(first.display_widget.zoom, 1.5)
            self.assertEqual(second.display_widget.zoom, 0.8)
        finally:
            first.close()
            second.close()
            QApplication.processEvents()

    def test_zoom_handler_controls_dm_zoom_and_reset(self):
        handler = ZoomHandler()
        dm_values = []
        handler.dm_zoom_changed.connect(dm_values.append)
        handler.dm_zoom_spin.setValue(1.5)
        self.assertEqual(dm_values, [1.5])
        handler.reset()
        self.assertEqual(handler.dm_zoom_spin.value(), 1.0)
        handler.deleteLater()

    def test_dm_highlight_matches_player_viewport_aspect_ratio(self):
        layer_manager = LayerManager()
        player_screen = PlayerScreen(layer_manager)
        dm_screen = DMScreen(layer_manager, player_screen=player_screen)
        try:
            player_screen.display_widget.resize(800, 600)
            player_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            player_screen.display_widget.set_zoom(2.0)
            dm_screen.update_player_highlight(2.0)
            highlight = dm_screen.display_widget.highlight_rect
            expected = player_screen.display_widget.visible_source_rect()

            for actual, expected_value in zip(highlight, expected):
                self.assertAlmostEqual(actual, expected_value)
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()

    def test_dm_only_player_view_uses_player_pan_units(self):
        dm_manager = LayerManager()
        player_manager = LayerManager()
        player_screen = PlayerScreen(player_manager)
        dm_screen = DMScreen(dm_manager, player_screen=player_screen)
        scene = Scene("Active", dm_manager, Frame(1920, 1080))
        try:
            dm_screen.display_widget.resize(1000, 700)
            player_screen.display_widget.resize(800, 600)
            dm_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            player_screen.display_widget.set_source_pixmap(
                QPixmap(1920, 1080)
            )
            dm_screen.display_widget.set_zoom(1.5)
            scene.player_zoom = 2.0
            scene.player_pan_x = 80
            scene.player_pan_y = -30
            dm_screen.set_player_view_scene(scene)

            expected = dm_screen.display_widget.visible_source_rect_for(
                scene.player_zoom,
                QPoint(scene.player_pan_x, scene.player_pan_y),
                player_screen.display_widget.size(),
            )
            for actual, expected_value in zip(
                dm_screen.display_widget.highlight_rect,
                expected,
            ):
                self.assertAlmostEqual(actual, expected_value)

            pending = []
            dm_screen.pending_player_pan.connect(pending.append)
            dm_screen._pan_player(QPoint(20, 10))
            dm_pixmap = dm_screen.display_widget.pixmap()
            player_size = dm_screen._scene_display_size(
                scene,
                player_screen.display_widget.size(),
            )
            self.assertEqual(
                pending[-1],
                QPoint(
                    round(20 * player_size[0] / dm_pixmap.width()),
                    round(10 * player_size[1] / dm_pixmap.height()),
                ),
            )
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()

    def test_mouse_action_menu_belongs_only_to_dm_screen(self):
        screen = PlayerScreen(LayerManager())
        try:
            self.assertIsNone(screen.mouse_action_menu)
        finally:
            screen.close()
            QApplication.processEvents()

    def test_dm_menu_can_select_player_pan_state(self):
        dm_screen = DMScreen(LayerManager())
        try:
            self.assertIs(
                dm_screen.mouse_action_menu.parentWidget(),
                dm_screen,
            )
            self.assertIs(
                dm_screen.layout.itemAt(0).widget(),
                dm_screen.scene_tabs,
            )
            self.assertIs(
                dm_screen.layout.itemAt(1).widget(),
                dm_screen.mouse_action_menu,
            )
            self.assertLessEqual(dm_screen.mouse_action_menu.height(), 32)
            self.assertEqual(
                dm_screen.layout.itemAt(1).alignment(),
                Qt.AlignmentFlag.AlignHCenter,
            )
            dm_screen.mouse_action_menu.player_pan_button.click()
            self.assertEqual(
                dm_screen.mouse_action_menu.state,
                MouseActionState.PLAYER_PAN,
            )
            self.assertEqual(
                dm_screen.display_widget.mouse_action_state,
                MouseActionState.PLAYER_PAN,
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_dm_menu_can_select_ping_state(self):
        dm_screen = DMScreen(LayerManager())
        try:
            dm_screen.mouse_action_menu.ping_button.click()
            self.assertEqual(
                dm_screen.mouse_action_menu.state,
                MouseActionState.PING,
            )
            self.assertEqual(
                dm_screen.display_widget.mouse_action_state,
                MouseActionState.PING,
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_dm_menu_can_select_ruler_state(self):
        dm_screen = DMScreen(LayerManager())
        try:
            dm_screen.mouse_action_menu.ruler_button.click()
            self.assertEqual(
                dm_screen.mouse_action_menu.state,
                MouseActionState.RULER,
            )
            self.assertEqual(
                dm_screen.display_widget.mouse_action_state,
                MouseActionState.RULER,
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_shape_menu_exposes_cone_mode(self):
        dm_screen = DMScreen(LayerManager())
        try:
            self.assertEqual(
                [
                    dm_screen.mouse_action_menu.shape_select.itemText(index)
                    for index in range(dm_screen.mouse_action_menu.shape_select.count())
                ],
                ["Cone", "Line", "Circle", "Square"],
            )
            dm_screen.mouse_action_menu.shape_button.click()
            self.assertEqual(
                dm_screen.mouse_action_menu.state,
                MouseActionState.SHAPE,
            )
            self.assertEqual(
                dm_screen.mouse_action_menu.shape_select.currentText(),
                "Cone",
            )
            self.assertFalse(dm_screen.mouse_action_menu.shape_select.isHidden())
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_shape_menu_enables_circle_mode(self):
        dm_screen = DMScreen(LayerManager())
        try:
            circle_index = dm_screen.mouse_action_menu.shape_select.findText("Circle")
            self.assertTrue(
                dm_screen.mouse_action_menu.shape_select.model().item(circle_index).isEnabled()
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_cone_highlights_intersecting_grid_cells(self):
        manager = LayerManager()
        manager.add(Layer("Grid", GridMedia(1920, 1080)))
        dm_screen = DMScreen(manager)
        try:
            dm_screen.display_widget.resize(800, 600)
            dm_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            dm_screen.mouse_action_menu.shape_button.click()
            dm_screen._shape_changed(QPoint(100, 100), QPoint(300, 100))
            self.assertEqual(len(dm_screen.display_widget._shape_polygon), 3)
            self.assertAlmostEqual(
                dm_screen.display_widget._shape_polygon[0][0],
                300 / 1919,
            )
            self.assertGreater(len(dm_screen.display_widget._shape_cells), 0)
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_cone_polygon_has_original_opening(self):
        start = (100.0, 100.0)
        end = (200.0, 100.0)
        polygon = DMScreen._cone_polygon(start, end)
        self.assertEqual(polygon[1], (200.0, 150.0))
        self.assertEqual(polygon[2], (200.0, 50.0))

    def test_shape_cell_threshold_excludes_small_overlap(self):
        overlap = DMScreen._polygon_intersection_area(
            [(0.0, 0.0), (20.0, 0.0), (0.0, 20.0)],
            (0.0, 0.0, 100.0, 100.0),
        )
        self.assertAlmostEqual(overlap, 200.0)
        self.assertLess(overlap, 100.0 * 100.0 * 0.05)

    def test_circle_uses_press_as_center_and_release_as_radius(self):
        polygon = DMScreen._circle_polygon((100.0, 100.0), (130.0, 100.0))
        self.assertEqual(len(polygon), 64)
        self.assertAlmostEqual(polygon[0][0], 130.0)
        self.assertAlmostEqual(polygon[0][1], 100.0)
        self.assertAlmostEqual(polygon[16][0], 100.0)
        self.assertAlmostEqual(polygon[16][1], 130.0)

    def test_circle_center_snaps_to_grid_cell_center(self):
        grid = GridMedia(1920, 1080)
        grid.set_parameters(100, 100, 10, 20, 2, QColor("white"))
        snapped = DMScreen._snap_to_grid((58, 141), grid)
        self.assertEqual(snapped, (60.0, 170.0))
        grid.stop()

    def test_shape_menu_enables_square_mode(self):
        dm_screen = DMScreen(LayerManager())
        try:
            square_index = dm_screen.mouse_action_menu.shape_select.findText("Square")
            self.assertTrue(
                dm_screen.mouse_action_menu.shape_select.model().item(square_index).isEnabled()
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_shape_menu_enables_line_mode(self):
        dm_screen = DMScreen(LayerManager())
        try:
            line_index = dm_screen.mouse_action_menu.shape_select.findText("Line")
            self.assertTrue(
                dm_screen.mouse_action_menu.shape_select.model().item(line_index).isEnabled()
            )
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_square_uses_opposite_drag_corners(self):
        polygon = DMScreen._square_polygon((200.0, 300.0), (100.0, 100.0))
        self.assertEqual(
            polygon,
            [(100.0, 100.0), (200.0, 100.0), (200.0, 300.0), (100.0, 300.0)],
        )

    def test_line_intersection_highlights_crossed_cell(self):
        self.assertTrue(
            DMScreen._line_intersects_rect(
                (-10.0, 50.0), (110.0, 50.0), 0.0, 0.0, 100.0, 100.0
            )
        )
        self.assertFalse(
            DMScreen._line_intersects_rect(
                (-10.0, 110.0), (110.0, 110.0), 0.0, 0.0, 100.0, 100.0
            )
        )
        self.assertEqual(
            DMScreen._line_length_in_rect(
                (-10.0, -10.0), (110.0, 110.0), 0.0, 100.0, 100.0, 200.0
            ),
            0.0,
        )

    def test_shape_rebuilds_when_frame_size_changes(self):
        dm_screen = DMScreen(LayerManager())
        try:
            dm_screen.display_widget.resize(800, 600)
            dm_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            dm_screen.mouse_action_menu.shape_button.click()
            dm_screen.mouse_action_menu.shape_select.setCurrentText("Circle")
            dm_screen._shape_changed(QPoint(100, 100), QPoint(200, 100))
            original = dm_screen.display_widget._shape_polygon
            dm_screen.frame.set_size(800, 600)
            dm_screen.sync_frame_settings()
            resized = dm_screen.display_widget._shape_polygon
            self.assertIsNot(original, resized)
            self.assertEqual(len(resized), len(original))
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_ruler_snaps_endpoints_to_grid_cell_centers(self):
        grid = GridMedia(1920, 1080)
        grid.set_parameters(100, 100, 10, 20, 2, QColor("white"))
        snapped = DMScreen._snap_to_grid((58, 141), grid)
        self.assertEqual(snapped, (60.0, 170.0))
        grid.stop()

    def test_switching_tools_clears_ruler_overlay(self):
        dm_screen = DMScreen(LayerManager())
        try:
            dm_screen.mouse_action_menu.ruler_button.click()
            dm_screen.display_widget.set_ruler((0.2, 0.2), (0.8, 0.8), 3, "cells")
            self.assertIsNotNone(
                dm_screen.display_widget._ruler_start_position
            )
            dm_screen.mouse_action_menu.pan_button.click()
            self.assertIsNone(dm_screen.display_widget._ruler_start_position)
            self.assertIsNone(dm_screen.display_widget._ruler_end_position)
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_ping_is_shared_between_dm_and_player_displays(self):
        layer_manager = LayerManager()
        player_screen = PlayerScreen(layer_manager)
        dm_screen = DMScreen(layer_manager, player_screen=player_screen)
        try:
            dm_screen.display_widget.resize(800, 600)
            player_screen.display_widget.resize(800, 600)
            pixmap = QPixmap(1920, 1080)
            dm_screen.display_widget.set_source_pixmap(pixmap)
            player_screen.display_widget.set_source_pixmap(pixmap)
            dm_screen._ping_at(dm_screen.display_widget._display_rect().center())
            self.assertEqual(
                dm_screen.display_widget._ping_position,
                player_screen.display_widget._ping_position,
            )
            self.assertIsNotNone(dm_screen.display_widget._ping_started)
            self.assertIsNotNone(player_screen.display_widget._ping_started)
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()

    def test_performance_panel_can_be_resized(self):
        dm_screen = DMScreen(LayerManager())
        try:
            self.assertIs(
                dm_screen.content_splitter.widget(1),
                dm_screen.debug_panel,
            )
            self.assertGreaterEqual(dm_screen.debug_panel.minimumHeight(), 32)
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_mask_tools_are_available_as_a_mouse_state(self):
        menu = MouseActionMenu()
        try:
            menu.add_mask_option()
            menu.set_mask_available(True)
            menu.mask_erase_button.click()
            menu.mask_brush_size.setValue(32)
            self.assertEqual(menu.state, MouseActionState.MASK)
            self.assertTrue(menu.mask_erase)
            self.assertEqual(menu.mask_brush_size.value(), 32)
            menu.mask_fill_add_button.click()
            self.assertEqual(menu.state, MouseActionState.MASK_FILL_ADD)
            menu.mask_fill_remove_button.click()
            self.assertEqual(menu.state, MouseActionState.MASK_FILL_REMOVE)
        finally:
            menu.deleteLater()
            QApplication.processEvents()

    def test_dm_mask_stroke_paints_selected_mask_layer(self):
        manager = LayerManager()
        mask = MaskMedia(1920, 1080)
        manager.add(Layer("Mask", mask))
        dm_screen = DMScreen(manager)
        try:
            display = dm_screen.display_widget
            display.resize(400, 300)
            display.set_source_pixmap(QPixmap(100, 100))
            dm_screen.side_panel.table.selectRow(0)
            dm_screen.mouse_action_menu.mask_button.click()
            dm_screen.mouse_action_menu.mask_brush_size.setValue(40)
            display.mask_stroke.emit(display.rect().center())
            self.assertGreater(mask.current_frame().pixelColor(960, 540).alpha(), 0)
            self.assertIs(dm_screen.side_panel.table.selected_layer(), manager.layers[0])
            self.assertEqual(display._mask_brush_size, 40)
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_dm_mask_stroke_paints_selected_draw_layer(self):
        manager = LayerManager()
        draw = DrawMedia(1920, 1080)
        manager.add(Layer("Draw", draw))
        dm_screen = DMScreen(manager)
        try:
            display = dm_screen.display_widget
            display.resize(400, 300)
            display.set_source_pixmap(QPixmap(100, 100))
            dm_screen.side_panel.table.selectRow(0)
            dm_screen.mouse_action_menu.mask_button.click()
            dm_screen.mouse_action_menu.mask_brush_size.setValue(40)
            display.mask_stroke.emit(display.rect().center())
            self.assertGreater(draw.current_frame().pixelColor(960, 540).alpha(), 0)
        finally:
            dm_screen.close()
            QApplication.processEvents()

    def test_pan_offset_changes_visible_source_rect(self):
        screen = PlayerScreen(LayerManager())
        try:
            display = screen.display_widget
            display.resize(800, 600)
            display.set_source_pixmap(QPixmap(1920, 1080))
            display.set_zoom(2.0)
            centered = display.visible_source_rect()
            display.set_mouse_action_state(MouseActionState.PAN)
            display.pan_offset.setX(-100)
            display._clamp_pan()
            panned = display.visible_source_rect()
            self.assertGreater(panned[0], centered[0])
            self.assertEqual(panned[2], centered[2])
        finally:
            screen.close()
            QApplication.processEvents()

    def test_dragging_dm_player_highlight_routes_to_player_display(self):
        layer_manager = LayerManager()
        player_screen = PlayerScreen(layer_manager)
        dm_screen = DMScreen(layer_manager, player_screen=player_screen)
        try:
            player_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            player_screen.display_widget.resize(800, 600)
            player_screen.display_widget.set_zoom(2.0)
            dm_screen.set_player_viewport_rect(
                player_screen.display_widget.visible_source_rect()
            )
            dm_screen.mouse_action_menu.player_pan_button.click()
            before = QPoint(player_screen.display_widget.pan_offset)
            dm_screen.display_widget.highlight_pan_delta.emit(QPoint(-20, 0))
            self.assertNotEqual(
                player_screen.display_widget.pan_offset,
                before,
            )
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()

    def test_dm_pan_state_takes_priority_over_player_rectangle(self):
        layer_manager = LayerManager()
        player_screen = PlayerScreen(layer_manager)
        dm_screen = DMScreen(layer_manager, player_screen=player_screen)
        try:
            player_screen.display_widget.set_source_pixmap(QPixmap(1920, 1080))
            player_screen.display_widget.resize(800, 600)
            player_screen.display_widget.set_zoom(2.0)
            dm_screen.set_player_viewport_rect(
                player_screen.display_widget.visible_source_rect()
            )
            dm_screen.mouse_action_menu.pan_button.click()
            before_player = QPoint(player_screen.display_widget.pan_offset)
            dm_screen.display_widget.pan_delta.emit(QPoint(20, 0))
            self.assertEqual(
                player_screen.display_widget.pan_offset,
                before_player,
            )
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()

    def test_player_controls_include_window_actions_and_player_reset(self):
        window = QMainWindow()
        handler = PlayerHandler(window)
        controls = PlayerControlsPanel(handler)
        try:
            values = []
            controls.player_zoom_changed.connect(values.append)
            controls.player_zoom_spin.setValue(2.0)
            self.assertEqual(values, [2.0])
            controls.reset_player_zoom()
            self.assertEqual(controls.player_zoom_spin.value(), 1.0)
            self.assertIs(controls.player_handler, handler)
        finally:
            controls.deleteLater()
            window.close()
            window.deleteLater()
            QApplication.processEvents()

    def test_player_frame_mirrors_dm_frame_settings(self):
        dm_screen = PlayerScreen(LayerManager())
        player_screen = PlayerScreen(LayerManager())
        try:
            dm_screen.frame.set_size(800, 600)
            dm_screen.frame.set_background_color(QColor("#203040"))
            player_screen.sync_frame_settings_from(dm_screen.frame)
            self.assertEqual(player_screen.frame.size.width(), 800)
            self.assertEqual(player_screen.frame.size.height(), 600)
            self.assertEqual(
                player_screen.frame.background_color,
                QColor("#203040"),
            )
        finally:
            dm_screen.close()
            player_screen.close()
            QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
