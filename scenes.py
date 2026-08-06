from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from layer_manager import LayerManager
from screen import Frame


@dataclass
class Scene:
    name: str
    layer_manager: LayerManager = field(default_factory=LayerManager)
    frame: Frame = field(default_factory=lambda: Frame(1920, 1080))
    scene_id: str = field(default_factory=lambda: str(uuid4()))
    cache_path: Path | None = None
    linked_file_path: Path | None = None
    is_dirty: bool = False
    player_zoom: float = 1.0
    player_pan_x: int = 0
    player_pan_y: int = 0

    def __post_init__(self):
        self.layer_manager.subscribe_to_updates(self.mark_dirty)

    def mark_dirty(self):
        self.is_dirty = True

    def mark_clean(self):
        self.is_dirty = False

    @classmethod
    def create(cls, name: str, cache_root: Path):
        scene = cls(name)
        scene.cache_path = cache_root / f"{scene.scene_id}.dms"
        return scene
