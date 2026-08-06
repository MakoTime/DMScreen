from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtCore import QThread, QTimer, Qt
from layer_manager import Layer
from layer_media import DrawMedia
from layer_media import ImageMedia
from layer_media import MaskMedia
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

        background_image = QImage(
            str(Path(__file__).resolve().parents[2] / "Obyrith Dungeon Dark.png")
        )
        self.side_panel.add_layer(Layer("Background", ImageMedia(background_image)))
        self.side_panel.add_layer(Layer("Grid"))
        self.side_panel.add_layer(Layer("Tokens"))
        self.side_panel.add_layer(Layer("Fog"))
        self.update_player_highlight(1.0)

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
        if self.player_controls is not None:
            self.update_player_highlight(
                self.player_controls.player_zoom_spin.value()
            )