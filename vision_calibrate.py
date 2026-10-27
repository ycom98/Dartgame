"""Automatic sub-pixel refinement of the four-click board calibration (M1-05c). Pure functions.

The four user clicks (20, 6, 3, 11 on the outer double edge) give an initial
homography, but each click is off by a pixel or two, which skews the whole
scoring map by 1-3 mm. The board itself has hundreds of edges at known
positions: the ring edges (outer bull, treble, double) and the 20 radial
sector wires. This module finds those edges in the image near where the click
calibration predicts them and re-fits the homography to all of them.

Steps:
  1. Sample model edge points: points on the ring circles (away from the
     spokes) and points on the 20 spokes (away from the rings), each with the
     board-plane normal of its edge.
  2. For each point, read the colour on both sides of the edge (well inside the
     neighbouring regions) and the colour profile across the edge, projected
     through the current homography. Projecting the profile onto the colour
     difference of the two sides gives a 0 -> 1 step whatever the board's
     colours (black/cream, red/green, ring/number ring). The edge is the
     sub-sample peak of its derivative. Weak, flat or reversed profiles are
     dropped.
  3. Fit the image -> board homography that puts the found edge points back on
     their model curves (point-to-curve distance, so an edge only constrains
     its normal direction), by Gauss-Newton with robust (Tukey) weights.
  4. Repeat 2-3 with a narrower search window (coarse to fine).
  5. Accept the result only when enough edges were found all around the board,
     their residual is small and the correction stays plausible; otherwise keep
     the click homography and say why.

No ground truth is used: only the calibration image and the clicks. The
thresholds were tuned on synthetic seed-1 scenes and must be checked on real
footage (M2).
"""
import math
import time

import cv2
import numpy as np

# Board geometry (mm), identical to core.score_point.
RING_EDGES = (15.9, 99.0, 107.0, 162.0, 170.0)
# Radii (inside, outside) where the regions on either side of each ring edge are sampled.
RING_SIDES = {15.9: (11.0, 22.0), 99.0: (93.0, 103.0), 107.0: (103.0, 113.0),
              162.0: (156.0, 166.0), 170.0: (166.0, 178.0)}
SPOKE_ANGLES = tuple(9.0 + 18.0 * k for k in range(20))  # degrees, 0 = toward the 20, clockwise
SECTOR_HALF_ANGLE = 9.0

# Sampling of model edge points (mm).
RING_STEP_MM = 3.0  # arc length between ring samples
SPOKE_STEP_MM = 2.0  # radial step along each spoke
SPOKE_RADII = (30.0, 168.0)  # inner spokes are too close together for a wide search
JUNCTION_CLEARANCE_MM = 3.0  # skip samples this close to a crossing edge

# Edge search.
WINDOWS_MM = (6.0, 3.0, 1.5)  # coarse to fine half-widths of the search across each edge
PROFILE_STEP_MM = 0.1
PRE_BLUR_SIGMA = 1.0  # px; smooths sensor noise and JPEG blocks before sampling
MIN_CONTRAST = 25.0  # colour distance (0-255 units) between the two sides of an edge
END_LEVELS = (0.35, 0.65)  # the profile must start below the first and end above the second
MIN_PEAK_SLOPE = 0.15  # per mm, of the normalised 0 -> 1 profile
# The wire itself: where the colour leaves the line between the two sides' colours, within
# WIRE_SEARCH_MM of the step. The step alone sits up to half a wire width off the wire's centre,
# toward the side whose colour differs more from the wire's.
WIRE_SEARCH_MM = 1.2
WIRE_MIN_CONTRAST = 12.0  # colour units above the lowest value in the search range

# Robust fit.
GAUSS_NEWTON_ITERATIONS = 8
TUKEY_C = 4.685
MIN_SIGMA_PX = 0.15

# Acceptance (otherwise the click homography is kept).
MIN_INLIERS = 300
MIN_INLIER_FRACTION = 0.4  # of all sampled edge points
MIN_RING_SECTORS = 10  # of 12 30-degree sectors with ring inliers
MIN_SPOKES = 14  # of 20 spokes with inliers
MAX_RESIDUAL_MM = 0.6  # RMS of inlier residuals
# Largest implied click error: how far (image px) the refined calibration puts the four click
# targets from where they were clicked. Measured in pixels because clicks are made in pixels: on a
# grazing view 2 px is ~10 mm of board. The limit is max(30 px, 10% of the board's radius in the
# image): sloppy clicks (6-8 px) still refine, while a fit that slipped by a sector (18 degrees,
# about 30% of the radius, 70-100 px) is rejected. (M1-05c used 12 px, which rejected half of the
# correct fits at 8 px click noise; QA D1.)
MIN_CLICK_ERROR_LIMIT_PX = 30.0
CLICK_ERROR_RADIUS_FRACTION = 0.10
CLICK_TARGETS_MM = np.array([[0.0, -170.0], [170.0, 0.0], [0.0, 170.0], [-170.0, 0.0]])  # 20, 6, 3, 11
MIN_POINTS_PER_BIN = 3


def clicks_report(reason, confidence='low'):
    """A report for a calibration that keeps the four-click homography (same keys as refine()'s)."""
    return {'method': 'clicks', 'confidence': confidence, 'reason': reason, 'warning': None, 'residual_mm': None,
            'edge_points': 0, 'sampled_points': 0, 'ring_sectors': 0, 'spokes': 0, 'click_offset_mm': None,
            'click_error_px': None, 'click_error_limit_px': None, 'seconds': None}


def click_error_limit(clicked):
    """Largest acceptable click error (px) for clicks at these image points (20, 6, 3, 11)."""
    radius = float(np.linalg.norm(clicked - clicked.mean(axis=0), axis=1).mean())
    return max(MIN_CLICK_ERROR_LIMIT_PX, CLICK_ERROR_RADIUS_FRACTION * radius)


def orientation_warning(clicked):
    """A warning when the 20 (first click) is not the topmost click in the image, else None.

    The board model is symmetric under rotation, so the fit cannot tell clicks in the wrong
    order (or a phone mounted sideways) from correct ones; the setup UI must say so (QA D6).
    """
    if int(np.argmin(clicked[:, 1])) != 0:
        return ('the 20 is not the topmost of the four points: check the click order (20, 6, 3, 11) '
                'and that the phone is upright')
    return None


def scaling(scale, center):
    """Board mm -> warp px."""
    return np.array([[scale, 0.0, center], [0.0, scale, center], [0.0, 0.0, 1.0]])


def apply(matrix, points):
    """Apply a 3x3 homography to (N, 2) points."""
    points = np.asarray(points, np.float64)
    mapped = points @ matrix[:, :2].T + matrix[:, 2]
    return mapped[:, :2] / mapped[:, 2:3]


def model_points():
    """Model edge samples: (points (N,2) mm, normals (N,2), kind (N,) 0 ring / 1 spoke, index (N,)).

    index is the ring radius position in RING_EDGES or the spoke number. normals point
    from the 'inside' region to the 'outside' one (outward for rings, clockwise for spokes).
    """
    points, normals, kinds, indices = [], [], [], []
    spokes = np.radians(SPOKE_ANGLES)
    for ring, radius in enumerate(RING_EDGES):
        count = int(round(2 * math.pi * radius / RING_STEP_MM))
        angles = np.arange(count) * (2 * math.pi / count)
        if radius > RING_EDGES[0]:
            gap = np.abs((angles[:, None] - spokes[None, :] + math.pi) % (2 * math.pi) - math.pi).min(axis=1)
            angles = angles[radius * np.sin(np.minimum(gap, math.pi / 2)) >= JUNCTION_CLEARANCE_MM]
        direction = np.column_stack([np.sin(angles), -np.cos(angles)])
        points.append(direction * radius)
        normals.append(direction)
        kinds.append(np.zeros(len(angles), int))
        indices.append(np.full(len(angles), ring))
    radii = np.arange(SPOKE_RADII[0], SPOKE_RADII[1] + 1e-9, SPOKE_STEP_MM)
    radii = radii[np.abs(radii[:, None] - np.asarray(RING_EDGES)[None, :]).min(axis=1) >= JUNCTION_CLEARANCE_MM]
    for spoke, angle in enumerate(spokes):
        direction = np.array([math.sin(angle), -math.cos(angle)])
        normal = np.array([math.cos(angle), math.sin(angle)])
        points.append(radii[:, None] * direction)
        normals.append(np.tile(normal, (len(radii), 1)))
        kinds.append(np.ones(len(radii), int))
        indices.append(np.full(len(radii), spoke))
    return (np.vstack(points), np.vstack(normals), np.concatenate(kinds), np.concatenate(indices))


def side_points(points, kinds, indices):
    """Board points well inside the regions on either side of each edge sample: (inside, outside)."""
    radius = np.linalg.norm(points, axis=1)
    angle = np.arctan2(points[:, 0], -points[:, 1])
    inner_r = radius.copy()
    outer_r = radius.copy()
    inner_a = angle.copy()
    outer_a = angle.copy()
    rings = kinds == 0
    for ring, edge in enumerate(RING_EDGES):
        selected = rings & (indices == ring)
        inner_r[selected], outer_r[selected] = RING_SIDES[edge]
    spokes = ~rings
    inner_a[spokes] = angle[spokes] - math.radians(SECTOR_HALF_ANGLE)
    outer_a[spokes] = angle[spokes] + math.radians(SECTOR_HALF_ANGLE)

    def polar(r, a):
        return np.column_stack([r * np.sin(a), -r * np.cos(a)])

    return polar(inner_r, inner_a), polar(outer_r, outer_a)


def sample(image, pixels):
    """Bilinear colour samples of a float32 image at (..., 2) pixel positions -> (..., channels)."""
    shape = pixels.shape[:-1]
    # remap maps must stay below 32767 per side: keep (points, offsets) as a 2-D map.
    grid = pixels.reshape(-1, pixels.shape[-2], 2) if pixels.ndim == 3 else pixels.reshape(1, -1, 2)
    grid = np.ascontiguousarray(grid, np.float32)
    values = cv2.remap(image, grid[..., 0], grid[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(-1.0, -1.0, -1.0))
    return values.reshape(*shape, image.shape[2])


def find_edges(image, board_to_image, points, normals, inside, outside, window):
    """Locate each model edge across its normal. Returns (offsets mm, valid, wire), each (N,).

    offset is the signed distance (mm, along the normal, under the current homography)
    from the model point to the found edge: the centre of the wire when the wire is
    visible (wire True), otherwise the steepest point of the colour step.
    """
    height, width = image.shape[:2]
    offsets_mm = np.arange(-window, window + PROFILE_STEP_MM / 2, PROFILE_STEP_MM)
    line = points[:, None, :] + offsets_mm[None, :, None] * normals[:, None, :]
    pixels = apply(board_to_image, line.reshape(-1, 2)).reshape(len(points), len(offsets_mm), 2)
    inside_colour = sample(image, apply(board_to_image, inside))
    outside_colour = sample(image, apply(board_to_image, outside))
    profile = sample(image, pixels)

    in_frame = ((pixels[..., 0] >= 0) & (pixels[..., 0] <= width - 1)
                & (pixels[..., 1] >= 0) & (pixels[..., 1] <= height - 1)).all(axis=1)
    in_frame &= (inside_colour >= 0).all(axis=1) & (outside_colour >= 0).all(axis=1)
    contrast = outside_colour - inside_colour
    strength = np.linalg.norm(contrast, axis=1)
    # Project the colour profile onto the side-to-side colour difference: 0 inside, 1 outside.
    level = ((profile - inside_colour[:, None, :]) * contrast[:, None, :]).sum(axis=2)
    level /= np.maximum(strength ** 2, 1e-6)[:, None]
    slope = np.gradient(level, PROFILE_STEP_MM, axis=1)

    ends = 3
    start = np.median(level[:, :ends], axis=1)
    end = np.median(level[:, -ends:], axis=1)
    peak = np.argmax(slope, axis=1)
    rows = np.arange(len(points))
    peak_slope = slope[rows, peak]
    interior = (peak > 0) & (peak < len(offsets_mm) - 1)
    valid = (in_frame & (strength >= MIN_CONTRAST) & (start <= END_LEVELS[0]) & (end >= END_LEVELS[1])
             & interior & (peak_slope >= MIN_PEAK_SLOPE))
    offsets = offsets_mm[np.clip(peak, 1, len(offsets_mm) - 2)] + subsample_peak(slope, peak) * PROFILE_STEP_MM

    # The wire on the edge: colour off the line between the two sides' colours.
    across = np.linalg.norm((profile - inside_colour[:, None, :]) - level[:, :, None] * contrast[:, None, :], axis=2)
    near = np.abs(offsets_mm[None, :] - offsets[:, None]) <= WIRE_SEARCH_MM
    masked = np.where(near, across, -np.inf)
    wire_peak = np.argmax(masked, axis=1)
    wire_height = masked[rows, wire_peak]
    floor = np.where(near, across, np.inf).min(axis=1)
    has_wire = (interior & (wire_height - floor >= WIRE_MIN_CONTRAST) & (wire_peak > 0)
                & (wire_peak < len(offsets_mm) - 1) & near[rows, np.clip(wire_peak - 1, 0, None)]
                & near[rows, np.clip(wire_peak + 1, None, len(offsets_mm) - 1)])
    wire_offsets = (offsets_mm[np.clip(wire_peak, 1, len(offsets_mm) - 2)]
                    + subsample_peak(across, wire_peak) * PROFILE_STEP_MM)
    offsets = np.where(has_wire, wire_offsets, offsets)
    return offsets, valid, has_wire & valid


def subsample_peak(values, peak):
    """Sub-sample offset (-0.5..0.5 samples) of a row-wise peak from a parabola through it and its neighbours."""
    rows = np.arange(len(values))
    clipped = np.clip(peak, 1, values.shape[1] - 2)
    before, centre, after = values[rows, clipped - 1], values[rows, clipped], values[rows, clipped + 1]
    curvature = before - 2 * centre + after
    shift = np.where(curvature < 0, 0.5 * (before - after) / np.where(curvature < 0, curvature, -1.0), 0.0)
    return np.clip(shift, -0.5, 0.5)


class EdgeFit:
    """Gauss-Newton fit of an image -> board homography to measured edge points.

    Image points are normalised (centred, scaled) for conditioning. The 8 parameters are
    the entries of the normalised homography with its last entry fixed at 1.
    """

    def __init__(self, image_points, kinds, indices, pixels_per_mm):
        self.centre = image_points.mean(axis=0)
        self.spread = float(np.sqrt(((image_points - self.centre) ** 2).sum(axis=1).mean())) or 1.0
        self.points = (image_points - self.centre) / self.spread
        self.kinds = kinds
        self.radii = np.asarray(RING_EDGES)[np.where(kinds == 0, indices, 0)]
        angles = np.radians(np.asarray(SPOKE_ANGLES))[np.where(kinds == 1, indices, 0)]
        self.spoke_normals = np.column_stack([np.cos(angles), np.sin(angles)])
        self.pixels_per_mm = pixels_per_mm
        self.normaliser = np.array([[1 / self.spread, 0, -self.centre[0] / self.spread],
                                    [0, 1 / self.spread, -self.centre[1] / self.spread], [0, 0, 1.0]])

    def to_parameters(self, image_to_board):
        matrix = image_to_board @ np.linalg.inv(self.normaliser)
        return (matrix / matrix[2, 2]).ravel()[:8]

    def to_matrix(self, parameters):
        return np.append(parameters, 1.0).reshape(3, 3) @ self.normaliser

    def residuals(self, parameters, jacobian=False):
        """Point-to-curve distances in mm (and their Jacobian w.r.t. the parameters)."""
        a = parameters
        x, y = self.points[:, 0], self.points[:, 1]
        w = a[6] * x + a[7] * y + 1.0
        qx = (a[0] * x + a[1] * y + a[2]) / w
        qy = (a[3] * x + a[4] * y + a[5]) / w
        rings = self.kinds == 0
        radius = np.hypot(qx, qy)
        gradient = np.where(rings[:, None], np.column_stack([qx, qy]) / np.maximum(radius, 1e-9)[:, None],
                            self.spoke_normals)
        residual = np.where(rings, radius - self.radii, qx * self.spoke_normals[:, 0] + qy * self.spoke_normals[:, 1])
        if not jacobian:
            return residual
        zero = np.zeros_like(x)
        dqx = np.column_stack([x / w, y / w, 1 / w, zero, zero, zero, -qx * x / w, -qx * y / w])
        dqy = np.column_stack([zero, zero, zero, x / w, y / w, 1 / w, -qy * x / w, -qy * y / w])
        return residual, gradient[:, :1] * dqx + gradient[:, 1:] * dqy

    def solve(self, image_to_board):
        """Robust fit. Returns (image_to_board, residual mm, Tukey weights)."""
        parameters = self.to_parameters(image_to_board)
        for _ in range(GAUSS_NEWTON_ITERATIONS):
            residual, jacobian = self.residuals(parameters, jacobian=True)
            weights = self.robust_weights(residual)
            if np.count_nonzero(weights) < 8:
                break
            # Residuals are weighed in image pixels: px per mm across the edge, squared.
            weights = weights * self.pixels_per_mm ** 2
            normal = jacobian.T @ (weights[:, None] * jacobian)
            normal += 1e-9 * np.trace(normal) * np.eye(8)
            step = np.linalg.solve(normal, -jacobian.T @ (weights * residual))
            parameters = parameters + step
            if np.abs(step).max() < 1e-10:
                break
        residual = self.residuals(parameters)
        return self.to_matrix(parameters), residual, self.robust_weights(residual)

    def robust_weights(self, residual_mm):
        scaled = residual_mm * self.pixels_per_mm
        sigma = max(1.4826 * float(np.median(np.abs(scaled - np.median(scaled)))), MIN_SIGMA_PX)
        u = scaled / (TUKEY_C * sigma)
        return np.where(np.abs(u) < 1, (1 - u ** 2) ** 2, 0.0)


def pixels_per_mm(board_to_image, points, normals):
    """Image pixels per board mm across each edge (local scale of the homography)."""
    ahead = apply(board_to_image, points + 0.5 * normals)
    behind = apply(board_to_image, points - 0.5 * normals)
    return np.linalg.norm(ahead - behind, axis=1)


def board_shift_mm(first, second):
    """Largest distance (mm) between two image -> board maps over the scoring area (r <= 170 mm).

    first/second: image -> board homographies. Compared at the board points the first
    one maps from (probe points on a grid of rings).
    """
    angles = np.radians(np.arange(0, 360, 15))
    probes = np.vstack([np.column_stack([r * np.sin(angles), -r * np.cos(angles)]) for r in (0.1, 60, 120, 170)])
    image_points = apply(np.linalg.inv(first), probes)
    return float(np.linalg.norm(apply(second, image_points) - probes, axis=1).max())


def coverage(points, kinds, indices, inliers):
    """(ring sectors with inliers out of 12, spokes with inliers out of 20)."""
    rings = inliers & (kinds == 0)
    angles = np.degrees(np.arctan2(points[rings, 0], -points[rings, 1])) % 360
    sectors = np.bincount((angles // 30).astype(int), minlength=12)
    spokes = np.bincount(indices[inliers & (kinds == 1)], minlength=20)
    return int((sectors >= MIN_POINTS_PER_BIN).sum()), int((spokes >= MIN_POINTS_PER_BIN).sum())


def refine(image, H, scale, center):
    """Refine vision's click homography H (image px -> warp px) from the board's own edges.

    Returns (H, report). H is the refined homography when the refinement is confident,
    otherwise the input H unchanged. report (JSON-serialisable) has:
      method        'refined' or 'clicks' (the click homography was kept)
      confidence    'high' (refined), or 'low' (kept the clicks, or refined but the orientation
                    looks wrong: see warning)
      reason        why the clicks were kept (None when refined)
      warning       orientation warning (orientation_warning), or None
      residual_mm   RMS distance of the found edges from the fitted board model (inliers)
      edge_points   inlier edge points used / sampled
      ring_sectors, spokes  coverage of the inliers (of 12 and 20)
      click_offset_mm  largest change of the board map within the double ring versus the clicks
      click_error_px   largest distance between a click and where the refined fit puts its target
      click_error_limit_px  the acceptance limit for click_error_px (click_error_limit)
      seconds       time taken
    Never raises on a bad image (including a grayscale one); a failure keeps the clicks.
    """
    started = time.perf_counter()
    S = scaling(scale, center)
    click_map = np.linalg.inv(S) @ np.asarray(H, np.float64)  # image px -> board mm
    report = clicks_report(None)
    try:
        image = np.asarray(image)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('calibration image must be a colour or grayscale image')
        blurred = cv2.GaussianBlur(image, (0, 0), PRE_BLUR_SIGMA).astype(np.float32)
        points, normals, kinds, indices = model_points()
        inside, outside = side_points(points, kinds, indices)
        report['sampled_points'] = int(len(points))
        current = click_map / click_map[2, 2]
        inliers = np.zeros(len(points), bool)
        residual = None
        for window in WINDOWS_MM:
            board_to_image = np.linalg.inv(current)
            offsets, valid, _ = find_edges(blurred, board_to_image, points, normals, inside, outside, window)
            if valid.sum() < MIN_INLIERS:
                raise ValueError('found %d board edges (need %d)' % (valid.sum(), MIN_INLIERS))
            found = points[valid] + offsets[valid, None] * normals[valid]
            image_points = apply(board_to_image, found)
            scale_px = pixels_per_mm(board_to_image, points[valid], normals[valid])
            fit = EdgeFit(image_points, kinds[valid], indices[valid], scale_px)
            current, residual_valid, weights = fit.solve(current)
            current = current / current[2, 2]
            inliers = np.zeros(len(points), bool)
            inliers[np.flatnonzero(valid)[weights > 0]] = True
            residual = residual_valid[weights > 0]
        rms = float(np.sqrt(np.mean(residual ** 2))) if residual is not None and len(residual) else None
        ring_sectors, spokes = coverage(points, kinds, indices, inliers)
        shift = board_shift_mm(click_map, current)
        clicked = apply(np.linalg.inv(click_map), CLICK_TARGETS_MM)
        click_error = float(np.linalg.norm(apply(np.linalg.inv(current), CLICK_TARGETS_MM) - clicked, axis=1).max())
        limit = click_error_limit(clicked)
        report.update({'residual_mm': round(rms, 3) if rms is not None else None,
                       'edge_points': int(inliers.sum()), 'ring_sectors': ring_sectors, 'spokes': spokes,
                       'click_offset_mm': round(shift, 2), 'click_error_px': round(click_error, 2),
                       'click_error_limit_px': round(limit, 1)})
        reason = rejection_reason(inliers, rms, ring_sectors, spokes, click_error, limit)
        if reason is None:
            H = S @ current
            H = H / H[2, 2]
            warning = orientation_warning(clicked)
            report.update({'method': 'refined', 'confidence': 'high' if warning is None else 'low',
                           'warning': warning})
        else:
            report['reason'] = reason
    except ValueError as error:
        report['reason'] = str(error)
    except Exception as error:  # noqa: BLE001 - a calibration helper must never break calibrate()
        report['reason'] = 'refinement failed: %s: %s' % (type(error).__name__, error)
    report['seconds'] = round(time.perf_counter() - started, 3)
    return np.asarray(H, np.float64), report


def rejection_reason(inliers, rms, ring_sectors, spokes, click_error, limit=MIN_CLICK_ERROR_LIMIT_PX):
    """Why the refined fit is not trusted, or None when it is."""
    if inliers.sum() < MIN_INLIERS or inliers.mean() < MIN_INLIER_FRACTION:
        return 'only %d of %d board edges fit' % (inliers.sum(), len(inliers))
    if ring_sectors < MIN_RING_SECTORS or spokes < MIN_SPOKES:
        return 'edges found on only part of the board (%d/12 ring sectors, %d/20 wires)' % (ring_sectors, spokes)
    if rms is None or rms > MAX_RESIDUAL_MM:
        return 'edge residual %.2f mm is too large' % (rms if rms is not None else float('nan'))
    if not math.isfinite(click_error) or click_error > limit:
        return 'the fit moves a clicked point by %.0f px, implausibly far; check the four points' % click_error
    return None
