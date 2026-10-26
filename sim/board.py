"""Top-down dartboard texture built from the core.py geometry."""
import functools
import math

import cv2
import numpy as np

from core import SECTORS

# Radii in millimetres, identical to core.score_point.
BULL_RADIUS = 6.35
OUTER_BULL_RADIUS = 15.9
TREBLE_INNER = 99.0
TREBLE_OUTER = 107.0
DOUBLE_INNER = 162.0
DOUBLE_OUTER = 170.0
NUMBER_RING_OUTER = 225.0
RING_EDGES = (BULL_RADIUS, OUTER_BULL_RADIUS, TREBLE_INNER, TREBLE_OUTER, DOUBLE_INNER, DOUBLE_OUTER)

# Half-width of the texture in mm. The texture covers [-HALF_EXTENT, HALF_EXTENT]^2.
HALF_EXTENT = 250.0
DEFAULT_PX_PER_MM = 4.0
WIRE_WIDTH_MM = 1.0

# BGR colours.
BLACK = (24, 24, 24)
CREAM = (176, 216, 232)
RED = (38, 36, 190)
GREEN = (58, 132, 34)
WIRE = (190, 192, 196)
NUMBER_RING = (28, 28, 30)
NUMBER_TEXT = (235, 235, 235)
SURROUND = (36, 34, 40)


def mm_to_texture_matrix(px_per_mm=DEFAULT_PX_PER_MM):
    """3x3 matrix mapping board mm (x, y, 1) to texture pixel coordinates.

    Pixel (col, row) has its centre at mm ((col + 0.5) / ppm - HALF_EXTENT, ...).
    """
    return np.array(
        [
            [px_per_mm, 0.0, HALF_EXTENT * px_per_mm - 0.5],
            [0.0, px_per_mm, HALF_EXTENT * px_per_mm - 0.5],
            [0.0, 0.0, 1.0],
        ]
    )


def _sector_index(x, y):
    """Vectorised sector index (0..19, into SECTORS) using core.score_point's rule."""
    degrees = np.degrees(np.arctan2(x, -y))
    return np.floor((degrees + 9.0) / 18.0).astype(np.int64) % 20


@functools.lru_cache(maxsize=4)
def board_texture(px_per_mm=DEFAULT_PX_PER_MM):
    """Render the board texture as a BGR uint8 array (read-only, cached).

    Includes black/cream singles, red/green doubles and trebles, ~1 mm wires,
    a number ring out to r=225 mm and a dark surround beyond it.
    """
    if px_per_mm < 4:
        raise ValueError('Board texture needs at least 4 px/mm')
    size = int(round(2 * HALF_EXTENT * px_per_mm))
    centres = (np.arange(size) + 0.5) / px_per_mm - HALF_EXTENT
    x, y = np.meshgrid(centres, centres)
    r = np.hypot(x, y)
    sector = _sector_index(x, y)
    # Sector 20 (index 0) is black with red rings; colours alternate around the board.
    dark_sector = (sector % 2) == 0

    image = np.empty((size, size, 3), np.uint8)
    image[:] = SURROUND
    image[r <= NUMBER_RING_OUTER] = NUMBER_RING

    singles = r <= DOUBLE_OUTER
    image[singles & dark_sector] = BLACK
    image[singles & ~dark_sector] = CREAM

    ring = ((r >= TREBLE_INNER) & (r <= TREBLE_OUTER)) | ((r >= DOUBLE_INNER) & (r <= DOUBLE_OUTER))
    image[ring & dark_sector] = RED
    image[ring & ~dark_sector] = GREEN

    image[r <= OUTER_BULL_RADIUS] = GREEN
    image[r <= BULL_RADIUS] = RED

    # Wires: circles at every ring edge plus radial spokes between the outer bull and the double.
    half_wire = WIRE_WIDTH_MM / 2
    wire = np.zeros_like(r, dtype=bool)
    for edge in RING_EDGES:
        wire |= np.abs(r - edge) < half_wire
    degrees = np.degrees(np.arctan2(x, -y))
    offset = np.mod(degrees + 9.0, 18.0)
    angular = np.minimum(offset, 18.0 - offset)
    spoke = (r * np.sin(np.radians(angular)) < half_wire) & (r > OUTER_BULL_RADIUS) & (r <= DOUBLE_OUTER)
    wire |= spoke
    image[wire] = WIRE

    _draw_numbers(image, px_per_mm)
    image.setflags(write=False)
    return image


def _draw_numbers(image, px_per_mm):
    """Upright sector numbers centred at r ~ 197 mm in the number ring."""
    radius = (DOUBLE_OUTER + NUMBER_RING_OUTER) / 2
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 0.075 * px_per_mm * 3.2  # ~24 mm tall glyphs
    thickness = max(1, int(round(px_per_mm * 0.9)))
    for index, number in enumerate(SECTORS):
        angle = math.radians(index * 18)
        x = radius * math.sin(angle)
        y = -radius * math.cos(angle)
        text = str(number)
        (width, height), _ = cv2.getTextSize(text, font, scale, thickness)
        col = (x + HALF_EXTENT) * px_per_mm - width / 2
        row = (y + HALF_EXTENT) * px_per_mm + height / 2
        cv2.putText(image, text, (int(round(col)), int(round(row))), font, scale,
                    NUMBER_TEXT, thickness, cv2.LINE_AA)
