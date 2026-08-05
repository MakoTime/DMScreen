import unittest

import numpy as np
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage

from layer_manager import Layer, LayerManager
from layer_media import (
    AnimationMedia,
    DrawMedia,
    GridMedia,
    ImageMedia,
    LayerMedia,
    MaskMedia,
)
from screen import Frame, RenderState


class TestImageMedia(unittest.TestCase):
    def test_empty_media_is_empty(self):
        self.assertTrue(ImageMedia().is_empty())

    def test_copy_is_independent(self):
        image = QImage(8, 6, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        original = ImageMedia(image)
        copied = original.copy()
        copied.set_image(QImage(3, 2, QImage.Format.Format_ARGB32))
        self.assertEqual(original.size, image.size())
        self.assertEqual(copied.size, QSize(3, 2))


class TestAnimationMedia(unittest.TestCase):
    def setUp(self):
        self.media = AnimationMedia(32, 20)

    def tearDown(self):
        self.media.stop()

    def test_generates_frame_with_requested_size(self):
        self.assertEqual(self.media.current_frame().size().width(), 32)
        self.assertEqual(self.media.current_frame().size().height(), 20)
        self.assertFalse(self.media.current_frame().isNull())
        self.assertEqual(self.media.frame_array().shape, (20, 32, 4))

    def test_thumbnail_stays_at_initial_frame(self):
        initial = self.media.thumbnail_frame()
        self.media._advance()
        self.assertEqual(self.media.thumbnail_frame(), initial)

    def test_direction_is_normalized(self):
        self.media.direction = (3.0, 4.0)
        self.media.normalize_direction()
        self.assertEqual(self.media.direction, (0.6, 0.8))

    def test_zero_direction_falls_back_to_horizontal(self):
        self.media.direction = (0.0, 0.0)
        self.media.normalize_direction()
        self.assertEqual(self.media.direction, (1.0, 0.0))

    def test_copy_preserves_parameters(self):
        self.media.direction = (-2.0, 1.0)
        self.media.speed = 0.25
        self.media.noise_scale = 0.02
        self.media.transparent_b = True
        copied = self.media.copy()
        try:
            self.assertEqual(copied.direction, self.media.direction)
            self.assertEqual(copied.speed, self.media.speed)
            self.assertEqual(copied.noise_scale, self.media.noise_scale)
            self.assertTrue(copied.transparent_b)
        finally:
            copied.stop()


class TestGridMedia(unittest.TestCase):
    def test_square_spacing_is_enforced(self):
        media = GridMedia(100, 80)
        try:
            media.set_parameters(40, 60, 3, 4, 2, QColor("white"))
            self.assertEqual(media.spacing_x, 50)
            self.assertEqual(media.spacing_y, 50)
            self.assertEqual(media.offset_x, 3)
            self.assertEqual(media.offset_y, 4)
        finally:
            media.stop()


class TestDrawAndMaskMedia(unittest.TestCase):
    def test_draw_media_is_transparent_and_frame_sized(self):
        media = DrawMedia(160, 100)
        try:
            self.assertEqual(media.size, QSize(160, 100))
            self.assertEqual(media.current_frame().pixelColor(0, 0).alpha(), 0)
        finally:
            media.stop()

    def test_mask_media_can_toggle_automatic_fill(self):
        media = MaskMedia(160, 100)
        try:
            self.assertEqual(media.current_frame().pixelColor(0, 0).alpha(), 0)
            media.set_auto_fill(True)
            self.assertEqual(media.current_frame().pixelColor(0, 0).name(), "#ffffff")
            media.set_auto_fill(False)
            self.assertEqual(media.current_frame().pixelColor(0, 0).alpha(), 0)
        finally:
            media.stop()

    def test_mask_media_draws_and_erases_with_brush(self):
        media = MaskMedia(40, 40)
        try:
            media.paint_at(20, 20, 5)
            self.assertEqual(media.current_frame().pixelColor(20, 20).name(), "#ffffff")
            media.paint_line(5, 20, 35, 20, 5)
            self.assertEqual(media.current_frame().pixelColor(10, 20).name(), "#ffffff")
            alpha_values = {
                media.current_frame().pixelColor(x, y).alpha()
                for y in range(media.height)
                for x in range(media.width)
            }
            self.assertTrue(alpha_values <= {0, 255})
            media.paint_at(20, 20, 5, erase=True)
            self.assertEqual(media.current_frame().pixelColor(20, 20).alpha(), 0)
            media.fill()
            self.assertEqual(media.current_frame().pixelColor(0, 0).alpha(), 255)
            media.paint_line(20, 0, 20, 39, 5, erase=True)
            media.flood_fill(5, 5, erase=True)
            self.assertEqual(media.current_frame().pixelColor(5, 5).alpha(), 0)
            self.assertGreater(media.current_frame().pixelColor(35, 35).alpha(), 0)
            media.fill(erase=True)
            self.assertEqual(media.current_frame().pixelColor(0, 0).alpha(), 0)
        finally:
            media.stop()

    def test_grid_image_has_transparent_background(self):
        media = GridMedia(100, 80)
        try:
            image = media.current_frame()
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 255)
            self.assertEqual(image.pixelColor(1, 1).alpha(), 0)
        finally:
            media.stop()

    def test_detects_known_grid_spacing(self):
        pixels = np.full((240, 320, 3), 255, dtype=np.uint8)
        pixels[:, 9::40, :] = 0
        pixels[15::60, :, :] = 0
        image = QImage(
            pixels.tobytes(), 320, 240, 960, QImage.Format.Format_RGB888
        ).copy()
        detected = GridMedia.detect_parameters(image)
        self.assertIsNotNone(detected)
        spacing_x, spacing_y, _, _ = detected
        self.assertAlmostEqual(spacing_x, 40, delta=2)
        self.assertAlmostEqual(spacing_y, 60, delta=2)

    def test_detection_returns_none_for_blank_image(self):
        image = QImage(100, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.assertIsNone(GridMedia.detect_parameters(image))


class TestLayerManager(unittest.TestCase):
    def test_structural_and_media_callbacks_are_separate(self):
        manager = LayerManager()
        structural = []
        media_updates = []
        manager.subscribe_to_updates(lambda: structural.append(True))
        manager.subscribe_to_media_updates(lambda: media_updates.append(True))
        media = ImageMedia(QImage(4, 4, QImage.Format.Format_ARGB32))
        layer = Layer("test", media)
        manager.add(layer)
        structural.clear()
        media.frame_changed.emit()
        self.assertEqual(structural, [])
        self.assertEqual(media_updates, [True])

    def test_remove_stops_media(self):
        class TrackMedia(LayerMedia):
            def __init__(self):
                super().__init__()
                self.stopped = False
                self.image = QImage(2, 2, QImage.Format.Format_ARGB32)

            def frame_at(self, time_ms=0):
                return self.image

            def copy(self):
                return TrackMedia()

            def stop(self):
                self.stopped = True

        media = TrackMedia()
        manager = LayerManager()
        manager.add(Layer("tracked", media))
        manager.remove(0)
        self.assertTrue(media.stopped)

    def test_unsubscribe_removes_callbacks(self):
        manager = LayerManager()
        callback = lambda: None
        manager.subscribe_to_updates(callback)
        manager.subscribe_to_media_updates(callback)
        manager.unsubscribe_from_updates(callback)
        manager.unsubscribe_from_media_updates(callback)
        self.assertNotIn(callback, manager.notify_update_callbacks)
        self.assertNotIn(callback, manager.notify_media_callbacks)


class TestFrame(unittest.TestCase):
    def test_layer_mask_reveals_image_through_transparent_mask_area(self):
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        mask = MaskMedia(4, 4)
        target = Layer("Image", image)
        mask_layer = Layer("Mask", mask)
        target.mask_layer_id = mask_layer.layer_id
        try:
            mask.paint_line(0, 0, 3, 0, 1)
            rendered = Frame(4, 4).draw([target], [mask_layer])
            self.assertEqual(rendered.pixelColor(1, 0).red(), 0)
            self.assertEqual(rendered.pixelColor(1, 1).red(), 255)
            self.assertEqual(target.media.current_frame().pixelColor(1, 1).red(), 255)
        finally:
            mask.stop()

    def test_render_states_has_black_background(self):
        frame = Frame(20, 20)
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        state = RenderState(image, QPoint(0, 0), (1.0, 1.0), 1.0, 1.0)
        rendered = frame.render_states([state])
        self.assertEqual(rendered.pixelColor(19, 19), QColor("black"))
        self.assertEqual(rendered.pixelColor(1, 1).red(), 255)

    def test_render_states_uses_configured_background(self):
        frame = Frame(4, 4, background_color=QColor("#203040"))
        rendered = frame.render_states([])
        self.assertEqual(rendered.pixelColor(3, 3), QColor("#203040"))

    def test_render_states_clips_outside_frame(self):
        frame = Frame(10, 10)
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("blue"))
        state = RenderState(image, QPoint(8, 8), (1.0, 1.0), 1.0, 1.0)
        rendered = frame.render_states([state])
        self.assertEqual(rendered.size(), QSize(10, 10))
        self.assertEqual(rendered.pixelColor(9, 9).blue(), 255)

    def test_alpha_is_applied(self):
        frame = Frame(4, 4)
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        state = RenderState(image, QPoint(), (1.0, 1.0), 0.5, 1.0)
        rendered = frame.render_states([state])
        self.assertLess(rendered.pixelColor(1, 1).red(), 255)
        self.assertGreater(rendered.pixelColor(1, 1).red(), 0)


if __name__ == "__main__":
    unittest.main()
