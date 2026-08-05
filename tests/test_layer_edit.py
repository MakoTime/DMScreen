import unittest

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from layer_edit import LayerEditFactory, LayerEditModel
from layer_manager import Layer, LayerManager
from layer_media import DrawMedia, GridMedia, ImageMedia, MaskMedia
from screen import Frame


class TestLayerEdit(unittest.TestCase):
    def setUp(self):
        self.frame = Frame(160, 100)

    def _layer(self, name, media=None):
        return Layer(name, media or ImageMedia(QImage(20, 10, QImage.Format.Format_ARGB32)))

    def test_factory_populates_grid_reference_layers(self):
        target = self._layer("grid", GridMedia(160, 100))
        reference = self._layer("map")
        manager = LayerManager()
        manager.add(target)
        manager.add(reference)
        dialog = LayerEditFactory(self.frame, manager).create(target)
        try:
            self.assertEqual(dialog.grid_reference.count(), 1)
            self.assertEqual(dialog.grid_reference.itemText(0), "map")
            self.assertIs(dialog.grid_reference.itemData(0), reference)
        finally:
            dialog.model.dispose()
            dialog.deleteLater()
            target.media.stop()
            reference.media.stop()

    def test_animation_and_grid_hide_import_controls(self):
        layer = self._layer("procedural")
        dialog = None
        try:
            dialog = LayerEditFactory(self.frame).create(layer)
            dialog.show()
            QApplication.processEvents()
            dialog.model.create_animation()
            QApplication.processEvents()
            self.assertFalse(dialog.import_button.isVisible())
            self.assertTrue(dialog.animation_mode.isVisible())
            self.assertFalse(dialog.grid_spacing_x.isVisible())

            dialog.model.create_grid()
            self.assertFalse(dialog.import_button.isVisible())
            self.assertFalse(dialog.animation_mode.isVisible())
            self.assertTrue(dialog.grid_spacing_x.isVisible())
        finally:
            if dialog is not None:
                dialog.model.dispose()
                dialog.deleteLater()
            if layer.media is not None:
                layer.media.stop()

    def test_grid_changes_sync_to_target_layer_immediately(self):
        target_media = GridMedia(160, 100)
        target = self._layer("grid", target_media)
        source = self._layer("reference")
        manager = LayerManager()
        manager.add(target)
        manager.add(source)
        dialog = LayerEditFactory(self.frame, manager).create(target)
        try:
            dialog.model.create_grid()
            dialog.grid_spacing_x.setValue(37)
            dialog.grid_offset_x.setValue(11)
            self.assertEqual(target_media.spacing_x, 37)
            self.assertEqual(target_media.spacing_y, 37)
            self.assertEqual(target_media.offset_x, 11)
        finally:
            dialog.model.dispose()
            dialog.deleteLater()
            manager.remove(1)
            manager.remove(0)

    def test_non_grid_media_does_not_live_sync(self):
        target_media = ImageMedia(QImage(10, 10, QImage.Format.Format_ARGB32))
        target = self._layer("image", target_media)
        dialog = LayerEditFactory(self.frame).create(target)
        try:
            dialog.grid_spacing_x.setValue(47)
            dialog._grid_changed()
            self.assertEqual(target_media.size, QSize(10, 10))
        finally:
            dialog.model.dispose()
            dialog.deleteLater()
            target_media.stop()

    def test_draw_and_mask_types_create_frame_sized_media(self):
        layer = self._layer("canvas")
        dialog = LayerEditFactory(self.frame).create(layer)
        try:
            dialog.show()
            QApplication.processEvents()
            dialog.media_type.setCurrentText("Draw")
            self.assertIsInstance(dialog.model.layer.media, DrawMedia)
            self.assertEqual(dialog.model.layer.media.size, QSize(160, 100))

            dialog.media_type.setCurrentText("Mask")
            self.assertIsInstance(dialog.model.layer.media, MaskMedia)
            self.assertTrue(dialog.mask_auto_fill.isVisible())
            self.assertEqual(dialog.alpha_spin.value(), 50)
            dialog.mask_brush_size.setValue(31)
            self.assertEqual(dialog.model.layer.media.brush_size, 31)
            dialog.mask_auto_fill.setChecked(True)
            self.assertEqual(
                dialog.model.layer.media.current_frame().pixelColor(0, 0).name(),
                "#ffffff",
            )
        finally:
            dialog.model.dispose()
            dialog.deleteLater()
            if layer.media is not None:
                layer.media.stop()

    def test_fit_button_restores_image_to_frame(self):
        layer = self._layer("image")
        dialog = LayerEditFactory(self.frame).create(layer)
        try:
            dialog.show()
            QApplication.processEvents()
            dialog.model.set_scale(1.0, 1.0)
            dialog.model.set_offset(23, 31)
            dialog.fit_button.click()
            QApplication.processEvents()
            self.assertEqual(dialog.model.layer.scale, (8.0, 8.0))
            self.assertEqual(dialog.model.layer.offset, QPoint(0, 10))
            self.assertTrue(dialog.fit_button.isVisible())

            dialog.fit_frame_button.click()
            QApplication.processEvents()
            self.assertEqual(self.frame.size, QSize(160, 80))
            self.assertEqual(dialog.model.layer.offset, QPoint(0, 0))
            self.assertTrue(dialog.fit_frame_button.isVisible())
        finally:
            dialog.model.dispose()
            dialog.deleteLater()
            if layer.media is not None:
                layer.media.stop()

    def test_commit_copies_media_and_transform(self):
        target = self._layer("target")
        model = LayerEditModel(target, self.frame)
        try:
            model.create_grid()
            model.set_name("Renamed layer")
            model.set_offset(12, 8)
            model.set_alpha(0.4)
            model.commit(target)
            self.assertIsInstance(target.media, GridMedia)
            self.assertIsNot(target.media, model.layer.media)
            self.assertEqual(target.name, "Renamed layer")
            self.assertEqual(target.offset, QPoint(12, 8))
            self.assertEqual(target.alpha, 0.4)
        finally:
            model.dispose()
            if target.media is not None:
                target.media.stop()


if __name__ == "__main__":
    unittest.main()
