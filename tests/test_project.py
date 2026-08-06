import json
import os
import tempfile
import unittest
import zipfile

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from constants import APP_VERSION
from layer_manager import Layer, LayerManager
from layer_media import DrawMedia, GridMedia, ImageMedia
from project_io import load_project, save_project


class ProjectArchiveTests(unittest.TestCase):
    def test_round_trip_embeds_media_and_layer_metadata(self):
        image = QImage(32, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        manager = LayerManager()
        layer = Layer(
            "Map",
            ImageMedia(image),
            visible=False,
            player_visible=True,
            offset=QPoint(12, 8),
            scale=(1.25, 0.75),
            alpha=0.6,
        )
        manager.add(layer)
        manager.add(Layer("Ink", DrawMedia(32, 24)))
        manager.add(Layer("Grid", GridMedia(32, 24)))
        frame = type(
            "FrameData",
            (),
            {"size": image.size(), "background_color": QColor("#102030")},
        )()

        project_file = tempfile.NamedTemporaryFile(suffix=".dms", delete=False)
        project_file.close()
        try:
            save_project(project_file.name, frame, manager)
            loaded_frame, loaded_layers = load_project(project_file.name)
            with zipfile.ZipFile(project_file.name) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                assets = set(archive.namelist())
        finally:
            os.unlink(project_file.name)

        self.assertEqual(loaded_frame["width"], 32)
        self.assertEqual(loaded_frame["height"], 24)
        self.assertEqual(loaded_frame["background"], "#ff102030")
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["app_version"], APP_VERSION)
        self.assertEqual([item.name for item in loaded_layers], ["Map", "Ink", "Grid"])
        self.assertFalse(loaded_layers[0].visible)
        self.assertEqual(loaded_layers[0].offset, QPoint(12, 8))
        self.assertEqual(loaded_layers[0].scale, (1.25, 0.75))
        self.assertAlmostEqual(loaded_layers[0].alpha, 0.6)
        self.assertEqual(loaded_layers[0].media.current_frame().size(), image.size())
        self.assertIn(manifest["layers"][0]["media"]["asset"], assets)
        self.assertIn(manifest["layers"][1]["media"]["asset"], assets)


if __name__ == "__main__":
    unittest.main()
