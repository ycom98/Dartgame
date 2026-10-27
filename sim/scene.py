"""Render synthetic camera frames of a dartboard with darts and known truth.

A frame is: the board texture warped through the camera's plane homography,
optional hard dart shadows on the board plane, the darts themselves (drawn
far-to-near), then optional photometric degradations (brightness/contrast,
blur, Gaussian noise, JPEG).

Synthetic frames are a measurement aid only; they do not prove real accuracy.
"""
import functools
import math
from dataclasses import dataclass, field, replace
from typing import Optional

import cv2
import numpy as np

from core import near_wire, score_point
from sim.board import DEFAULT_PX_PER_MM, board_texture, mm_to_texture_matrix

# Calibration points expected by vision.TARGETS, in order: 20, 6, 3, 11 on the outer double edge.
CALIBRATION_BOARD_POINTS = np.array([[0.0, -170.0], [170.0, 0.0], [0.0, 170.0], [-170.0, 0.0]])

WALL_COLOUR = (150, 160, 168)

# Dart dimensions in mm, measured along the axis from the visible tip.
POINT_LENGTH = 22.0
POINT_DIAMETER = 2.3
BARREL_LENGTH = 47.0
BARREL_DIAMETER = 7.0
SHAFT_DIAMETER = 5.0
FLIGHT_LENGTH = 38.0
FLIGHT_WIDTH = 38.0
FLIGHT_OVERLAP = 8.0  # shaft end inserted into the flight

POINT_COLOUR = (172, 174, 180)
BARREL_COLOURS = [(70, 70, 76), (96, 98, 104), (52, 54, 58)]
SHAFT_COLOURS = [(30, 30, 30), (220, 220, 220), (40, 40, 170), (160, 90, 30)]
FLIGHT_COLOURS = [(30, 30, 200), (200, 120, 20), (30, 180, 230), (40, 160, 40), (230, 230, 230), (20, 20, 20)]


@dataclass
class Dart:
    """One dart. The tip sits on the board plane at (x, y, 0).

    length:  total protrusion from the board in mm (110-140 for real darts).
    tilt:    angle between the dart axis and the board normal, degrees.
    azimuth: direction the tail leans in the board plane, degrees; 0 = toward
             the 20 (up, -y), 90 = toward the 6 (+x).
    spin:    rotation of the flights about the axis, degrees.
    """

    x: float
    y: float
    length: float = 125.0
    tilt: float = 15.0
    azimuth: float = 0.0
    spin: float = 0.0
    barrel_colour: tuple = BARREL_COLOURS[0]
    shaft_colour: tuple = SHAFT_COLOURS[0]
    flight_colour: tuple = FLIGHT_COLOURS[0]

    @property
    def axis(self):
        """Unit vector from tip to tail in board coordinates (+z toward thrower)."""
        tilt = math.radians(self.tilt)
        azimuth = math.radians(self.azimuth)
        return np.array([
            math.sin(tilt) * math.sin(azimuth),
            -math.sin(tilt) * math.cos(azimuth),
            math.cos(tilt),
        ])

    @property
    def tip(self):
        return np.array([self.x, self.y, 0.0])

    def at(self, s):
        """Board-frame 3D point at distance s along the axis from the tip."""
        return self.tip + s * self.axis

    def label(self):
        result = score_point(float(self.x), float(self.y))
        return {
            'x': float(self.x),
            'y': float(self.y),
            'label': result['label'],
            'value': result['value'],
            'multiplier': result['multiplier'],
            'score': result['score'],
            'near_wire': near_wire(float(self.x), float(self.y)),
        }


@dataclass
class Degradation:
    """Photometric and calibration degradations.

    brightness/contrast: fixed multipliers (1.0 = unchanged).
    brightness_jitter:   a harness draws brightness uniformly in 1 +/- jitter.
    shadow:              light travel direction (board frame) for a hard shadow, or None.
    click_noise:         sigma in px added to calibration clicks by the harness.
    """

    noise_sigma: float = 0.0
    blur_sigma: float = 0.0
    jpeg_quality: Optional[int] = None
    brightness: float = 1.0
    contrast: float = 1.0
    brightness_jitter: float = 0.0
    shadow: Optional[tuple] = None
    shadow_strength: float = 0.45
    click_noise: float = 0.0

    def with_options(self, **changes):
        return replace(self, **changes)


PROFILES = {
    'ideal': Degradation(),
    'realistic': Degradation(
        noise_sigma=4.0,
        blur_sigma=1.0,
        jpeg_quality=80,
        brightness_jitter=0.15,
        click_noise=2.0,
    ),
}

# Light from above and slightly in front of / left of the board, travelling down and into it.
DEFAULT_LIGHT = (0.25, 0.55, -1.0)


def random_dart(rng, max_radius=170.0, min_radius=0.0):
    """Draw a plausible dart: tip uniform by area, mostly tail-up, tilt 5-30 deg."""
    radius = math.sqrt(rng.uniform(min_radius ** 2 / max_radius ** 2, 1.0)) * max_radius
    angle = rng.uniform(0.0, 2.0 * math.pi)
    if rng.uniform() < 0.8:
        azimuth = float(rng.normal(0.0, 35.0))
    else:
        azimuth = float(rng.uniform(-180.0, 180.0))
    return Dart(
        x=float(radius * math.sin(angle)),
        y=float(-radius * math.cos(angle)),
        length=float(rng.uniform(110.0, 140.0)),
        tilt=float(rng.uniform(5.0, 30.0)),
        azimuth=azimuth,
        spin=float(rng.uniform(0.0, 90.0)),
        barrel_colour=BARREL_COLOURS[int(rng.integers(len(BARREL_COLOURS)))],
        shaft_colour=SHAFT_COLOURS[int(rng.integers(len(SHAFT_COLOURS)))],
        flight_colour=FLIGHT_COLOURS[int(rng.integers(len(FLIGHT_COLOURS)))],
    )


# -- geometry of the dart body ----------------------------------------------------


def _perpendiculars(axis, spin_degrees):
    """Two unit vectors perpendicular to axis and each other, rotated by spin."""
    helper = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    first = np.cross(axis, helper)
    first /= np.linalg.norm(first)
    second = np.cross(axis, first)
    spin = math.radians(spin_degrees)
    e1 = math.cos(spin) * first + math.sin(spin) * second
    e2 = -math.sin(spin) * first + math.cos(spin) * second
    return e1, e2


def _dart_parts(dart):
    """Body parts as ('cylinder', s0, s1, diameter, colour) or ('polygon', points3d, colour)."""
    shaft_start = POINT_LENGTH + BARREL_LENGTH
    flight_start = dart.length - FLIGHT_LENGTH
    shaft_end = flight_start + FLIGHT_OVERLAP
    parts = [('cylinder', 0.0, POINT_LENGTH, POINT_DIAMETER, POINT_COLOUR)]
    # Barrel drawn as bands to suggest knurling.
    bands = 5
    band_length = BARREL_LENGTH / bands
    for index in range(bands):
        colour = dart.barrel_colour if index % 2 == 0 else tuple(min(255, c + 30) for c in dart.barrel_colour)
        start = POINT_LENGTH + index * band_length
        parts.append(('cylinder', start, start + band_length, BARREL_DIAMETER, colour))
    if shaft_end > shaft_start:
        parts.append(('cylinder', shaft_start, shaft_end, SHAFT_DIAMETER, dart.shaft_colour))
    e1, e2 = _perpendiculars(dart.axis, dart.spin)
    half = FLIGHT_WIDTH / 2
    outline = [(0.0, 0.0), (14.0, half), (FLIGHT_LENGTH, half), (FLIGHT_LENGTH, -half), (14.0, -half)]
    for direction, shade in ((e1, 1.0), (e2, 0.78)):
        points = np.array([dart.at(flight_start + s) + w * direction for s, w in outline])
        colour = tuple(int(c * shade) for c in dart.flight_colour)
        parts.append(('polygon', points, colour))
    return parts


def _part_midpoint(dart, part):
    if part[0] == 'cylinder':
        return dart.at((part[1] + part[2]) / 2)
    return part[1].mean(axis=0)


def _cylinder_outline(camera, dart, s0, s1, diameter):
    """Image-space quad for a cylinder segment (silhouette approximation)."""
    ends = np.array([dart.at(s0), dart.at(s1)])
    pixels = camera.project(ends)
    depths = camera.depth(ends)
    widths = camera.f * diameter / depths
    direction = pixels[1] - pixels[0]
    norm = np.linalg.norm(direction)
    if norm < 1e-6:
        # Axis points at the lens: draw a disc instead.
        return None, pixels[1], float(widths.max()) / 2
    normal = np.array([-direction[1], direction[0]]) / norm
    quad = np.array([
        pixels[0] + normal * widths[0] / 2,
        pixels[1] + normal * widths[1] / 2,
        pixels[1] - normal * widths[1] / 2,
        pixels[0] - normal * widths[0] / 2,
    ])
    return quad, pixels[1], float(widths[1]) / 2


SUBPIXEL_SHIFT = 4
SUBPIXEL_SCALE = 1 << SUBPIXEL_SHIFT


def _fixed(points):
    return np.round(np.asarray(points) * SUBPIXEL_SCALE).astype(np.int32)


def _draw_dart(image, camera, dart):
    parts = _dart_parts(dart)
    parts.sort(key=lambda part: -float(camera.depth(np.atleast_2d(_part_midpoint(dart, part)))[0]))
    for part in parts:
        if part[0] == 'cylinder':
            _, s0, s1, diameter, colour = part
            quad, end, radius = _cylinder_outline(camera, dart, s0, s1, diameter)
            if quad is not None:
                cv2.fillConvexPoly(image, _fixed(quad), colour, cv2.LINE_AA, SUBPIXEL_SHIFT)
            centre = tuple(int(v) for v in _fixed(end))
            cv2.circle(image, centre, max(1, int(round(radius * SUBPIXEL_SCALE))), colour, -1,
                       cv2.LINE_AA, SUBPIXEL_SHIFT)
        else:
            _, points, colour = part
            pixels = camera.project(points)
            cv2.fillPoly(image, [_fixed(pixels)], colour, cv2.LINE_AA, SUBPIXEL_SHIFT)


def dart_silhouette(camera, darts, include_point=True):
    """uint8 mask (255 = covered, anti-aliased edges) of the darts' outlines in the image.

    include_point=False leaves out the steel point (used to ask whether a dart's own
    barrel, shaft or flight hides its tip).
    """
    mask = np.zeros((camera.height, camera.width), np.uint8)
    for dart in darts:
        parts = _dart_parts(dart)
        if not include_point:
            parts = parts[1:]
        for part in parts:
            if part[0] == 'cylinder':
                _, s0, s1, diameter, _ = part
                quad, end, radius = _cylinder_outline(camera, dart, s0, s1, diameter)
                if quad is not None:
                    cv2.fillConvexPoly(mask, _fixed(quad), 255, cv2.LINE_AA, SUBPIXEL_SHIFT)
                centre = tuple(int(v) for v in _fixed(end))
                cv2.circle(mask, centre, max(1, int(round(radius * SUBPIXEL_SCALE))), 255, -1,
                           cv2.LINE_AA, SUBPIXEL_SHIFT)
            else:
                cv2.fillPoly(mask, [_fixed(camera.project(part[1]))], 255, cv2.LINE_AA, SUBPIXEL_SHIFT)
    return mask


def add_speckles(image, camera, rng, count, radius_mm=(0.8, 2.0), max_board_radius=170.0):
    """Draw count small discs (debris, chalk, flecks; random colours) on the board plane, in place.

    By default each disc is smaller than a dart fragment (radius 0.8-2 mm, at most ~13 mm2; blur
    and the warp make it look up to about twice that). Returns the (x, y, radius) of each speck in mm.
    """
    specks = []
    for _ in range(count):
        radius = math.sqrt(rng.uniform(0.0, 1.0)) * max_board_radius
        angle = rng.uniform(0.0, 2.0 * math.pi)
        x, y = radius * math.sin(angle), -radius * math.cos(angle)
        size = float(rng.uniform(*radius_mm))
        outline = np.array([[x + size * math.cos(t), y + size * math.sin(t)]
                            for t in np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False)])
        colour = tuple(int(v) for v in rng.integers(0, 256, 3))
        cv2.fillPoly(image, [_fixed(camera.project_plane(outline))], colour, cv2.LINE_AA, SUBPIXEL_SHIFT)
        specks.append((float(x), float(y), size))
    return specks


def _shadow_mask(camera, darts, light):
    """Mask of board pixels in hard shadow of the darts for a directional light."""
    light = np.asarray(light, dtype=np.float64)
    if light[2] >= 0:
        raise ValueError('Shadow light must travel toward the board (negative z)')
    mask = np.zeros((camera.height, camera.width), np.uint8)

    def to_plane(points):
        points = np.atleast_2d(points)
        steps = -points[:, 2] / light[2]
        return points[:, :2] + steps[:, None] * light[:2]

    for dart in darts:
        for part in _dart_parts(dart):
            if part[0] == 'cylinder':
                _, s0, s1, diameter, _ = part
                ends = to_plane(np.array([dart.at(s0), dart.at(s1)]))
                direction = ends[1] - ends[0]
                norm = np.linalg.norm(direction)
                if norm < 1e-6:
                    continue
                normal = np.array([-direction[1], direction[0]]) / norm * diameter / 2
                quad = np.array([ends[0] + normal, ends[1] + normal, ends[1] - normal, ends[0] - normal])
            else:
                quad = to_plane(part[1])
            pixels = camera.project_plane(quad)
            cv2.fillPoly(mask, [_fixed(pixels)], 255, cv2.LINE_AA, SUBPIXEL_SHIFT)
    return mask


# -- board image ------------------------------------------------------------------


def _camera_key(camera):
    return (tuple(camera.position), tuple(camera.look_at), camera.roll, camera.width,
            camera.height, camera.hfov, camera.k1)


@functools.lru_cache(maxsize=16)
def _board_image_cached(key, px_per_mm):
    from sim.camera import Camera

    camera = Camera(*key)
    texture = board_texture(px_per_mm)
    texture_from_mm = mm_to_texture_matrix(px_per_mm)
    if not camera.k1:
        image_from_texture = camera.plane_homography() @ np.linalg.inv(texture_from_mm)
        image = cv2.warpPerspective(texture, image_from_texture, (camera.width, camera.height),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                    borderValue=WALL_COLOUR)
    else:
        cols, rows = np.meshgrid(np.arange(camera.width, dtype=np.float64),
                                 np.arange(camera.height, dtype=np.float64))
        board = camera.image_to_plane(np.column_stack([cols.ravel(), rows.ravel()]))
        texture_points = np.column_stack([board, np.ones(len(board))]) @ texture_from_mm.T
        map_x = texture_points[:, 0].reshape(cols.shape).astype(np.float32)
        map_y = texture_points[:, 1].reshape(cols.shape).astype(np.float32)
        image = cv2.remap(texture, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                          borderValue=WALL_COLOUR)
    image.setflags(write=False)
    return image


def board_image(camera, px_per_mm=DEFAULT_PX_PER_MM):
    """The empty board as seen by camera (cached, read-only)."""
    return _board_image_cached(_camera_key(camera), px_per_mm)


# -- rendering --------------------------------------------------------------------


def render_clean(camera, darts=(), shadow=None, shadow_strength=0.45, px_per_mm=DEFAULT_PX_PER_MM):
    """Board plus darts (and an optional hard shadow), without photometric degradation."""
    image = board_image(camera, px_per_mm).copy()
    darts = list(darts)
    if shadow is not None and darts:
        mask = _shadow_mask(camera, darts, shadow).astype(np.float32) / 255.0
        factor = 1.0 - shadow_strength * mask
        image = np.clip(image.astype(np.float32) * factor[:, :, None] + 0.5, 0, 255).astype(np.uint8)
    # Nearest-last: sort by depth of the dart's middle.
    darts.sort(key=lambda dart: -float(camera.depth(np.atleast_2d(dart.at(dart.length / 2)))[0]))
    for dart in darts:
        _draw_dart(image, camera, dart)
    return image


def photometric(image, degradation, brightness=None):
    """Deterministic part of the degradation: brightness/contrast, then blur.

    brightness overrides degradation.brightness (used for per-trial jitter).
    """
    brightness = degradation.brightness if brightness is None else brightness
    out = image
    if brightness != 1.0 or degradation.contrast != 1.0:
        work = out.astype(np.float32)
        work = (work - 128.0) * degradation.contrast + 128.0
        work *= brightness
        out = np.clip(work + 0.5, 0, 255).astype(np.uint8)
    if degradation.blur_sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), degradation.blur_sigma)
    return out


def sensor(image, degradation, rng):
    """Per-frame part of the degradation: Gaussian noise, then JPEG.

    Returns (frame, encoded_jpeg_bytes_or_None).
    """
    out = image
    if degradation.noise_sigma > 0:
        # OpenCV's generator is ~4x faster than numpy here; seed it from rng so output stays deterministic.
        cv2.setRNGSeed(int(rng.integers(0, 2 ** 31 - 1)))
        noise = np.empty(out.shape, np.int16)
        sigma = float(degradation.noise_sigma)
        cv2.randn(noise, (0.0,) * out.shape[2], (sigma,) * out.shape[2])
        out = cv2.add(out, noise, dtype=cv2.CV_8U)
    encoded = None
    if degradation.jpeg_quality is not None:
        ok, data = cv2.imencode('.jpg', out, [cv2.IMWRITE_JPEG_QUALITY, int(degradation.jpeg_quality)])
        if not ok:
            raise RuntimeError('JPEG encoding failed')
        encoded = data.tobytes()
        out = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return out, encoded


def degrade(image, degradation, rng, brightness=None):
    """Apply all degradations. Returns (frame, encoded_jpeg_bytes_or_None)."""
    return sensor(photometric(image, degradation, brightness), degradation, rng)


@dataclass
class SceneResult:
    frame: np.ndarray
    calibration_points: np.ndarray  # (4, 2) image points of 20, 6, 3, 11 at r=170
    labels: list = field(default_factory=list)
    encoded: Optional[bytes] = None  # JPEG bytes when the degradation includes JPEG


def calibration_points(camera):
    return camera.project_plane(CALIBRATION_BOARD_POINTS).astype(np.float32)


def render_scene(camera, darts=(), degradation=None, seed=0, px_per_mm=DEFAULT_PX_PER_MM):
    """Render one frame with ground truth.

    Returns SceneResult(frame, calibration_points, labels, encoded). Labels are
    one dict per dart (tip x/y, score_point label/value/multiplier, near_wire).
    Deterministic for a given seed.
    """
    degradation = degradation or Degradation()
    rng = np.random.default_rng(seed)
    clean = render_clean(camera, darts, degradation.shadow, degradation.shadow_strength, px_per_mm)
    brightness = degradation.brightness
    if degradation.brightness_jitter:
        brightness *= float(rng.uniform(1 - degradation.brightness_jitter, 1 + degradation.brightness_jitter))
    frame, encoded = degrade(clean, degradation, rng, brightness)
    return SceneResult(frame, calibration_points(camera), [dart.label() for dart in darts], encoded)
