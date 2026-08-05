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
		self._stop_media()
		self.layer.media = AnimationMedia(
			min(160, max(16, self.frame.size.width() // 4)),
			min(90, max(16, self.frame.size.height() // 4)),
		)
		self._connect_media()
		self._fit_media_to_frame()
		self.changed.emit()

	def create_grid(self):
		self._stop_media()
		self.layer.media = GridMedia(
			max(16, self.frame.size.width()),
			max(16, self.frame.size.height()),
		)
		self._connect_media()
		self._fit_media_to_frame()
		self.changed.emit()

	def create_draw(self):
		self._stop_media()
		self.layer.media = DrawMedia(
			self.frame.size.width(),
			self.frame.size.height(),
		)
		self._connect_media()
		self.changed.emit()

	def create_mask(self):
		self._stop_media()
		self.layer.media = MaskMedia(
			self.frame.size.width(),
			self.frame.size.height(),
		)
		self.layer.alpha = 0.5
		self.layer.mask_layer_id = None
		self._connect_media()
		self.changed.emit()

	def set_mask_auto_fill(self, auto_fill: bool):
		if not isinstance(self.layer.media, MaskMedia):
			return
		self.layer.media.set_auto_fill(auto_fill)
		self.changed.emit()

	def set_mask_brush_size(self, brush_size: int):
		if not isinstance(self.layer.media, MaskMedia):
			return
		self.layer.media.brush_size = max(1, int(brush_size))
		self.changed.emit()

	def detect_grid(self, image: QImage) -> bool:
		media = self.layer.media
		if not isinstance(media, GridMedia):
			return False
		detected = media.detect_from_image(image)
		if detected:
			self._sync_grid_to_target()
		return detected

	def _sync_grid_to_target(self):
		if not isinstance(self.layer.media, GridMedia):
			return
		if self.target is None or not isinstance(self.target.media, GridMedia):
			return
		self.target.media.set_parameters(
			self.layer.media.spacing_x,
			self.layer.media.spacing_y,
			self.layer.media.offset_x,
			self.layer.media.offset_y,
			self.layer.media.line_width,
			self.layer.media.color,
		)

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
		self.animation_button = QPushButton("Create Animation")
		self.grid_detect_button = QPushButton("Grid Detect")
		self.grid_reference = QComboBox()
		for layer in model.reference_layers:
			if layer.media is not None:
				self.grid_reference.addItem(layer.name, layer)
		self.animation_mode = QComboBox()
		self.animation_mode.addItems(("Color to color", "Color to alpha"))
		self.animation_direction_x = self._direction_spin()
		self.animation_direction_y = self._direction_spin()
		self.animation_color_a = QPushButton()
		self.animation_color_b = QPushButton()
		self.animation_speed = QDoubleSpinBox()
		self.animation_speed.setRange(0.0, 1.0)
		self.animation_speed.setSingleStep(0.01)
		self.animation_speed.setDecimals(2)
		self.animation_scale = QDoubleSpinBox()
		self.animation_scale.setRange(0.003, 0.08)
		self.animation_scale.setSingleStep(0.003)
		self.animation_scale.setDecimals(3)
		self.grid_spacing_x = self._grid_spin(2, 10000, 100)
		self.grid_spacing_y = self._grid_spin(2, 10000, 100)
		self.grid_offset_x = self._grid_spin(-10000, 10000, 0)
		self.grid_offset_y = self._grid_spin(-10000, 10000, 0)
		self.grid_line_width = self._grid_spin(1, 20, 2)
		self.grid_color = QPushButton()
		self.mask_auto_fill = QCheckBox("Mask filled automatically")
		self.mask_brush_size = self._grid_spin(1, 200, 20)
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
		form.addRow(self.mask_auto_fill)
		self.mask_brush_size_label = QLabel("Mask brush size")
		form.addRow(self.mask_brush_size_label, self.mask_brush_size)
		form.addRow(self.animation_button)
		self.animation_mode_label = QLabel("Animation output")
		self.animation_direction_x_label = QLabel("Animation direction X")
		self.animation_direction_y_label = QLabel("Animation direction Y")
		self.animation_color_a_label = QLabel("Animation color A")
		self.animation_color_b_label = QLabel("Animation color B")
		self.animation_speed_label = QLabel("Animation speed")
		self.animation_scale_label = QLabel("Noise scale")
		self.grid_spacing_x_label = QLabel("Grid spacing X")
		self.grid_spacing_y_label = QLabel("Grid spacing Y (same as X)")
		self.grid_offset_x_label = QLabel("Grid offset X")
		self.grid_offset_y_label = QLabel("Grid offset Y")
		self.grid_line_width_label = QLabel("Grid line width")
		self.grid_color_label = QLabel("Grid color")
		self.grid_reference_label = QLabel("Grid reference layer")
		form.addRow(self.animation_mode_label, self.animation_mode)
		form.addRow(self.animation_direction_x_label, self.animation_direction_x)
		form.addRow(self.animation_direction_y_label, self.animation_direction_y)
		form.addRow(self.animation_color_a_label, self.animation_color_a)
		form.addRow(self.animation_color_b_label, self.animation_color_b)
		form.addRow(self.animation_speed_label, self.animation_speed)
		form.addRow(self.animation_scale_label, self.animation_scale)
		form.addRow(self.grid_detect_button)
		form.addRow(self.grid_reference_label, self.grid_reference)
		form.addRow(self.grid_spacing_x_label, self.grid_spacing_x)
		form.addRow(self.grid_spacing_y_label, self.grid_spacing_y)
		form.addRow(self.grid_offset_x_label, self.grid_offset_x)
		form.addRow(self.grid_offset_y_label, self.grid_offset_y)
		form.addRow(self.grid_line_width_label, self.grid_line_width)
		form.addRow(self.grid_color_label, self.grid_color)

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
		self.animation_button.clicked.connect(self.model.create_animation)
		self.grid_detect_button.clicked.connect(self._grid_detect)
		self.grid_spacing_x.valueChanged.connect(self._grid_changed)
		self.grid_spacing_y.valueChanged.connect(self._grid_changed)
		self.grid_offset_x.valueChanged.connect(self._grid_changed)
		self.grid_offset_y.valueChanged.connect(self._grid_changed)
		self.grid_line_width.valueChanged.connect(self._grid_changed)
		self.grid_color.clicked.connect(self._choose_grid_color)
		self.mask_auto_fill.toggled.connect(self._mask_auto_fill_changed)
		self.mask_brush_size.valueChanged.connect(self._mask_brush_size_changed)
		self.animation_mode.currentIndexChanged.connect(self._animation_changed)
		self.animation_direction_x.valueChanged.connect(self._animation_changed)
		self.animation_direction_y.valueChanged.connect(self._animation_changed)
		self.animation_color_a.clicked.connect(lambda: self._choose_color("a"))
		self.animation_color_b.clicked.connect(lambda: self._choose_color("b"))
		self.animation_speed.valueChanged.connect(self._animation_changed)
		self.animation_scale.valueChanged.connect(self._animation_changed)
		self.model.changed.connect(self._refresh)
		self._refresh()

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

	@staticmethod
	def _grid_spin(minimum, maximum, value):
		spin = QSpinBox()
		spin.setRange(minimum, maximum)
		spin.setValue(value)
		return spin

	@staticmethod
	def _direction_spin():
		spin = QDoubleSpinBox()
		spin.setRange(-100.0, 100.0)
		spin.setSingleStep(0.1)
		spin.setDecimals(3)
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

	def _mask_auto_fill_changed(self, enabled: bool):
		self.model.set_mask_auto_fill(enabled)

	def _mask_brush_size_changed(self):
		self.model.set_mask_brush_size(self.mask_brush_size.value())

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

	def _choose_color(self, channel: str):
		media = self.model.layer.media
		if not isinstance(media, AnimationMedia):
			return
		current = media.color_a if channel == "a" else media.color_b
		color = QColorDialog.getColor(current, self, "Choose animation color")
		if not color.isValid():
			return
		if channel == "a":
			media.color_a = color
		else:
			media.color_b = color
		media._render()
		media.frame_changed.emit()
		self._refresh()

	def _choose_grid_color(self):
		media = self.model.layer.media
		if not isinstance(media, GridMedia):
			return
		color = QColorDialog.getColor(media.color, self, "Choose grid color")
		if color.isValid():
			media.color = color
			media._render()
			media.frame_changed.emit()
			self.model._sync_grid_to_target()
			self._refresh()

	def _grid_detect(self):
		index = self.grid_reference.currentIndex()
		if index < 0:
			return
		layer = self.grid_reference.itemData(index)
		if layer is None or layer.media is None:
			return
		if self.model.detect_grid(layer.media.current_frame()):
			self._refresh()

	def _grid_changed(self):
		media = self.model.layer.media
		if not isinstance(media, GridMedia):
			return
		spacing = self.grid_spacing_x.value()
		self.grid_spacing_y.blockSignals(True)
		self.grid_spacing_y.setValue(spacing)
		self.grid_spacing_y.blockSignals(False)
		media.set_parameters(
			spacing,
			spacing,
			self.grid_offset_x.value(),
			self.grid_offset_y.value(),
			self.grid_line_width.value(),
			media.color,
		)
		self.model._sync_grid_to_target()

	def _animation_changed(self):
		media = self.model.layer.media
		if not isinstance(media, AnimationMedia):
			return
		media.set_parameters(
			media.color_a,
			media.color_b,
			self.animation_mode.currentIndex() == 1,
			self.animation_speed.value(),
			self.animation_scale.value(),
			(
				self.animation_direction_x.value(),
				self.animation_direction_y.value(),
			),
		)

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
		self.mask_auto_fill.setVisible(is_mask)
		for widget in (
			self.mask_brush_size_label,
			self.mask_brush_size,
		):
			widget.setVisible(is_mask)
		if is_mask:
			self.mask_auto_fill.blockSignals(True)
			self.mask_auto_fill.setChecked(media.auto_fill)
			self.mask_auto_fill.blockSignals(False)
			self.mask_brush_size.blockSignals(True)
			self.mask_brush_size.setValue(media.brush_size)
			self.mask_brush_size.blockSignals(False)
		self.animation_button.setVisible(is_animation)
		self.grid_detect_button.setVisible(is_grid)
		self.grid_reference_label.setVisible(is_grid)
		self.grid_reference.setVisible(is_grid)
		is_color_to_alpha = is_animation and self.animation_mode.currentIndex() == 1
		for widget in (
			self.animation_mode_label,
			self.animation_mode,
			self.animation_direction_x_label,
			self.animation_direction_x,
			self.animation_direction_y_label,
			self.animation_direction_y,
			self.animation_color_a_label,
			self.animation_color_a,
			self.animation_color_b_label,
			self.animation_color_b,
			self.animation_speed_label,
			self.animation_speed,
			self.animation_scale_label,
			self.animation_scale,
		):
			widget.setVisible(is_animation)
		self.animation_color_b_label.setVisible(is_animation and not is_color_to_alpha)
		self.animation_color_b.setVisible(is_animation and not is_color_to_alpha)
		for widget in (
			self.grid_spacing_x_label,
			self.grid_spacing_x,
			self.grid_spacing_y_label,
			self.grid_spacing_y,
			self.grid_offset_x_label,
			self.grid_offset_x,
			self.grid_offset_y_label,
			self.grid_offset_y,
			self.grid_line_width_label,
			self.grid_line_width,
			self.grid_color_label,
			self.grid_color,
		):
			widget.setVisible(is_grid)
		if is_grid:
			self.grid_spacing_y.setEnabled(False)
			for spin, value in (
				(self.grid_spacing_x, media.spacing_x),
				(self.grid_spacing_y, media.spacing_y),
				(self.grid_offset_x, media.offset_x),
				(self.grid_offset_y, media.offset_y),
				(self.grid_line_width, media.line_width),
			):
				spin.blockSignals(True)
				spin.setValue(value)
				spin.blockSignals(False)
			self._set_color_button(self.grid_color, media.color)
		if is_animation:
			self.animation_mode.blockSignals(True)
			self.animation_mode.setCurrentIndex(1 if media.transparent_b else 0)
			self.animation_mode.blockSignals(False)
			for spin, value in zip(
				(self.animation_direction_x, self.animation_direction_y),
				media.direction,
			):
				spin.blockSignals(True)
				spin.setValue(value)
				spin.blockSignals(False)
			for spin, value in (
				(self.animation_speed, media.speed),
				(self.animation_scale, media.noise_scale),
			):
				spin.blockSignals(True)
				spin.setValue(value)
				spin.blockSignals(False)
			self._set_color_button(self.animation_color_a, media.color_a)
			self._set_color_button(self.animation_color_b, media.color_b)
		self.preview.set_image(self.model.preview_image())

	@staticmethod
	def _set_color_button(button: QPushButton, color: QColor):
		button.setText(color.name())
		button.setStyleSheet(
			f"background-color: {color.name()}; color: {'white' if color.lightness() < 128 else 'black'}"
		)

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
