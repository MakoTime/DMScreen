from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ui.factories import LayerEditFactory
from layer_manager import Layer, LayerManager
from layer_media import AnimationMedia
from screen import Frame


class LayerModel(QAbstractTableModel):
    MOVE, VISIBLE, PLAYER_VISIBLE, NAME, IMAGE = range(5)
    HEADERS = ("", "DM", "Player", "Name", "Image")

    def __init__(self, layer_manager: LayerManager, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self._updating_manager = False
        self._moving_rows = False
        layer_manager.subscribe_to_updates(self.refresh)
        layer_manager.subscribe_to_media_updates(self.media_refresh)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.layer_manager.layers)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if (
            orientation == Qt.Horizontal
            and role == Qt.DisplayRole
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.layer_manager.layers):
            return None

        layer = self.layer_manager.layers[index.row()]
        if index.column() == self.VISIBLE and role == Qt.CheckStateRole:
            return Qt.Checked if layer.visible else Qt.Unchecked
        if index.column() == self.PLAYER_VISIBLE and role == Qt.CheckStateRole:
            return Qt.Checked if layer.player_visible else Qt.Unchecked
        if index.column() == self.NAME and role == Qt.DisplayRole:
            return layer.name
        if index.column() == self.IMAGE and role == Qt.DecorationRole:
            if layer.media is not None and not layer.media.is_empty():
                thumbnail_frame = getattr(layer.media, "thumbnail_frame", None)
                image = (
                    thumbnail_frame()
                    if thumbnail_frame is not None
                    else layer.media.current_frame()
                )
                return QPixmap.fromImage(image).scaled(
                    80,
                    80,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
        if role == Qt.UserRole:
            return layer
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled

        flags = (
            Qt.ItemIsEnabled
            | Qt.ItemIsSelectable
            | Qt.ItemIsDragEnabled
            | Qt.ItemIsDropEnabled
        )
        if index.column() in (self.VISIBLE, self.PLAYER_VISIBLE):
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if (
            not index.isValid()
            or index.row() >= len(self.layer_manager.layers)
            or index.column() not in (self.VISIBLE, self.PLAYER_VISIBLE)
            or role != Qt.CheckStateRole
            or self._moving_rows
        ):
            return False

        try:
            is_visible = Qt.CheckState(value) == Qt.Checked
        except (TypeError, ValueError):
            return False

        layer = self.layer_manager.layers[index.row()]
        match index.column():
            case self.VISIBLE:
                layer.visible = is_visible
            case self.PLAYER_VISIBLE:
                layer.player_visible = is_visible
            case _:
                return False
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.layer_manager.on_update()
        return True

    def mimeTypes(self):
        return ["application/x-layer-row"]

    def mimeData(self, indexes):
        mime_data = QMimeData()
        rows = sorted({index.row() for index in indexes if index.isValid()})
        if rows:
            mime_data.setData("application/x-layer-row", str(rows[0]).encode())
        return mime_data

    def supportedDropActions(self):
        return Qt.MoveAction

    def dropMimeData(self, data, action, row, column, parent):
        if action != Qt.MoveAction or not data.hasFormat("application/x-layer-row"):
            return False

        source = int(bytes(data.data("application/x-layer-row")).decode())
        destination = row if row >= 0 else parent.row()
        if destination < 0:
            destination = self.rowCount()
        destination = min(destination, self.rowCount())
        return self.moveRows(QModelIndex(), source, 1, QModelIndex(), destination)

    def moveRows(self, source_parent, source_row, count, destination_parent, destination_child):
        if (
            source_parent.isValid()
            or destination_parent.isValid()
            or count != 1
            or source_row < 0
            or source_row >= self.rowCount()
            or destination_child < 0
            or destination_child > self.rowCount()
            or destination_child == source_row
        ):
            return False

        self._moving_rows = True
        try:
            if not self.beginMoveRows(
                source_parent,
                source_row,
                source_row,
                destination_parent,
                destination_child,
            ):
                return False

            layer = self.layer_manager.layers.pop(source_row)
            insert_at = destination_child
            if destination_child > source_row:
                insert_at -= 1
            self.layer_manager.layers.insert(insert_at, layer)
            self.endMoveRows()
            self._updating_manager = True
            try:
                self.layer_manager.on_update()
            finally:
                self._updating_manager = False
            return True
        finally:
            self._moving_rows = False

    def refresh(self):
        if self._updating_manager:
            return
        table = self.parent()
        current_row = table.currentIndex().row() if table is not None else -1
        self.beginResetModel()
        self.endResetModel()
        if table is not None and 0 <= current_row < self.rowCount():
            index = self.index(current_row, self.NAME)
            table.setCurrentIndex(index)
            table.selectRow(current_row)

    def media_refresh(self):
        """Keep media changes out of the model reset path during playback/painting."""
        if self._updating_manager or self.rowCount() == 0:
            return
        self.dataChanged.emit(
            self.index(0, self.IMAGE),
            self.index(self.rowCount() - 1, self.IMAGE),
            [Qt.DecorationRole],
        )


class LayerTable(QTableView):
    """Table view for a layer model."""

    def __init__(self, layer_manager: LayerManager, parent=None):
        super().__init__(parent)
        self.model_instance = LayerModel(layer_manager, self)
        self.setModel(self.model_instance)
        self.setColumnHidden(LayerModel.MOVE, True)

        header = self.horizontalHeader()
        header.setSectionResizeMode(
            LayerModel.VISIBLE, QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            LayerModel.PLAYER_VISIBLE, QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(LayerModel.NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(
            LayerModel.IMAGE, QHeaderView.ResizeToContents
        )

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.verticalHeader().setDefaultSectionSize(84)

    def selected_layer(self):
        index = self.currentIndex()
        if not index.isValid():
            return None
        return self.model_instance.layer_manager.layers[index.row()]

    def remove_selected(self):
        index = self.currentIndex()
        if index.isValid():
            self.model_instance.layer_manager.remove(index.row())


class LayerPanel(QWidget):
    def __init__(
        self,
        layer_manager: LayerManager,
        frame: Frame | None = None,
        parent=None,
        frame_changed_callback=None,
    ):
        super().__init__(parent)

        self.layer_manager = layer_manager
        self.edit_factory = LayerEditFactory(
            frame or Frame(),
            layer_manager,
            self,
            frame_changed_callback,
        )

        layout = QVBoxLayout(self)
        self.table = LayerTable(layer_manager, self)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.add_button = QPushButton("+")
        self.remove_button = QPushButton("-")
        self.edit_button = QPushButton("Edit")
        self.add_button.clicked.connect(self._add_default_layer)
        self.remove_button.clicked.connect(self.table.remove_selected)
        self.edit_button.clicked.connect(self.edit_selected)

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.edit_button)
        layout.addLayout(button_layout)

    def add_layer(self, layer: Layer):
        """Add a layer to the manager and table."""
        self.layer_manager.add(layer)

    def remove_selected(self):
        """Remove the currently selected layer."""
        self.table.remove_selected()

    def edit_selected(self):
        """Open the edit dialog for the currently selected layer."""
        layer = self.table.selected_layer()
        if layer is not None and self.edit_factory.edit(layer):
            self.layer_manager.on_update()

    def _add_default_layer(self):
        layer_number = len(self.layer_manager.layers) + 1
        layer = Layer(f"Layer {layer_number}")
        self.add_layer(layer)
        if self.edit_factory.edit(layer):
            self.layer_manager.on_update()

    def _add_animation_layer(self):
        layer_number = len(self.layer_manager.layers) + 1
        layer = Layer(f"Animation {layer_number}")
        media = AnimationMedia(
            min(160, max(16, self.edit_factory.frame.size.width() // 4)),
            min(90, max(16, self.edit_factory.frame.size.height() // 4)),
        )
        layer.media = media
        frame_size = self.edit_factory.frame.size
        if not frame_size.isEmpty():
            layer.scale = (
                frame_size.width() / media.width,
                frame_size.height() / media.height,
            )
        self.add_layer(layer)
        if self.edit_factory.edit(layer):
            self.layer_manager.on_update()
