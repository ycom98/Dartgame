"""Camera pose and foot point from the four-point board calibration (pure functions).

The foot point is the perpendicular projection of the camera centre onto the
board plane. Off-plane parts of a dart project (through the camera) onto the
board plane on the side away from the foot point, so the dart tip is the blob
end nearer the foot point.

Model: square pixels, principal point at the image centre, unknown focal
length f. With G = K [r1 r2 t] (board mm -> image), the constraints
r1 . r2 = 0 and |r1| = |r2| are each linear in w = 1/f^2; we solve them in
least squares. Near-frontal views carry almost no perspective and make f
unobservable, so the solver falls back to an assumed horizontal FOV.

Board coordinates follow core.py (mm, +x right, +y down, +z toward the
thrower). Internally the decomposition uses the right-handed frame
(x, y, into the board); results are reported in the core.py convention.
"""
import math

import numpy as np

DEFAULT_CAMERA_HFOV = 70.0
FOCAL_RANGE = (0.4, 2.5)  # allowed f as a multiple of the image width
MIN_PERSPECTIVE = 0.05  # below this the board is too frontal to solve f
MOUNT_SIDE_DISTANCE = 2000.0
MOUNT_SIDES = {
    'top': (0.0, -MOUNT_SIDE_DISTANCE),
    'bottom': (0.0, MOUNT_SIDE_DISTANCE),
    'left': (-MOUNT_SIDE_DISTANCE, 0.0),
    'right': (MOUNT_SIDE_DISTANCE, 0.0),
}
BOARD_RADIUS = 170.0


def board_to_image_homography(H, scale, center):
    """G: board mm -> image px, from vision's H (image px -> warp px).

    Warp px = mm * scale + center, so G = inv(H) @ S.
    """
    S = np.array([[scale, 0.0, center], [0.0, scale, center], [0.0, 0.0, 1.0]])
    G = np.linalg.inv(np.asarray(H, dtype=np.float64)) @ S
    return G / G[2, 2]


def perspective_strength(G):
    """Relative depth change across the board (0 for a perfectly frontal view)."""
    G = G / G[2, 2]
    return BOARD_RADIUS * math.hypot(G[2, 0], G[2, 1])


def solve_focal(G, width, height):
    """Least-squares focal length (px) from r1 . r2 = 0 and |r1| = |r2|.

    Returns (f, details). f is None when the system has no positive solution.
    """
    s = float(width)
    normalise = np.array([[1 / s, 0.0, -width / 2 / s], [0.0, 1 / s, -height / 2 / s], [0.0, 0.0, 1.0]])
    A = normalise @ G
    A = A / np.linalg.norm(A[:, :2])
    h1, h2 = A[:, 0], A[:, 1]
    p = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    q = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    denominator = float(p @ p)
    details = {'perspective': round(perspective_strength(G), 4)}
    if denominator < 1e-18:
        return None, {**details, 'reason': 'degenerate homography'}
    w = -float(p @ q) / denominator
    if not math.isfinite(w) or w <= 0:
        return None, {**details, 'reason': 'no positive focal solution'}
    return math.sqrt(1.0 / w) * s, details


def pose_from_focal(G, f, width, height):
    """Recover R, t and the camera centre for a known focal length."""
    K = np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]])
    B = np.linalg.inv(K) @ G
    scale = (np.linalg.norm(B[:, 0]) + np.linalg.norm(B[:, 1])) / 2.0
    if scale <= 0 or not math.isfinite(scale):
        raise ValueError('Homography columns are degenerate')
    if B[2, 2] < 0:  # the board must lie in front of the camera
        scale = -scale
    r1, r2, t = B[:, 0] / scale, B[:, 1] / scale, B[:, 2] / scale
    R = np.column_stack([r1, r2, np.cross(r1, r2)])
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        raise ValueError('Calibration points imply a mirrored board')
    centre = -R.T @ t  # right-handed frame: z points into the board
    height_off_board = -float(centre[2])
    if height_off_board <= 0:
        raise ValueError('Camera would be behind the board')
    return {
        'R': R,
        't': t,
        'C': (float(centre[0]), float(centre[1]), height_off_board),
        'foot': (float(centre[0]), float(centre[1])),
        'height': height_off_board,
    }


def focal_from_hfov(width, hfov_degrees):
    return (width / 2.0) / math.tan(math.radians(hfov_degrees) / 2.0)


def estimate_pose(H, width, height, scale, center, camera_hfov=DEFAULT_CAMERA_HFOV):
    """Pose summary {f, C, foot, height, source, reason, perspective}. Never raises.

    source is 'solved' when f came from the homography, 'fallback' when the
    assumed HFOV was used, and foot/C are None if no pose could be recovered.
    """
    result = {'f': None, 'C': None, 'foot': None, 'height': None, 'source': 'fallback',
              'reason': None, 'perspective': None, 'camera_hfov': float(camera_hfov)}
    try:
        G = board_to_image_homography(H, scale, center)
        if not np.isfinite(G).all():
            raise ValueError('Calibration homography is not finite')
        f, details = solve_focal(G, width, height)
        result['perspective'] = details.get('perspective')
        reason = details.get('reason')
        if f is not None:
            low, high = FOCAL_RANGE[0] * width, FOCAL_RANGE[1] * width
            if details['perspective'] < MIN_PERSPECTIVE:
                reason = 'view too frontal to solve focal length (perspective %.3f)' % details['perspective']
            elif not low <= f <= high:
                reason = 'solved focal %.0f px outside [%.0f, %.0f]' % (f, low, high)
            else:
                result['source'] = 'solved'
        if result['source'] != 'solved':
            f = focal_from_hfov(width, camera_hfov)
            result['reason'] = reason
        pose = pose_from_focal(G, f, width, height)
        result.update({
            'f': round(float(f), 2),
            'C': [round(v, 2) for v in pose['C']],
            'foot': [round(v, 2) for v in pose['foot']],
            'height': round(pose['height'], 2),
        })
    except (ValueError, np.linalg.LinAlgError, ZeroDivisionError, OverflowError) as error:
        result.update({'f': None, 'C': None, 'foot': None, 'height': None, 'source': 'fallback',
                       'reason': 'pose could not be recovered: %s' % error})
    return result


def manual_pose(mount_side, base=None):
    """Override the foot point: 2 m out along the chosen side of the board."""
    if mount_side not in MOUNT_SIDES:
        raise ValueError('mount_side must be one of: ' + ', '.join(MOUNT_SIDES))
    pose = dict(base or {})
    pose.update({'foot': list(MOUNT_SIDES[mount_side]), 'source': 'manual', 'mount_side': mount_side})
    return pose


def direction_degrees(point):
    """Angle of a board point from the bull, degrees, 0 = toward the 20, clockwise."""
    return math.degrees(math.atan2(point[0], -point[1]))


def angle_difference(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)
