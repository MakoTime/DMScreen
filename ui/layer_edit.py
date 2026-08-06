from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
	QCheckBox,
	QComboBox,
	QColorDialog,
	QDialog,
	QDialogButtonBox,
	QFileDialog,
	QFormLayout,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QPushButton,
	QDoubleSpinBox,
	QSpinBox,
	QVBoxLayout,
	QWidget,
)

from layer_manager import Layer, LayerManager
from layer_media import (
	AnimationMedia,
	DrawMedia,
	GifMedia,
	GridMedia,
	ImageMedia,
	MaskMedia,
	VideoMedia,
)
from screen import Frame


class LayerEditModel(QObject):
	"""Editable state for one layer and its scene preview."""

	changed = Signal()

	def __init__(
		self,
		layer: Layer,
		frame: Frame,
		layers: list[Layer] | None = None,
		target: Layer | None = None,
		parent=None,
		frame_changed_callback=None,
	):
		super().__init__(parent)
		self.layer = Layer(
			name=layer.name,
			layer_id=layer.layer_id,
			media=layer.media.copy() if layer.media is not None else None,
			visible=layer.visible,
			player_visible=layer.player_visible,
			offset=QPoint(layer.offset),
			scale=tuple(layer.scale),
			alpha=layer.alpha,
			mask_layer_id=layer.mask_layer_id,
		)
		self.frame = frame
		self.reference_layers = [item for item in (layers or []) if item is not layer]
		self.target = target
		self.frame_changed_callback = frame_changed_callback
		self.keep_aspect_ratio = True
		self._fit_media_when_ready = False
		self._disposed = False
		self._connect_media()
		self.media_model = LayerMediaEditModel(self)

	def _connect_media(self):
		if self.layer.media is not None:
			self.layer.media.frame_changed.connect(self._media_frame_changed)

	def _media_frame_changed(self):
		if self._fit_media_when_ready:
			self._fit_media_to_frame()
			self._fit_media_when_ready = False
		self.changed.emit()

	def set_keep_aspect_ratio(self, enabled: bool):
		self.keep_aspect_ratio = enabled
		self.changed.emit()

	def set_name(self, name: str):
		self.layer.name = name
		self.changed.emit()

	def set_scale(self, scale_x: float, scale_y: float):
		self.layer.scale = (
			max(0.01, scale_x),
			max(0.01, scale_x if self.keep_aspect_ratio else scale_y),
		)
		self.changed.emit()

	def set_offset(self, x: int, y: int):
		self.layer.offset = QPoint(x, y)
		self.changed.emit()

	def set_alpha(self, alpha: float):
		self.layer.alpha = max(0.0, min(1.0, alpha))
		self.changed.emit()

	def set_mask_layer(self, mask_layer_id: str | None):
		self.layer.mask_layer_id = mask_layer_id
		self.changed.emit()

	def fit_media_to_frame(self):
		self._fit_media_to_frame()
		self.changed.emit()

	def fit_frame_to_media(self):
		if self.layer.media is None or self.layer.media.is_empty():
			return
		image = self.layer.media.current_frame()
		scale_x, scale_y = self.layer.scale
		self.frame.set_size(
			max(1, round(image.width() * scale_x)),
			max(1, round(image.height() * scale_y)),
		)
		self.layer.offset = QPoint()
		if self.frame_changed_callback is not None:
			self.frame_changed_callback()
		self.changed.emit()

	def create_animation(self):
		self.media_model.create_animation()

	def create_grid(self):
		self.media_model.create_grid()

	def create_draw(self):
		self.media_model.create_draw()

	def create_mask(self):
		self.media_model.create_mask()

	def set_mask_auto_fill(self, auto_fill: bool):
		self.media_model.set_mask_auto_fill(auto_fill)

	def set_mask_brush_size(self, brush_size: int):
		self.media_model.set_mask_brush_size(brush_size)

	def detect_grid(self, image: QImage) -> bool:
		return self.media_model.detect_grid(image)

	def _sync_grid_to_target(self):
		self.media_model.sync_grid_to_target()

	def import_media(self, file_path: str) -> bool:
		if not Path(file_path).is_file():
			return False

		image = QImage(file_path)
		if Path(file_path).suffix.lower() == ".gif":
			self._stop_media()
			self.layer.media = GifMedia(file_path)
			self._connect_media()
			self._fit_media_when_ready = self.layer.media.is_empty()
			if not self._fit_media_when_ready:
				self._fit_media_to_frame()
			self.changed.emit()
			return True
		if not image.isNull():
			self._stop_media()
			self.layer.media = ImageMedia(image)
			self._fit_media_to_frame()
			self.changed.emit()
			return True
		else:
			self._stop_media()
			try:
				self.layer.media = VideoMedia(file_path)
			except RuntimeError:
				return False
			self._connect_media()
			self._fit_media_when_ready = isinstance(self.layer.media, VideoMedia)
			if not self._fit_media_when_ready:
				self._fit_media_to_frame()
			self.changed.emit()
			return True

	def _stop_media(self):
		if self.layer.media is None:
			return
		self.layer.media.frame_changed.disconnect(self._media_frame_changed)
		self.layer.media.stop()

	def dispose(self):
		if self._disposed:
			return
		self._disposed = True
		self._stop_media()

	def _fit_media_to_frame(self):
		if self.layer.media is None or self.layer.media.is_empty():
			return
		image = self.layer.media.current_frame()
		frame_size = self.frame.size
		if frame_size.isEmpty():
			self.layer.scale = (1.0, 1.0)
		else:
			fit_scale = min(
				frame_size.width() / image.width(),
				frame_size.height() / image.height(),
			)
			self.layer.scale = (fit_scale, fit_scale)
		self.layer.offset = QPoint(
			round((frame_size.width() - image.width() * self.layer.scale[0]) / 2),
			round((frame_size.height() - image.height() * self.layer.scale[1]) / 2),
		)

	def preview_image(self) -> QImage:
		mask_layers = [
			layer
			for layer in self.reference_layers
			if layer.layer_id == self.layer.mask_layer_id
		]
		return self.frame.draw([self.layer], mask_layers)

	def commit(self, target: Layer):
		new_media = self.layer.media.copy() if self.layer.media is not None else None
		if target.media is not None:
			target.media.stop()
		target.name = self.layer.name
		target.media = new_media
		target.offset = QPoint(self.layer.offset)
		target.scale = self.layer.scale
		target.alpha = self.layer.alpha
		target.mask_layer_id = self.layer.mask_layer_id


class AnimationEditModel:
	"""Owns procedural animation editing state and operations."""

	def __init__(self, media_model):
		self.media_model = media_model

	@property
	def layer(self):
		return self.media_model.layer

	def create(self):
		self.media_model.create_animation()

	def set_parameters(self, mode, speed, noise_scale, direction):
		media = self.layer.media
		if not isinstance(media, AnimationMedia):
			return
		media.set_parameters(
			media.color_a,
			media.color_b,
			mode,
			speed,
			noise_scale,
			direction,
		)

	def set_color(self, channel, color):
		media = self.layer.media
		if not isinstance(media, AnimationMedia):
			return
		if channel == "a":
			media.color_a = color
		else:
			media.color_b = color
		media._render()
		media.frame_changed.emit()


class GridEditModel:
	"""Owns grid editing state and operations."""

	def __init__(self, media_model):
		self.media_model = media_model

	@property
	def layer(self):
		return self.media_model.layer

	def create(self):
		self.media_model.create_grid()

	def set_parameters(self, spacing, offset, line_width):
		media = self.layer.media
		if not isinstance(media, GridMedia):
			return
		media.set_parameters(
			spacing,
			spacing,
			offset[0],
			offset[1],
			line_width,
			media.color,
		)
		self.media_model.sync_grid_to_target()

	def detect(self, image):
		return self.media_model.detect_grid(image)

	def set_color(self, color):
		media = self.layer.media
		if not isinstance(media, GridMedia):
			return
		media.color = color
		media._render()
		media.frame_changed.emit()
		self.media_model.sync_grid_to_target()


class MaskEditModel:
	"""Owns mask editing state and operations."""

	def __init__(self, media_model):
		self.media_model = media_model

	@property
	def layer(self):
		return self.media_model.layer

	def create(self):
		self.media_model.create_mask()

	def set_auto_fill(self, auto_fill):
		self.media_model.set_mask_auto_fill(auto_fill)

	def set_brush_size(self, brush_size):
		self.media_model.set_mask_brush_size(brush_size)


class LayerMediaEditModel:
	"""Coordinates shared media lifecycle and specialized media models."""

	def __init__(self, layer_model):
		self.layer_model = layer_model
		self.animation = AnimationEditModel(self)
		self.grid = GridEditModel(self)
		self.mask = MaskEditModel(self)

	@property
	def layer(self):
		return self.layer_model.layer

	@property
	def frame(self):
		return self.layer_model.frame

	def _replace(self, media):
		self.layer_model._stop_media()
		self.layer.media = media
		self.layer_model._connect_media()

	def create_animation(self):
		self._replace(
			AnimationMedia(
				max(16, self.frame.size.width()),
				max(16, self.frame.size.height()),
			)
		)
		self.layer_model._fit_media_to_frame()
		self.layer_model.changed.emit()

	def create_grid(self):
		self._replace(
			GridMedia(
				max(16, self.frame.size.width()),
				max(16, self.frame.size.height()),
			)
		)
		self.layer_model._fit_media_to_frame()
		self.layer_model.changed.emit()

	def create_draw(self):
		self._replace(
			DrawMedia(self.frame.size.width(), self.frame.size.height())
		)
		self.layer_model.changed.emit()

	def create_mask(self):
		self._replace(
			MaskMedia(self.frame.size.width(), self.frame.size.height())
		)
		self.layer.alpha = 0.5
		self.layer.mask_layer_id = None
		self.layer_model.changed.emit()

	def set_mask_auto_fill(self, auto_fill):
		if isinstance(self.layer.media, MaskMedia):
			self.layer.media.set_auto_fill(auto_fill)
			self.layer_model.changed.emit()

	def set_mask_brush_size(self, brush_size):
		if isinstance(self.layer.media, MaskMedia):
			self.layer.media.brush_size = max(1, int(brush_size))
			self.layer_model.changed.emit()

	def detect_grid(self, image):
		if not isinstance(self.layer.media, GridMedia):
			return False
		detected = self.layer.media.detect_from_image(image)
		if detected:
			self.sync_grid_to_target()
		return detected

	def sync_grid_to_target(self):
		media = self.layer.media
		target = self.layer_model.target
		if not isinstance(media, GridMedia):
			return
		if target is None or not isinstance(target.media, GridMedia):
			return
		target.media.set_parameters(
			media.spacing_x,
			media.spacing_y,
			media.offset_x,
			media.offset_y,
			media.line_width,
			media.color,
		)


class ScenePreview(QWidget):
	"""Paints the frame outline and the edited layer inside it."""

	def __init__(self, frame: Frame, parent=None):
		super().__init__(parent)
		self.frame = frame
		self.image = QImage()
		self.setMinimumSize(360, 240)

	def set_image(self, image: QImage):
		self.image = image
		self.update()

	def paintEvent(self, event):
		painter = QPainter(self)
		try:
			painter.fillRect(self.rect(), QColor("#20242a"))

			frame_size = self.frame.size
			if frame_size.isEmpty():
				return

			preview_size = frame_size.scaled(
				self.size(), Qt.KeepAspectRatio
			)
			frame_rect = QRect(QPoint(0, 0), preview_size)
			frame_rect.moveCenter(self.rect().center())
			painter.fillRect(frame_rect, QColor("#0d0f12"))
			if not self.image.isNull():
				painter.drawImage(frame_rect, self.image)
			painter.setPen(QPen(QColor("#d4a85b"), 2))
			painter.drawRect(frame_rect.adjusted(1, 1, -1, -1))
		finally:
			painter.end()


class AnimationLayerView(QWidget):
	"""Controls specific to procedural animation layers."""

	def __init__(self, model, parent=None):
		super().__init__(parent)
		self.model = model.media_model.animation
		self.create_button = QPushButton("Create Animation")
		self.mode = QComboBox()
		self.mode.addItems(("Color to color", "Color to alpha"))
		self.direction_x = self._direction_spin()
		self.direction_y = self._direction_spin()
		self.color_a = QPushButton()
		self.color_b = QPushButton()
		self.speed = QDoubleSpinBox()
		self.speed.setRange(0.0, 1.0)
		self.speed.setSingleStep(0.01)
		self.speed.setDecimals(2)
		self.speed.setFixedWidth(96)
		self.noise_scale = QDoubleSpinBox()
		self.noise_scale.setRange(0.003, 0.08)
		self.noise_scale.setSingleStep(0.003)
		self.noise_scale.setDecimals(3)
		self.noise_scale.setFixedWidth(96)

		form = QFormLayout(self)
		form.addRow(self.create_button)
		form.addRow("Animation output", self.mode)
		form.addRow("Animation direction X", self.direction_x)
		form.addRow("Animation direction Y", self.direction_y)
		form.addRow("Animation color A", self.color_a)
		form.addRow("Animation color B", self.color_b)
		form.addRow("Animation speed", self.speed)
		form.addRow("Noise scale", self.noise_scale)
		self._form = form
		self.create_button.clicked.connect(self.model.create)
		self.mode.currentIndexChanged.connect(self._changed)
		self.direction_x.valueChanged.connect(self._changed)
		self.direction_y.valueChanged.connect(self._changed)
		self.color_a.clicked.connect(lambda: self._choose_color("a"))
		self.color_b.clicked.connect(lambda: self._choose_color("b"))
		self.speed.valueChanged.connect(self._changed)
		self.noise_scale.valueChanged.connect(self._changed)

	def set_color_b_visible(self, visible):
		self._form.setRowVisible(self.color_b, visible)

	def refresh(self, media):
		is_animation = isinstance(media, AnimationMedia)
		self.setVisible(is_animation)
		if not is_animation:
			return
		self.mode.blockSignals(True)
		self.mode.setCurrentIndex(1 if media.transparent_b else 0)
		self.mode.blockSignals(False)
		for spin, value in zip(
			(self.direction_x, self.direction_y), media.direction
		):
			spin.blockSignals(True)
			spin.setValue(value)
			spin.blockSignals(False)
		for spin, value in (
			(self.speed, media.speed),
			(self.noise_scale, media.noise_scale),
		):
			spin.blockSignals(True)
			spin.setValue(value)
			spin.blockSignals(False)
		self._set_color_button(self.color_a, media.color_a)
		self._set_color_button(self.color_b, media.color_b)
		self.set_color_b_visible(self.mode.currentIndex() != 1)

	def _changed(self):
		self.model.set_parameters(
			self.mode.currentIndex() == 1,
			self.speed.value(),
			self.noise_scale.value(),
			(self.direction_x.value(), self.direction_y.value()),
		)

	def _choose_color(self, channel):
		media = self.model.layer.media
		if not isinstance(media, AnimationMedia):
			return
		current = media.color_a if channel == "a" else media.color_b
		color = QColorDialog.getColor(current, self, "Choose animation color")
		if not color.isValid():
			return
		self.model.set_color(channel, color)

	@staticmethod
	def _set_color_button(button, color):
		button.setText(color.name())
		button.setStyleSheet(
			f"background-color: {color.name()}; color: {'white' if color.lightness() < 128 else 'black'}"
		)

	@staticmethod
	def _direction_spin():
		spin = QDoubleSpinBox()
		spin.setRange(-100.0, 100.0)
		spin.setSingleStep(0.1)
		spin.setDecimals(3)
		return spin


class GridLayerView(QWidget):
	"""Controls specific to grid layers."""

	def __init__(self, model, reference_layers, parent=None):
		super().__init__(parent)
		self.model = model.media_model.grid
		self.detect_button = QPushButton("Grid Detect")
		self.reference = QComboBox()
		self.spacing_x = self._grid_spin(2, 10000, 100)
		self.spacing_y = self._grid_spin(2, 10000, 100)
		self.offset_x = self._grid_spin(-10000, 10000, 0)
		self.offset_y = self._grid_spin(-10000, 10000, 0)
		self.line_width = self._grid_spin(1, 20, 2)
		self.color = QPushButton()
		for layer in reference_layers:
			if layer.media is not None:
				self.reference.addItem(layer.name, layer)

		form = QFormLayout(self)
		form.addRow(self.detect_button)
		form.addRow("Grid reference layer", self.reference)
		form.addRow("Grid spacing X", self.spacing_x)
		form.addRow("Grid spacing Y (same as X)", self.spacing_y)
		form.addRow("Grid offset X", self.offset_x)
		form.addRow("Grid offset Y", self.offset_y)
		form.addRow("Grid line width", self.line_width)
		form.addRow("Grid color", self.color)
		self.detect_button.clicked.connect(self._detect)
		self.spacing_x.valueChanged.connect(self._changed)
		self.spacing_y.valueChanged.connect(self._changed)
		self.offset_x.valueChanged.connect(self._changed)
		self.offset_y.valueChanged.connect(self._changed)
		self.line_width.valueChanged.connect(self._changed)
		self.color.clicked.connect(self._choose_color)

	def refresh(self, media):
		is_grid = isinstance(media, GridMedia)
		self.setVisible(is_grid)
		if not is_grid:
			return
		self.spacing_y.setEnabled(False)
		for spin, value in (
			(self.spacing_x, media.spacing_x),
			(self.spacing_y, media.spacing_y),
			(self.offset_x, media.offset_x),
			(self.offset_y, media.offset_y),
			(self.line_width, media.line_width),
		):
			spin.blockSignals(True)
			spin.setValue(value)
			spin.blockSignals(False)
		self._set_color_button(media.color)

	def _detect(self):
		index = self.reference.currentIndex()
		if index < 0:
			return
		layer = self.reference.itemData(index)
		if layer is not None and layer.media is not None:
			self.model.detect(layer.media.current_frame())

	def _changed(self):
		spacing = self.spacing_x.value()
		self.spacing_y.blockSignals(True)
		self.spacing_y.setValue(spacing)
		self.spacing_y.blockSignals(False)
		self.model.set_parameters(
			spacing,
			(self.offset_x.value(), self.offset_y.value()),
			self.line_width.value(),
		)

	def _choose_color(self):
		media = self.model.layer.media
		if not isinstance(media, GridMedia):
			return
		color = QColorDialog.getColor(media.color, self, "Choose grid color")
		if color.isValid():
			self.model.set_color(color)

	def _set_color_button(self, color):
		self.color.setText(color.name())
		self.color.setStyleSheet(
			f"background-color: {color.name()}; color: {'white' if color.lightness() < 128 else 'black'}"
		)

	@staticmethod
	def _grid_spin(minimum, maximum, value):
		spin = QSpinBox()
		spin.setRange(minimum, maximum)
		spin.setValue(value)
		return spin


class MaskLayerView(QWidget):
	"""Controls specific to mask layers."""

	def __init__(self, model, parent=None):
		super().__init__(parent)
		self.model = model.media_model.mask
		self.auto_fill = QCheckBox("Mask filled automatically")
		self.brush_size = QSpinBox()
		self.brush_size.setRange(1, 200)
		self.brush_size.setValue(20)
		form = QFormLayout(self)
		form.addRow(self.auto_fill)
		form.addRow("Mask brush size", self.brush_size)
		self.auto_fill.toggled.connect(self.model.set_auto_fill)
		self.brush_size.valueChanged.connect(self.model.set_brush_size)

	def refresh(self, media):
		is_mask = isinstance(media, MaskMedia)
		self.setVisible(is_mask)
		if not is_mask:
			return
		self.auto_fill.blockSignals(True)
		self.auto_fill.setChecked(media.auto_fill)
		self.auto_fill.blockSignals(False)
		self.brush_size.blockSignals(True)
		self.brush_size.setValue(media.brush_size)
		self.brush_size.blockSignals(False)


class LayerEditView(QDialog):
	"""Dialog view for editing a layer and previewing it in the frame."""

	def __init__(self, model: LayerEditModel, parent=None):
		super().__init__(parent)
		self.model = model
		self.setWindowTitle("Edit Layer")
		self.resize(780, 480)

		self.name_edit = QLineEdit(model.layer.name)
		self.import_button = QPushButton("Import Image or Video")
		self.fit_button = QPushButton("Fit to Frame")
		self.fit_frame_button = QPushButton("Fit Frame to Media")
		self.keep_aspect_checkbox = QCheckBox("Keep aspect ratio")
		self.keep_aspect_checkbox.setChecked(True)
		self.media_type = QComboBox()
		self.media_type.addItems(
			("Image / GIF / Video", "Animation", "Grid", "Draw", "Mask")
		)
		self.media_type.setToolTip(
			"Choose Animation to replace this layer with procedural media"
		)
		self.scale_x_spin = self._scale_spin()
		self.scale_y_spin = self._scale_spin()
		self.offset_x_spin = self._offset_spin()
		self.offset_y_spin = self._offset_spin()
		self.alpha_spin = self._alpha_spin()
		self.mask_link = QComboBox()
		self.mask_link.addItem("None", None)
		for layer in model.reference_layers:
			if isinstance(layer.media, MaskMedia):
				self.mask_link.addItem(layer.name, layer.layer_id)
		self.animation_view = AnimationLayerView(model)
		self.grid_view = GridLayerView(model, model.reference_layers)
		self.mask_view = MaskLayerView(model)
		self.preview = ScenePreview(model.frame)

		form = QFormLayout()
		form.addRow("Layer", self.name_edit)
		form.addRow("Media type", self.media_type)
		form.addRow(self.import_button)
		fit_controls = QWidget()
		fit_layout = QHBoxLayout(fit_controls)
		fit_layout.setContentsMargins(0, 0, 0, 0)
		fit_layout.addWidget(self.fit_button)
		fit_layout.addWidget(self.fit_frame_button)
		form.addRow(fit_controls)
		form.addRow(self.keep_aspect_checkbox)
		form.addRow("Scale X", self.scale_x_spin)
		form.addRow("Scale Y", self.scale_y_spin)
		form.addRow("Offset X", self.offset_x_spin)
		form.addRow("Offset Y", self.offset_y_spin)
		form.addRow("Alpha (%)", self.alpha_spin)
		form.addRow("Mask link", self.mask_link)
		form.addRow(self.mask_view)
		form.addRow(self.animation_view)
		form.addRow(self.grid_view)

		controls = QWidget()
		controls.setLayout(form)
		content = QHBoxLayout()
		content.addWidget(controls)
		content.addWidget(self.preview, 1)

		buttons = QDialogButtonBox(
			QDialogButtonBox.StandardButton.Ok
			| QDialogButtonBox.StandardButton.Cancel
		)
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)

		layout = QVBoxLayout(self)
		layout.addLayout(content)
		layout.addWidget(buttons)

		self.import_button.clicked.connect(self._import_media)
		self.fit_button.clicked.connect(self.model.fit_media_to_frame)
		self.fit_frame_button.clicked.connect(self.model.fit_frame_to_media)
		self.media_type.currentIndexChanged.connect(self._media_type_changed)
		self.keep_aspect_checkbox.toggled.connect(self._keep_aspect_changed)
		self.scale_x_spin.valueChanged.connect(self._scale_changed)
		self.scale_y_spin.valueChanged.connect(self._scale_changed)
		self.offset_x_spin.valueChanged.connect(self._offset_changed)
		self.offset_y_spin.valueChanged.connect(self._offset_changed)
		self.alpha_spin.valueChanged.connect(self._alpha_changed)
		self.name_edit.textChanged.connect(self.model.set_name)
		self.mask_link.currentIndexChanged.connect(self._mask_link_changed)
		self.model.changed.connect(self._refresh)
		self._refresh()

	@property
	def animation_button(self):
		return self.animation_view.create_button

	@property
	def animation_mode(self):
		return self.animation_view.mode

	@property
	def animation_direction_x(self):
		return self.animation_view.direction_x

	@property
	def animation_direction_y(self):
		return self.animation_view.direction_y

	@property
	def animation_color_a(self):
		return self.animation_view.color_a

	@property
	def animation_color_b(self):
		return self.animation_view.color_b

	@property
	def animation_speed(self):
		return self.animation_view.speed

	@property
	def animation_scale(self):
		return self.animation_view.noise_scale

	@property
	def grid_reference(self):
		return self.grid_view.reference

	@property
	def grid_detect_button(self):
		return self.grid_view.detect_button

	@property
	def grid_spacing_x(self):
		return self.grid_view.spacing_x

	@property
	def grid_spacing_y(self):
		return self.grid_view.spacing_y

	@property
	def grid_offset_x(self):
		return self.grid_view.offset_x

	@property
	def grid_offset_y(self):
		return self.grid_view.offset_y

	@property
	def grid_line_width(self):
		return self.grid_view.line_width

	@property
	def grid_color(self):
		return self.grid_view.color

	@property
	def mask_auto_fill(self):
		return self.mask_view.auto_fill

	@property
	def mask_brush_size(self):
		return self.mask_view.brush_size

	@staticmethod
	def _scale_spin():
		spin = QDoubleSpinBox()
		spin.setRange(0.01, 100.0)
		spin.setSingleStep(0.05)
		spin.setDecimals(2)
		return spin

	@staticmethod
	def _offset_spin():
		spin = QSpinBox()
		spin.setRange(-100000, 100000)
		return spin

	@staticmethod
	def _alpha_spin():
		spin = QSpinBox()
		spin.setRange(0, 100)
		spin.setSuffix(" %")
		return spin

	def _import_media(self):
		file_path, _ = QFileDialog.getOpenFileName(
			self,
			"Import Layer Image or Video",
			"",
			"Media (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.mp4 *.mov *.avi *.mkv *.webm);;Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Videos (*.mp4 *.mov *.avi *.mkv *.webm)",
		)
		if file_path:
			self.model.import_media(file_path)

	def _media_type_changed(self, index: int):
		if index == 1 and not isinstance(
			self.model.layer.media, AnimationMedia
		):
			self.model.create_animation()
		elif index == 2 and not isinstance(
			self.model.layer.media, GridMedia
		):
			self.model.create_grid()
		elif index == 3 and not isinstance(
			self.model.layer.media, DrawMedia
		):
			self.model.create_draw()
		elif index == 4 and not isinstance(
			self.model.layer.media, MaskMedia
		):
			self.model.create_mask()

	def _keep_aspect_changed(self, enabled: bool):
		self.model.set_keep_aspect_ratio(enabled)
		self.scale_y_spin.setEnabled(not enabled)

	def _scale_changed(self):
		self.model.set_scale(
			self.scale_x_spin.value(), self.scale_y_spin.value()
		)

	def _offset_changed(self):
		self.model.set_offset(
			self.offset_x_spin.value(), self.offset_y_spin.value()
		)

	def _alpha_changed(self):
		self.model.set_alpha(self.alpha_spin.value() / 100)

	def _mask_link_changed(self):
		self.model.set_mask_layer(self.mask_link.currentData())

	def _grid_changed(self):
		self.grid_view._changed()

	def _refresh(self):
		self.name_edit.blockSignals(True)
		self.name_edit.setText(self.model.layer.name)
		self.name_edit.blockSignals(False)
		scale_x, scale_y = self.model.layer.scale
		for spin, value in (
			(self.scale_x_spin, scale_x),
			(self.scale_y_spin, scale_y),
			(self.offset_x_spin, self.model.layer.offset.x()),
			(self.offset_y_spin, self.model.layer.offset.y()),
			(self.alpha_spin, round(self.model.layer.alpha * 100)),
		):
			spin.blockSignals(True)
			spin.setValue(value)
			spin.blockSignals(False)
		media = self.model.layer.media
		is_animation = isinstance(media, AnimationMedia)
		is_grid = isinstance(media, GridMedia)
		is_draw = isinstance(media, DrawMedia)
		is_mask = isinstance(media, MaskMedia)
		self.mask_link.setVisible(not is_mask)
		self.mask_link.blockSignals(True)
		mask_index = self.mask_link.findData(self.model.layer.mask_layer_id)
		self.mask_link.setCurrentIndex(max(0, mask_index))
		self.mask_link.blockSignals(False)
		self.media_type.blockSignals(True)
		self.media_type.setCurrentIndex(
			1 if is_animation else
			2 if is_grid else
			3 if is_draw else
			4 if is_mask else 0
		)
		self.media_type.blockSignals(False)
		is_procedural = is_animation or is_grid or is_draw or is_mask
		self.import_button.setVisible(not is_procedural)
		self.fit_button.setVisible(not is_procedural)
		self.fit_frame_button.setVisible(not is_procedural)
		self.mask_view.refresh(media)
		self.animation_view.refresh(media)
		self.grid_view.refresh(media)
		self.preview.set_image(self.model.preview_image())

	def accept(self):
		if isinstance(self.model.layer.media, AnimationMedia):
			self.model.layer.media.normalize_direction()
		super().accept()

	def closeEvent(self, event):
		self.model.dispose()
		super().closeEvent(event)


class LayerEditFactory:
	"""Creates layer edit dialogs with the application frame."""

	def __init__(
		self,
		frame: Frame,
		layer_manager: LayerManager | None = None,
		parent=None,
		frame_changed_callback=None,
	):
		self.frame = frame
		self.layer_manager = layer_manager
		self.parent = parent
		self.frame_changed_callback = frame_changed_callback

	def create(self, layer: Layer) -> LayerEditView:
		layers = self.layer_manager.layers if self.layer_manager is not None else []
		model = LayerEditModel(
			layer,
			self.frame,
			layers,
			layer,
			self.parent,
			self.frame_changed_callback,
		)
		return LayerEditView(model, self.parent)

	def edit(self, layer: Layer) -> bool:
		dialog = self.create(layer)
		if dialog.exec() != QDialog.DialogCode.Accepted:
			return False
		dialog.model.commit(layer)
		return True
