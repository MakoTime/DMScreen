from pathlib import Path
from math import ceil, floor, hypot, cos, pi, sin

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtCore import QThread, QTimer, Qt
from layer_manager import Layer
from layer_media import DrawMedia
from layer_media import ImageMedia
from layer_media import MaskMedia
from layer_media import GridMedia
from mouse_action import MouseActionState
from player_controls import PlayerControlsPanel
from PySide6.QtWidgets import QSplitter
from screen import Screen
from side_panel import SidePanel
from zoom_handler import ZoomHandler
from ui.views.performance_panel import PerformancePanel


class DMScreen(Screen):
    render_thread_priority = QThread.Priority.LowPriority

    def __init__(
        self,
        layer_manager,
        player_controls: PlayerControlsPanel | None = None,
        zoom_handler: ZoomHandler | None = None,
        player_screen=None,
        parent=None,
    ):
        self.player_controls = player_controls
        self.zoom_handler = zoom_handler
        self.player_screen = player_screen
        self._mask_last_point = None
        self._shape_definition = None
        super().__init__(layer_manager, parent)

    def build_ui(self):
        self.mouse_action_menu.add_player_pan_option()
        self.mouse_action_menu.add_mask_option()
        self.mouse_action_menu.setParent(self)
        self.mouse_action_menu.adjustSize()
        self.layout.insertWidget(
            0,
            self.mouse_action_menu,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        if self.player_screen is not None:
            self.display_widget.highlight_pan_delta.connect(
                self._pan_player_from_dm
            )
            self.display_widget.pan_delta.connect(
                self._pan_player_from_player_pan_state
            )
            self.display_widget.wheel_zoom_delta.connect(
                self._zoom_player_by
            )
        self.display_widget.mask_stroke.connect(self._paint_mask)
        self.display_widget.mask_stroke_finished.connect(
            self._finish_mask_stroke
        )
        self.display_widget.ping_requested.connect(self._ping_at)
        self.display_widget.ruler_changed.connect(self._ruler_changed)
        self.display_widget.shape_changed.connect(self._shape_changed)
        self.mouse_action_menu.state_changed.connect(
            self._mouse_action_changed
        )
        self.mouse_action_menu.mask_brush_size.valueChanged.connect(
            self.display_widget.set_mask_brush_size
        )
        self.display_widget.set_mask_brush_size(
            self.mouse_action_menu.mask_brush_size.value()
        )
        self.display_widget.set_mask_frame_size(self.frame.size)
        self.initialise_splitter()
        self.debug_panel = PerformancePanel(self)
        self._debug_timer = QTimer(self)
        self._debug_timer.setInterval(5000)
        self._debug_timer.timeout.connect(self._refresh_debug_stats)
        self._debug_timer.start()
        self.initialise_side_panel()
        self.side_panel.table.selectionModel().selectionChanged.connect(
            self._selected_layer_changed
        )
        self._selected_layer_changed()

    def _pan_player_from_dm(self, delta):
        self._pan_player(delta)

    def _pan_player_from_player_pan_state(self, delta):
        if self.display_widget.mouse_action_state is not MouseActionState.PLAYER_PAN:
            return
        self._pan_player(delta)

    def _pan_player(self, delta):
        player_display = self.player_screen.display_widget
        dm_pixmap = self.display_widget.pixmap()
        player_pixmap = player_display.pixmap()
        if dm_pixmap is None or player_pixmap is None:
            return
        scale_x = player_pixmap.width() / max(1, dm_pixmap.width())
        scale_y = player_pixmap.height() / max(1, dm_pixmap.height())
        player_display.pan_by(
            QPoint(round(delta.x() * scale_x), round(delta.y() * scale_y))
        )

    def _zoom_player_by(self, steps):
        player_display = self.player_screen.display_widget
        player_display.set_zoom(player_display.zoom * (1.1 ** steps))
        player_display.zoom_changed.emit(player_display.zoom)

    def _selected_layer_changed(self, *args):
        layer = self.side_panel.table.selected_layer()
        self.mouse_action_menu.set_mask_available(
            layer is not None
            and isinstance(layer.media, (DrawMedia, MaskMedia))
        )

    def _paint_mask(self, point):
        layer = self.side_panel.table.selected_layer()
        if layer is None or not isinstance(layer.media, (DrawMedia, MaskMedia)):
            return
        display_rect = self.display_widget._display_rect()
        if display_rect.isEmpty() or not display_rect.contains(point):
            return
        frame_size = self.frame.size
        x = (point.x() - display_rect.left()) * frame_size.width() / display_rect.width()
        y = (point.y() - display_rect.top()) * frame_size.height() / display_rect.height()
        current_point = QPoint(round(x), round(y))
        if isinstance(layer.media, MaskMedia) and self.display_widget.mouse_action_state in (
            MouseActionState.MASK_FILL_ADD,
            MouseActionState.MASK_FILL_REMOVE,
        ):
            if self._mask_last_point is None:
                layer.media.flood_fill(
                    current_point.x(),
                    current_point.y(),
                    self.display_widget.mouse_action_state
                    is MouseActionState.MASK_FILL_REMOVE,
                )
            self._mask_last_point = current_point
            return
        brush_size = self.mouse_action_menu.mask_brush_size.value()
        erase = self.mouse_action_menu.mask_erase
        if self._mask_last_point is None:
            layer.media.paint_at(
                current_point.x(), current_point.y(), brush_size, erase
            )
        else:
            layer.media.paint_line(
                self._mask_last_point.x(),
                self._mask_last_point.y(),
                current_point.x(),
                current_point.y(),
                brush_size,
                erase,
            )
        self._mask_last_point = current_point

    def _finish_mask_stroke(self):
        self._mask_last_point = None

    def _ping_at(self, point):
        display_rect = self.display_widget._display_rect()
        if display_rect.isEmpty() or not display_rect.contains(point):
            return
        position = (
            (point.x() - display_rect.left()) / display_rect.width(),
            (point.y() - display_rect.top()) / display_rect.height(),
        )
        self.display_widget.set_ping_position(position)
        if self.player_screen is not None:
            self.player_screen.display_widget.set_ping_position(position)

    def _ruler_changed(self, start, end):
        display_rect = self.display_widget._display_rect()
        if display_rect.isEmpty():
            return
        start_frame = self._display_point_to_frame(start, display_rect)
        end_frame = self._display_point_to_frame(end, display_rect)
        grid = next(
            (
                layer.media
                for layer in self.layer_manager.layers
                if isinstance(layer.media, GridMedia)
            ),
            None,
        )
        if grid is not None:
            start_frame = self._snap_to_grid(start_frame, grid)
            end_frame = self._snap_to_grid(end_frame, grid)
            distance = max(
                abs(end_frame[0] - start_frame[0]) / grid.spacing_x,
                abs(end_frame[1] - start_frame[1]) / grid.spacing_y,
            )
            unit = "cells"
        else:
            distance = hypot(
                end_frame[0] - start_frame[0], end_frame[1] - start_frame[1]
            )
            unit = "px"
        start_position = self._frame_point_to_normalized(start_frame)
        end_position = self._frame_point_to_normalized(end_frame)
        self.display_widget.set_ruler(
            start_position, end_position, distance, unit
        )
        if self.player_screen is not None:
            self.player_screen.display_widget.set_ruler(
                start_position, end_position, distance, unit
            )

    def _mouse_action_changed(self, state):
        if state is not MouseActionState.RULER:
            self.display_widget.clear_ruler()
            if self.player_screen is not None:
                self.player_screen.display_widget.clear_ruler()
        if state is not MouseActionState.SHAPE:
            self._shape_definition = None
            self.display_widget.clear_shape()
            if self.player_screen is not None:
                self.player_screen.display_widget.clear_shape()

    def _shape_changed(self, start, end):
        shape = self.mouse_action_menu.shape_select.currentText()
        if shape not in ("Cone", "Line", "Circle", "Square"):
            return
        display_rect = self.display_widget._display_rect()
        if display_rect.isEmpty():
            return
        start_frame = self._display_point_to_frame(start, display_rect)
        end_frame = self._display_point_to_frame(end, display_rect)
        self._shape_definition = (
            shape,
            self._frame_point_to_normalized(start_frame),
            self._frame_point_to_normalized(end_frame),
        )
        self._update_shape_overlay()

    def _update_shape_overlay(self):
        if self._shape_definition is None:
            return
        shape, start_position, end_position = self._shape_definition
        start_frame = self._normalized_point_to_frame(start_position)
        end_frame = self._normalized_point_to_frame(end_position)
        grid = next(
            (
                layer.media
                for layer in self.layer_manager.layers
                if isinstance(layer.media, GridMedia)
            ),
            None,
        )
        if grid is not None:
            if shape in ("Cone", "Line"):
                end_frame = self._snap_to_grid(end_frame, grid)
                start_frame = self._snap_to_grid(start_frame, grid)
                if shape == "Cone":
                    start_frame = self._offset_cone_start(start_frame, end_frame, grid)
            elif shape == "Circle":
                start_frame = self._snap_to_grid(start_frame, grid)
            else:
                start_frame = self._snap_to_grid(start_frame, grid)
                end_frame = self._snap_to_grid(end_frame, grid)
        polygon = (
            self._cone_polygon(start_frame, end_frame)
            if shape == "Cone"
            else (
                self._circle_polygon(start_frame, end_frame)
                if shape == "Circle"
                else (
                    self._square_polygon(start_frame, end_frame)
                    if shape == "Square"
                    else [start_frame, end_frame]
                )
            )
        )
        cells = (
            self._line_cells(start_frame, end_frame, grid)
            if shape == "Line"
            else self._cone_cells(polygon, grid)
        )
        normalized_polygon = [
            self._frame_point_to_normalized(point) for point in polygon
        ]
        normalized_cells = [
            (
                x / self.frame.size.width(),
                y / self.frame.size.height(),
                width / self.frame.size.width(),
                height / self.frame.size.height(),
            )
            for x, y, width, height in cells
        ]
        self.display_widget.set_shape(normalized_polygon, normalized_cells)
        if self.player_screen is not None:
            self.player_screen.display_widget.set_shape(
                normalized_polygon, normalized_cells
            )

    @staticmethod
    def _cone_polygon(start, end):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = hypot(dx, dy)
        if length < 1.0:
            return [start, end, end]
        perpendicular = (-dy / length, dx / length)
        half_width = length / 2.0
        return [
            start,
            (
                end[0] + perpendicular[0] * half_width,
                end[1] + perpendicular[1] * half_width,
            ),
            (
                end[0] - perpendicular[0] * half_width,
                end[1] - perpendicular[1] * half_width,
            ),
        ]

    @staticmethod
    def _circle_polygon(center, edge, segments=64):
        radius = hypot(edge[0] - center[0], edge[1] - center[1])
        return [
            (
                center[0] + radius * cos(2 * pi * index / segments),
                center[1] + radius * sin(2 * pi * index / segments),
            )
            for index in range(segments)
        ]

    @staticmethod
    def _square_polygon(first_corner, opposite_corner):
        left = min(first_corner[0], opposite_corner[0])
        right = max(first_corner[0], opposite_corner[0])
        top = min(first_corner[1], opposite_corner[1])
        bottom = max(first_corner[1], opposite_corner[1])
        return [
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        ]

    @staticmethod
    def _offset_cone_start(start, end, grid):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = hypot(dx, dy)
        if length < 1.0:
            return start
        offset = grid.spacing_x / 2.0
        scale = offset / length
        return (
            start[0] + dx * scale,
            start[1] + dy * scale,
        )

    def _cone_cells(self, polygon, grid):
        if grid is None:
            return []
        start_x = floor((0 - grid.offset_x) / grid.spacing_x) - 1
        end_x = ceil((self.frame.size.width() - grid.offset_x) / grid.spacing_x) + 1
        start_y = floor((0 - grid.offset_y) / grid.spacing_y) - 1
        end_y = ceil((self.frame.size.height() - grid.offset_y) / grid.spacing_y) + 1
        cells = []
        for column in range(start_x, end_x):
            x = grid.offset_x + column * grid.spacing_x
            for row in range(start_y, end_y):
                y = grid.offset_y + row * grid.spacing_y
                left = max(0.0, x)
                top = max(0.0, y)
                right = min(float(self.frame.size.width()), x + grid.spacing_x)
                bottom = min(float(self.frame.size.height()), y + grid.spacing_y)
                if right <= left or bottom <= top:
                    continue
                intersection_area = self._polygon_intersection_area(
                    polygon, (left, top, right, bottom)
                )
                if intersection_area >= (right - left) * (bottom - top) * 0.05:
                    cells.append((left, top, right - left, bottom - top))
        return cells

    def _line_cells(self, start, end, grid):
        if grid is None:
            return []
        start_x = floor((0 - grid.offset_x) / grid.spacing_x) - 1
        end_x = ceil((self.frame.size.width() - grid.offset_x) / grid.spacing_x) + 1
        start_y = floor((0 - grid.offset_y) / grid.spacing_y) - 1
        end_y = ceil((self.frame.size.height() - grid.offset_y) / grid.spacing_y) + 1
        cells = []
        for column in range(start_x, end_x):
            x = grid.offset_x + column * grid.spacing_x
            for row in range(start_y, end_y):
                y = grid.offset_y + row * grid.spacing_y
                left = max(0.0, x)
                top = max(0.0, y)
                right = min(float(self.frame.size.width()), x + grid.spacing_x)
                bottom = min(float(self.frame.size.height()), y + grid.spacing_y)
                if right <= left or bottom <= top:
                    continue
                segment_length = self._line_length_in_rect(
                    start, end, left, top, right, bottom
                )
                if segment_length >= hypot(right - left, bottom - top) * 0.1:
                    cells.append((left, top, right - left, bottom - top))
        return cells

    @staticmethod
    def _line_intersects_rect(start, end, left, top, right, bottom):
        return DMScreen._line_length_in_rect(
            start, end, left, top, right, bottom
        ) > 0.0

    @staticmethod
    def _line_length_in_rect(start, end, left, top, right, bottom):
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        lower, upper = 0.0, 1.0
        for position, direction, minimum, maximum in (
            (start[0], delta_x, left, right),
            (start[1], delta_y, top, bottom),
        ):
            if abs(direction) < 1e-9:
                if position < minimum or position > maximum:
                    return 0.0
                continue
            entering = (minimum - position) / direction
            exiting = (maximum - position) / direction
            if entering > exiting:
                entering, exiting = exiting, entering
            lower = max(lower, entering)
            upper = min(upper, exiting)
            if lower > upper:
                return 0.0
        return hypot(delta_x, delta_y) * max(0.0, upper - lower)

    @staticmethod
    def _polygon_intersection_area(polygon, rect):
        left, top, right, bottom = rect
        clipped = list(polygon)
        boundaries = (
            (lambda point: point[0] >= left, lambda start, end: (
                left,
                start[1] + (end[1] - start[1]) * (left - start[0])
                / (end[0] - start[0]),
            )),
            (lambda point: point[0] <= right, lambda start, end: (
                right,
                start[1] + (end[1] - start[1]) * (right - start[0])
                / (end[0] - start[0]),
            )),
            (lambda point: point[1] >= top, lambda start, end: (
                start[0] + (end[0] - start[0]) * (top - start[1])
                / (end[1] - start[1]),
                top,
            )),
            (lambda point: point[1] <= bottom, lambda start, end: (
                start[0] + (end[0] - start[0]) * (bottom - start[1])
                / (end[1] - start[1]),
                bottom,
            )),
        )
        for inside, intersection in boundaries:
            if not clipped:
                return 0.0
            output = []
            previous = clipped[-1]
            for current in clipped:
                previous_inside = inside(previous)
                current_inside = inside(current)
                if current_inside != previous_inside:
                    output.append(intersection(previous, current))
                if current_inside:
                    output.append(current)
                previous = current
            clipped = output
        if len(clipped) < 3:
            return 0.0
        return abs(
            sum(
                clipped[index][0] * clipped[(index + 1) % len(clipped)][1]
                - clipped[(index + 1) % len(clipped)][0] * clipped[index][1]
                for index in range(len(clipped))
            )
            / 2.0
        )

    def _display_point_to_frame(self, point, display_rect):
        x = (point.x() - display_rect.left()) / display_rect.width()
        y = (point.y() - display_rect.top()) / display_rect.height()
        return (
            max(0.0, min(1.0, x)) * max(0, self.frame.size.width() - 1),
            max(0.0, min(1.0, y)) * max(0, self.frame.size.height() - 1),
        )

    def _frame_point_to_normalized(self, point):
        return (
            point[0] / max(1, self.frame.size.width() - 1),
            point[1] / max(1, self.frame.size.height() - 1),
        )

    def _normalized_point_to_frame(self, point):
        return (
            point[0] * max(0, self.frame.size.width() - 1),
            point[1] * max(0, self.frame.size.height() - 1),
        )

    @staticmethod
    def _snap_to_grid(point, grid):
        return (
            max(
                0.0,
                min(
                    grid.width - 1,
                    grid.offset_x
                    + (round((point[0] - grid.offset_x) / grid.spacing_x - 0.5) + 0.5)
                    * grid.spacing_x,
                ),
            ),
            max(
                0.0,
                min(
                    grid.height - 1,
                    grid.offset_y
                    + (round((point[1] - grid.offset_y) / grid.spacing_y - 0.5) + 0.5)
                    * grid.spacing_y,
                ),
            ),
        )

    def initialise_splitter(self):
        self.splitter = QSplitter()
        # self.splitter.addWidget(self.side_panel)
        # self.splitter.addWidget(self.display_widget)

        # self.splitter.setStretchFactor(0, 0)
        # self.splitter.setStretchFactor(1, 1)

    def initialise_side_panel(self):
        self.side_panel = SidePanel(
            self.layer_manager,
            self.frame,
            frame_changed_callback=self.sync_frame_settings,
            zoom_handler=self.zoom_handler,
        )

        self.splitter.addWidget(self.side_panel)
        self.splitter.addWidget(self.display_widget)
        if self.player_controls is not None:
            self.splitter.addWidget(self.player_controls)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        if self.player_controls is not None:
            self.splitter.setStretchFactor(2, 0)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.addWidget(self.splitter)
        self.content_splitter.addWidget(self.debug_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([self.height(), 32])
        self.layout.addWidget(self.content_splitter)

        self.create_default_layers()
        self.update_player_highlight(1.0)

    def create_default_layers(self):
        background_image = QImage(
            str(Path(__file__).resolve().parents[2] / "Obyrith Dungeon Dark.png")
        )
        self.side_panel.add_layer(
            Layer("Background", ImageMedia(background_image))
        )
        self.side_panel.add_layer(Layer("Grid"))
        self.side_panel.add_layer(Layer("Tokens"))
        self.side_panel.add_layer(Layer("Fog"))

    def reset_project_overlays(self):
        self._shape_definition = None
        self.display_widget.clear_ruler()
        self.display_widget.clear_shape()
        if self.player_screen is not None:
            self.player_screen.display_widget.clear_ruler()
            self.player_screen.display_widget.clear_shape()

    def _refresh_debug_stats(self):
        with self.performance.measure("ui.performance_panel.refresh"):
            checkers = [("DM", self.performance)]
            if self.player_screen is not None:
                checkers.append(("Player", self.player_screen.performance))
            for layer in self.layer_manager.layers:
                media_checker = getattr(layer.media, "performance", None)
                if media_checker is not None:
                    checkers.append((f"Media.{layer.name}", media_checker))
            self.debug_panel.set_checkers(checkers)

    def update_player_highlight(self, zoom: float):
        if self.player_screen is not None:
            self.set_player_viewport_rect(
                self.player_screen.display_widget.visible_source_rect()
            )
            return

        coverage = max(0.1, min(1.0, 1.0 / float(zoom)))
        offset = (1.0 - coverage) / 2.0
        self.set_player_viewport_rect((offset, offset, coverage, coverage))

    def set_player_viewport_rect(self, rect):
        if self.player_screen is None:
            return
        self.display_widget.set_highlight_rect(rect)

    def sync_frame_settings(self):
        super().sync_frame_settings()
        self.display_widget.set_mask_frame_size(self.frame.size)
        self._update_shape_overlay()
        if self.player_controls is not None:
            self.update_player_highlight(
                self.player_controls.player_zoom_spin.value()
            )