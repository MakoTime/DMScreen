"""Portable, self-contained project archive support."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint
from PySide6.QtGui import QColor, QImage

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
from constants import APP_VERSION

PROJECT_VERSION = 2


def _migrate_manifest(manifest):
    """Upgrade a project manifest to the current archive schema."""
    if not isinstance(manifest, dict):
        raise ValueError("Invalid DMScreen project manifest")
    version = manifest.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Invalid DMScreen project version")
    if version > PROJECT_VERSION:
        raise ValueError("Unsupported DMScreen project version")

    while version < PROJECT_VERSION:
        migration = PROJECT_MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"No migration exists for DMScreen project version {version}"
            )
        manifest = migration(manifest)
        next_version = manifest.get("version")
        if next_version != version + 1:
            raise ValueError("Invalid DMScreen project migration")
        version = next_version
    return manifest


def _migrate_v1_to_v2(manifest):
    manifest = dict(manifest)
    manifest["version"] = 2
    manifest.setdefault(
        "player_view",
        {"zoom": 1.0, "pan_x": 0, "pan_y": 0},
    )
    return manifest


PROJECT_MIGRATIONS = {1: _migrate_v1_to_v2}


def save_project(
    path,
    frame,
    layer_manager: LayerManager,
    scene_name=None,
    player_view=None,
):
    player_view = player_view or {"zoom": 1.0, "pan_x": 0, "pan_y": 0}
    manifest = {
        "version": PROJECT_VERSION,
        "app_version": APP_VERSION,
        "scene_name": scene_name,
        "player_view": {
            "zoom": float(player_view.get("zoom", 1.0)),
            "pan_x": int(player_view.get("pan_x", 0)),
            "pan_y": int(player_view.get("pan_y", 0)),
        },
        "frame": {
            "width": frame.size.width(),
            "height": frame.size.height(),
            "background": frame.background_color.name(QColor.NameFormat.HexArgb),
        },
        "layers": [],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, layer in enumerate(layer_manager.layers):
            media_data = _serialize_media(layer.media, index, archive)
            manifest["layers"].append(
                {
                    "name": layer.name,
                    "visible": layer.visible,
                    "player_visible": layer.player_visible,
                    "offset": [layer.offset.x(), layer.offset.y()],
                    "scale": list(layer.scale),
                    "alpha": layer.alpha,
                    "layer_id": layer.layer_id,
                    "mask_layer_id": layer.mask_layer_id,
                    "media": media_data,
                }
            )
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2).encode("utf-8"),
        )


def load_project(path, include_metadata=False):
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        manifest = _migrate_manifest(manifest)
        frame = manifest["frame"]
        layers = [
            _deserialize_layer(data, archive, frame["width"], frame["height"])
            for data in manifest["layers"]
        ]
    if include_metadata:
        return (
            frame,
            layers,
            manifest.get("scene_name"),
            manifest.get("player_view", {"zoom": 1.0, "pan_x": 0, "pan_y": 0}),
        )
    return frame, layers


def _serialize_media(media, index, archive):
    if media is None:
        return {"type": "none"}
    if isinstance(media, GridMedia):
        return {
            "type": "grid",
            "width": media.width,
            "height": media.height,
            "spacing_x": media.spacing_x,
            "spacing_y": media.spacing_y,
            "offset_x": media.offset_x,
            "offset_y": media.offset_y,
            "line_width": media.line_width,
            "color": media.color.name(QColor.NameFormat.HexArgb),
        }
    if isinstance(media, AnimationMedia):
        return {
            "type": "animation",
            "width": media.width,
            "height": media.height,
            "speed": media.speed,
            "noise_scale": media.noise_scale,
            "direction": list(media.direction),
            "color_a": media.color_a.name(QColor.NameFormat.HexArgb),
            "color_b": media.color_b.name(QColor.NameFormat.HexArgb),
            "transparent_b": media.transparent_b,
        }
    if isinstance(media, GifMedia):
        return _serialize_file_media(media, index, archive, "gif")
    if isinstance(media, VideoMedia):
        return _serialize_file_media(media, index, archive, "video")
    if isinstance(media, MaskMedia):
        return {
            "type": "mask",
            "brush_size": media.brush_size,
            "auto_fill": media.auto_fill,
            "asset": _write_image(media.current_frame(), index, archive),
        }
    if isinstance(media, DrawMedia):
        return {
            "type": "draw",
            "brush_size": media.brush_size,
            "asset": _write_image(media.current_frame(), index, archive),
        }
    if isinstance(media, ImageMedia):
        return {
            "type": "image",
            "asset": _write_image(media.current_frame(), index, archive),
        }
    raise TypeError(f"Unsupported layer media: {type(media).__name__}")


def _serialize_file_media(media, index, archive, media_type):
    suffix = Path(media.file_path).suffix or (".gif" if media_type == "gif" else ".mp4")
    source = PurePosixPath(f"assets/layer_{index}{suffix}")
    with open(media.file_path, "rb") as source_file:
        archive.writestr(str(source), source_file.read())
    return {"type": media_type, "asset": str(source)}


def _write_image(image, index, archive):
    asset = f"assets/layer_{index}.png"
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError(f"Could not encode image asset: {asset}")
    buffer.close()
    archive.writestr(asset, bytes(data))
    return asset


def _deserialize_layer(data, archive, frame_width, frame_height):
    media = _deserialize_media(
        data["media"], archive, frame_width, frame_height
    )
    offset = data.get("offset", [0, 0])
    return Layer(
        data["name"],
        media,
        visible=data.get("visible", True),
        player_visible=data.get("player_visible", True),
        offset=QPoint(*offset),
        scale=tuple(data.get("scale", [1.0, 1.0])),
        alpha=data.get("alpha", 1.0),
        layer_id=data.get("layer_id"),
        mask_layer_id=data.get("mask_layer_id"),
    )


def _deserialize_media(data, archive, frame_width, frame_height):
    media_type = data["type"]
    if media_type == "none":
        return None
    if media_type == "grid":
        media = GridMedia(data["width"], data["height"])
        media.set_parameters(
            data["spacing_x"],
            data["spacing_y"],
            data["offset_x"],
            data["offset_y"],
            data["line_width"],
            QColor(data["color"]),
        )
        return media
    if media_type == "animation":
        media = AnimationMedia(data["width"], data["height"])
        media.set_parameters(
            QColor(data["color_a"]),
            QColor(data["color_b"]),
            data["transparent_b"],
            data["speed"],
            data["noise_scale"],
            data["direction"],
        )
        return media
    if media_type in ("gif", "video"):
        suffix = Path(data["asset"]).suffix
        path = _extract_temp_asset(archive, data["asset"], suffix)
        return GifMedia(path) if media_type == "gif" else VideoMedia(path)
    image = QImage.fromData(archive.read(data["asset"]), "PNG")
    if image.isNull():
        raise ValueError(f"Invalid image asset: {data['asset']}")
    if media_type == "mask":
        media = MaskMedia(
            image.width(), image.height(), data["auto_fill"], data["brush_size"]
        )
    elif media_type == "draw":
        media = DrawMedia(image.width(), image.height(), data["brush_size"])
    elif media_type == "image":
        media = ImageMedia()
    else:
        raise ValueError(f"Unsupported media type: {media_type}")
    media.set_image(image)
    return media


def _extract_temp_asset(archive, asset, suffix):
    import tempfile

    file_handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        file_handle.write(archive.read(asset))
    finally:
        file_handle.close()
    return file_handle.name
