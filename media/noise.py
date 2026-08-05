from math import hypot

import numpy as np


class NoiseField:
    def __init__(self, width: int, height: int, noise_scale: float):
        self.width = width
        self.height = height
        self.noise_scale = noise_scale
        self._x, self._y = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )

    def render(self, phase: float, direction: tuple[float, float]):
        direction_x, direction_y = direction
        length = hypot(direction_x, direction_y)
        if length == 0.0:
            direction_x, direction_y = 1.0, 0.0
        else:
            direction_x /= length
            direction_y /= length
        sample_x = self._x * self.noise_scale + phase * direction_x
        sample_y = self._y * self.noise_scale + phase * direction_y
        cell_x = np.floor(sample_x).astype(np.int32)
        cell_y = np.floor(sample_y).astype(np.int32)
        frac_x = sample_x - cell_x
        frac_y = sample_y - cell_y

        def lattice(ix, iy):
            values = np.sin(ix * 127.1 + iy * 311.7) * 43758.5453
            return values - np.floor(values)

        smooth_x = frac_x * frac_x * (3.0 - 2.0 * frac_x)
        smooth_y = frac_y * frac_y * (3.0 - 2.0 * frac_y)
        top = lattice(cell_x, cell_y) * (1.0 - smooth_x)
        top += lattice(cell_x + 1, cell_y) * smooth_x
        bottom = lattice(cell_x, cell_y + 1) * (1.0 - smooth_x)
        bottom += lattice(cell_x + 1, cell_y + 1) * smooth_x
        return top * (1.0 - smooth_y) + bottom * smooth_y
