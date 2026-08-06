from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage


@dataclass
class RenderState:
    image: QImage
    offset: QPoint
    scale: tuple[float, float]
    alpha: float
    render_scale: float
    mask_image: QImage | None = None
    image_array: np.ndarray | None = None
    mask_array: np.ndarray | None = None
    layer_name: str = ""
    layer_id: str = ""
    animation: object | None = None
