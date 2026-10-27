"""Pinhole camera for synthetic scenes.

Board coordinates (core.py convention): mm, +x right, +y down, +z out of the
board toward the thrower. That frame is left-handed, so internally the camera
works in a right-handed "world" frame W = (x, y, -z), where W.z points into
the board. Board-plane points (x, y, 0) are identical in both frames.

The camera frame is OpenCV's: +x right in the image, +y down, +z forward.
"""
import math
from dataclasses import dataclass

import numpy as np

# Standard mounts: camera position in board mm (z toward the thrower), looking at the bull.
MOUNTS = {
    'top': (0.0, -450.0, 500.0),
    'bottom': (0.0, 450.0, 500.0),
    'left': (-450.0, 0.0, 500.0),
    'right': (450.0, 0.0, 500.0),
    'steep-topleft': (-300.0, -500.0, 350.0),
    'near-frontal': (150.0, -200.0, 1200.0),
}

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_HFOV = 70.0


def hfov_from_diagonal(diagonal_degrees, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Horizontal FOV (degrees) of a pinhole camera with the given diagonal FOV and frame size."""
    half_diagonal = math.tan(math.radians(diagonal_degrees) / 2.0)
    return math.degrees(2.0 * math.atan(half_diagonal * width / math.hypot(width, height)))


# Ceiling mounts (M1-05d): the owner's basement (docs/DECISIONS.md #2). 7.5 ft (2286 mm) ceiling,
# bull at 1730 mm, phone about 30 mm below the ceiling, so the camera is 526 mm above the bull,
# centred left-right, at a distance from the wall, aimed at the bull.
CEILING_HEIGHT_ABOVE_BULL = 2286.0 - 30.0 - 1730.0
CEILING_DISTANCES = {
    'ceiling-0.5ft': 152.0,
    'ceiling-1.5ft': 457.0,  # the owner's planned mount
    'ceiling-2ft': 610.0,
    'ceiling-3ft': 914.0,
}
CEILING_MOUNTS = tuple(CEILING_DISTANCES)
MOUNTS.update({name: (0.0, -CEILING_HEIGHT_ABOVE_BULL, distance) for name, distance in CEILING_DISTANCES.items()})

# Samsung Galaxy S22 main camera at 1x, 1920x1080 video. Assumption: about 78 degrees diagonal
# (the 4:3 still frame is ~85 degrees; 16:9 video crops it to ~80, and video stabilisation
# crops a little more). That is ~70.4 degrees horizontal, ~43 degrees vertical.
S22_DIAGONAL_FOV = 78.0
S22_HFOV = hfov_from_diagonal(S22_DIAGONAL_FOV)
# Horizontal FOV per mount; mounts not listed use DEFAULT_HFOV.
MOUNT_HFOV = {name: S22_HFOV for name in CEILING_MOUNTS}


def board_to_world(points):
    """Board coordinates (x, y, z toward thrower) -> right-handed world (x, y, -z)."""
    points = np.asarray(points, dtype=np.float64)
    return points * np.array([1.0, 1.0, -1.0])


def _normalise(vector):
    return vector / np.linalg.norm(vector)


@dataclass
class Camera:
    """A pinhole camera with optional radial distortion (k1).

    position: camera centre in board mm (z toward the thrower).
    look_at:  point on/near the board the optical axis passes through.
    roll:     rotation about the optical axis in degrees (positive = clockwise in the image).
    """

    position: tuple
    look_at: tuple = (0.0, 0.0, 0.0)
    roll: float = 0.0
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    hfov: float = DEFAULT_HFOV
    k1: float = 0.0

    def __post_init__(self):
        centre = board_to_world(self.position)
        target = board_to_world(self.look_at)
        forward = _normalise(target - centre)
        board_down = np.array([0.0, 1.0, 0.0])
        if abs(float(forward @ board_down)) > 0.999:
            raise ValueError('Camera looks straight along the board y axis; choose another position')
        right = _normalise(np.cross(board_down, forward))
        down = np.cross(forward, right)
        if self.roll:
            angle = math.radians(self.roll)
            right, down = (
                math.cos(angle) * right + math.sin(angle) * down,
                -math.sin(angle) * right + math.cos(angle) * down,
            )
        self.R = np.vstack([right, down, forward])
        self.C_world = centre
        self.t = -self.R @ centre
        self.f = (self.width / 2.0) / math.tan(math.radians(self.hfov) / 2.0)
        self.K = np.array(
            [
                [self.f, 0.0, self.width / 2.0],
                [0.0, self.f, self.height / 2.0],
                [0.0, 0.0, 1.0],
            ]
        )

    # -- geometry -----------------------------------------------------------------

    @property
    def foot_point(self):
        """Perpendicular projection of the camera centre onto the board plane (mm)."""
        return float(self.position[0]), float(self.position[1])

    def plane_homography(self):
        """3x3 homography mapping board mm (x, y, 1) to undistorted image pixels."""
        G = self.K @ np.column_stack([self.R[:, 0], self.R[:, 1], self.t])
        return G / G[2, 2]

    def to_camera(self, points_board):
        """Board-frame 3D points (N, 3) -> camera-frame coordinates (N, 3)."""
        world = board_to_world(np.atleast_2d(points_board))
        return (self.R @ world.T).T + self.t

    def depth(self, points_board):
        """Distance along the optical axis for board-frame points (N,)."""
        return self.to_camera(points_board)[:, 2]

    def distort_normalised(self, xn, yn):
        if not self.k1:
            return xn, yn
        factor = 1.0 + self.k1 * (xn * xn + yn * yn)
        return xn * factor, yn * factor

    def undistort_normalised(self, xd, yd, iterations=8):
        if not self.k1:
            return xd, yd
        xu, yu = xd, yd
        for _ in range(iterations):
            factor = 1.0 + self.k1 * (xu * xu + yu * yu)
            xu, yu = xd / factor, yd / factor
        return xu, yu

    def project(self, points_board):
        """Board-frame 3D points (N, 3) -> image pixels (N, 2), including distortion."""
        cam = self.to_camera(points_board)
        if (cam[:, 2] <= 1e-6).any():
            raise ValueError('Point behind the camera')
        xn = cam[:, 0] / cam[:, 2]
        yn = cam[:, 1] / cam[:, 2]
        xd, yd = self.distort_normalised(xn, yn)
        u = self.f * xd + self.K[0, 2]
        v = self.f * yd + self.K[1, 2]
        return np.column_stack([u, v])

    def project_plane(self, points_xy):
        """Board-plane points (N, 2) in mm -> image pixels (N, 2)."""
        points_xy = np.atleast_2d(np.asarray(points_xy, dtype=np.float64))
        zeros = np.zeros((len(points_xy), 1))
        return self.project(np.hstack([points_xy, zeros]))

    def image_to_plane(self, pixels):
        """Image pixels (N, 2) -> board-plane mm (N, 2), inverting distortion and the homography."""
        pixels = np.atleast_2d(np.asarray(pixels, dtype=np.float64))
        xd = (pixels[:, 0] - self.K[0, 2]) / self.f
        yd = (pixels[:, 1] - self.K[1, 2]) / self.f
        xu, yu = self.undistort_normalised(xd, yd)
        undistorted = np.column_stack([xu * self.f + self.K[0, 2], yu * self.f + self.K[1, 2], np.ones(len(xu))])
        board = (np.linalg.inv(self.plane_homography()) @ undistorted.T).T
        return board[:, :2] / board[:, 2:3]

    def pixel_scale(self, point_board):
        """Approximate image pixels per mm for a small object at point_board."""
        return self.f / float(self.depth(np.atleast_2d(point_board))[0])


def camera_for_mount(name, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, hfov=None, roll=0.0, k1=0.0):
    """Camera at a standard mount, aimed at the bull. hfov defaults to the mount's (MOUNT_HFOV)."""
    if name not in MOUNTS:
        raise ValueError('Unknown mount %r; choose one of %s' % (name, ', '.join(MOUNTS)))
    if hfov is None:
        hfov = MOUNT_HFOV.get(name, DEFAULT_HFOV)
    return Camera(MOUNTS[name], (0.0, 0.0, 0.0), roll, width, height, hfov, k1)
