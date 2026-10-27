"""Dart segmentation on warped (top-down) board images (M1-05b). Pure functions.

Input: the current stable warped frame, the empty-board base, and the camera
foot point in warp pixels (or None). Output: a Segmentation saying whether the
change is no dart, one dart (with its pixels), several darts, or too large to
be a dart.

Pipeline:
  1. Illumination normalisation: per-channel gain between frame and base,
     estimated robustly over the whole board (a dart covers a few percent of
     it), so an exposure or white-balance drift is not a change.
  2. Colour-aware change: the largest per-channel difference after
     normalisation, thresholded at max(CHANGE_THRESHOLD, NOISE_FACTOR x the
     robust noise level). A dart part with the same gray level as the board
     behind it still differs in colour.
     Hysteresis then adds weaker change (> WEAK_FACTOR x threshold) connected to it,
     so a thin, blurred dart point is kept while isolated noise is not.
  3. Shadow removal: a cast shadow darkens the board by about the same factor
     in every channel (chromaticity is kept). A changed pixel that is darker
     than the base by a channel-consistent factor is shadow, not dart. Small
     fragments surrounded by darkened board (noise speckles inside a shadow) go too.
  4. Fragment grouping: one dart often breaks into fragments (a black shaft
     over a black segment, a red flight over a red ring). A fragment joins a
     group when it touches it (NEAR_GAP_MM) or lies along the group's axis
     within AXIS_GAP_MM. The axis is the group's principal axis, or the
     direction away from the foot point: off-plane dart parts project away from
     the foot point, so one dart's fragments are collinear with that direction.
     Past the dart's end nearest the foot point only the tip can lie, so a
     fragment joined there across a gap must be point-shaped (elongated and
     parallel); shadow edges and speckles there are not.
     Only a group holding a core fragment (CORE_MIN_MM2, a barrel or flight
     sized piece) joins across a gap; small pieces without a core join only
     what they touch, so scattered specks are not chained into a 'dart'.
  5. Decision: groups of at least MIN_DART_MM2 that are plausibly a dart (a
     core fragment, mean width MIN_MEAN_WIDTH_MM) are candidates. Exactly one
     candidate is a dart; two or more are reported as 'multiple'. More than
     MAX_FRAGMENTS fragments (or MAX_CORE_FRAGMENTS core-sized ones), only
     implausible dart-sized groups, or one candidate beside MAX_IMPLAUSIBLE_BESIDE_DART
     dart-sized implausible groups, is 'noisy' (no proposal); the fragment caps
     also bounds the grouping time.

No ground truth is used: the same code runs on real frames. Every threshold
here was tuned on synthetic scenes (seed 1) and must be refit on real footage.
"""
import functools
import itertools
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

# Change detection.
CHANGE_THRESHOLD = 30  # minimum per-channel difference (0-255) after normalisation
NOISE_FACTOR = 5.0  # threshold >= NOISE_FACTOR x robust noise sigma of the difference
GAIN_MIN_BASE = 40  # base pixels darker than this do not vote for the gain
GAIN_SAMPLE_STEP = 5
GAIN_RANGE = (0.5, 2.0)  # a gain outside this is a large scene change, not an exposure drift
WEAK_FACTOR = 0.5  # hysteresis: weak pixels connected to a strong change also count
MAX_CHANGE_THRESHOLD = 60  # cap for the noise-adaptive threshold (a gross change also inflates the noise estimate)
LARGE_CHANGE_FRACTION = 0.12  # changed fraction of the board that means "camera or board moved"

# Shadow test (per pixel, on lightly smoothed images).
SHADOW_RATIO = (0.25, 0.8)  # mean frame/base ratio of a shadowed pixel
SHADOW_CHROMA_SPREAD = 0.10  # (max - min) / mean of the per-channel ratios
SHADOW_MIN_CHANNEL = 60  # base channels at least this bright measure the darkening ratio
SHADOW_DIM_MARGIN = 0.4  # dimmer channels may rise by at most this x threshold (noise)

# Fragments and grouping, in board millimetres.
MIN_FRAGMENT_MM2 = 4.0
NEAR_GAP_MM = 5.0
AXIS_GAP_MM = 70.0
AXIS_WIDTH_MM = 5.0
AXIS_ANGLE_DEG = 10.0
ELONGATED_RATIO = 3.0  # PCA eigenvalue ratio for a usable principal axis
POINT_MIN_LENGTH_MM = 4.0  # a cut-off point fragment is at least this long
POINT_SOLIDITY = 0.6  # pixels / convex hull area of a cut-off point fragment (speckle clouds are sparse)
POINT_ALIGNMENT = float(np.cos(np.radians(25.0)))  # a cut-off point fragment is roughly parallel to the dart
MIN_DART_MM2 = 40.0
MAX_DART_MM2 = 8000.0
# Dart plausibility (M1-05e). On synthetic seed 1 (all ten mounts, ideal, realistic and realistic +
# shadow) every accepted dart had a largest fragment of at least 62 mm2 holding at least 26% of the
# dart's pixels, a mean width (area / length) of at least 3.3 mm and a length of at least 17 mm.
# On near-frontal (ungated), where a dart can point at the lens, darts were as short as 12 mm; the
# 15 mm minimum rejects those few (near-frontal 49.8 -> 49.3%). Chained specks are thin; a single
# fleck is short.
CORE_MIN_MM2 = 50.0  # a group needs a fragment this large to join pieces across a gap or to be a dart
MIN_CORE_FRACTION = 0.15  # the core fragment's share of the group's pixels
MIN_MEAN_WIDTH_MM = 2.0
MIN_DART_LENGTH_MM = 15.0
# More fragments than this is a noisy scene (sensor noise, debris, a moving shadow), not one new dart.
# Synthetic dart frames have at most 8. The cap also bounds the grouping time (pairwise checks).
MAX_FRAGMENTS = 40
# Core-sized fragments (>= CORE_MIN_MM2) are the expensive ones to group (each may join across a
# gap). More than this many is also a noisy scene, such as an arm or hand shadow broken into
# pieces (QA D4: 30-40 large strokes took 0.16-0.38 s and occasionally gave a false dart).
MAX_CORE_FRAGMENTS = 12
# A plausible dart next to this many dart-sized implausible groups is a noisy scene too. On grazing
# views the warp stretches a 3-4 mm fleck to 15-18 mm, as long as the shortest darts; a lone such
# fleck still passes, but flecks rarely come alone. Chosen on seed 1: speckle false proposals on
# ceiling-0.5ft / near-frontal / ceiling-3ft 22 / 17 / 11 of 60 -> 2 / 0 / 0, no dart result changed.
MAX_IMPLAUSIBLE_BESIDE_DART = 2


@dataclass
class Segmentation:
    """Result of segment().

    kind: 'none', 'dart', 'multiple', 'too_large', 'noisy' or 'large_change'.
    points: (N, 2) float32 warp pixels (x, y) of the dart when kind == 'dart'.
    outline: (M, 2) float32 outline pixels of the dart's fragments when kind == 'dart'.
    groups: the grouped Blobs, largest first (for diagnostics).
    implausible: candidate-sized groups rejected as not dart-shaped (diagnostics).
    """

    kind: str
    points: Optional[np.ndarray] = None
    outline: Optional[np.ndarray] = None
    groups: list = field(default_factory=list)
    changed_fraction: float = 0.0
    shadow_pixels: int = 0
    gains: tuple = (1.0, 1.0, 1.0)
    threshold: float = CHANGE_THRESHOLD
    difference: Optional[np.ndarray] = None  # normalised max-channel change image (float32)
    fragment_count: int = 0
    implausible: int = 0


@functools.lru_cache(maxsize=4)
def board_disc(size, center, radius_px):
    """uint8 mask (255 inside) of the board disc in warp pixels (cached, read-only)."""
    yy, xx = np.ogrid[:size, :size]
    mask = (((xx - center) ** 2 + (yy - center) ** 2) <= radius_px ** 2).astype(np.uint8) * 255
    mask.setflags(write=False)
    return mask


@functools.lru_cache(maxsize=4)
def gain_samples(size, center, radius_px):
    """(rows, cols) of every GAIN_SAMPLE_STEP-th board pixel (cached)."""
    rows, cols = np.nonzero(board_disc(size, center, radius_px))
    return rows[::GAIN_SAMPLE_STEP], cols[::GAIN_SAMPLE_STEP]


def illumination_gains(frame, base, samples):
    """Per-channel gain g with frame ~= g * base on the board (median ratio over usable pixels).

    samples: (rows, cols) of board pixels (gain_samples); a subsample is plenty for a median.
    """
    rows, cols = samples
    gains = []
    for channel in range(3):
        b = base[rows, cols, channel].astype(np.float32)
        f = frame[rows, cols, channel].astype(np.float32)
        usable = b >= GAIN_MIN_BASE
        gain = float(np.median(f[usable] / b[usable])) if usable.sum() > 100 else 1.0
        gains.append(gain)
    return tuple(gains)


def normalised_difference(frame, base, gains):
    """Frame divided by the gains (float32), and the per-channel max absolute difference to base."""
    corrected = frame.astype(np.float32) * (1.0 / np.asarray(gains, np.float32))
    channels = cv2.split(cv2.absdiff(corrected, base.astype(np.float32)))
    difference = cv2.max(cv2.max(channels[0], channels[1]), channels[2])
    return corrected, difference


def change_threshold(difference, board_mask):
    """NOISE_FACTOR x noise, kept within [CHANGE_THRESHOLD, MAX_CHANGE_THRESHOLD].

    noise is the median of the max-channel absolute difference; for Gaussian noise of
    sigma s per channel that median is about 1.26 s, so the threshold is about 6 s.
    """
    values = difference[board_mask > 0]
    noise = float(np.median(values)) if values.size else 0.0
    return min(max(float(CHANGE_THRESHOLD), NOISE_FACTOR * noise), float(MAX_CHANGE_THRESHOLD))


def grow_into_weak_change(difference, threshold, strong, board_mask):
    """Hysteresis: add weakly changed pixels connected to strongly changed ones.

    A thin dart point is only a few pixels wide; anti-aliasing and blur blend it with
    the board, so its pixels often change by less than the threshold. Weak pixels
    (> WEAK_FACTOR x threshold) are kept only when connected to a strong change, so
    isolated noise stays out.
    """
    weak = ((difference > threshold * WEAK_FACTOR) & (board_mask > 0)).astype(np.uint8)
    count, labels = cv2.connectedComponents(weak, connectivity=8)
    keep = np.zeros(count, bool)
    keep[np.unique(labels[strong])] = True
    keep[0] = False
    return keep[labels]


def shadow_pixels(corrected, base, changed, threshold):
    """bool mask, within changed: a cast shadow rather than an object.

    A shadow darkens every channel by about the same factor. The factor is only
    measurable on channels the base shows well (>= SHADOW_MIN_CHANNEL); on a red or
    green ring the dim channels are mostly noise, so for them the test is only that
    they did not get brighter (beyond SHADOW_DIM_MARGIN x threshold). A black or grey
    dart part over a coloured ring brightens the dim channels, so it is not shadow.
    """
    rows, cols = np.nonzero(changed)
    shadow = np.zeros(changed.shape, bool)
    if rows.size == 0:
        return shadow
    smooth_frame = cv2.blur(corrected, (3, 3))[rows, cols]
    smooth_base = cv2.blur(base.astype(np.float32), (3, 3))[rows, cols]
    ratios = (smooth_frame + 1.0) / (smooth_base + 1.0)
    reliable = smooth_base >= SHADOW_MIN_CHANNEL
    count = reliable.sum(axis=1)
    mean = (ratios * reliable).sum(axis=1) / np.maximum(count, 1)
    spread = (np.where(reliable, ratios, -np.inf).max(axis=1)
              - np.where(reliable, ratios, np.inf).min(axis=1)) / np.maximum(mean, 1e-3)
    dim_not_brighter = np.all(reliable | (smooth_frame <= smooth_base + SHADOW_DIM_MARGIN * threshold), axis=1)
    shadow[rows, cols] = ((count > 0) & dim_not_brighter
                          & (mean >= SHADOW_RATIO[0]) & (mean <= SHADOW_RATIO[1])
                          & (spread <= SHADOW_CHROMA_SPREAD))
    return shadow


def inside_shadow(blob, corrected, base):
    """True when the board in a 2-pixel ring around the blob is darker than the base by a shadow's ratio.

    Only the brightness ratio (all channels summed) is tested here, not chromaticity.

    Noise leaves speckles of "change" inside a cast shadow (most of all on the dark
    segments and coloured rings, where the shadow test is weakest). Such a speckle is
    surrounded by darkened board; a dart fragment is surrounded by normally lit board.
    """
    x0, y0 = np.maximum(blob.points.min(axis=0).astype(int) - 3, 0)
    x1, y1 = blob.points.max(axis=0).astype(int) + 4
    own = np.zeros((y1 - y0, x1 - x0), np.uint8)
    own[blob.points[:, 1].astype(int) - y0, blob.points[:, 0].astype(int) - x0] = 1
    ring = (cv2.dilate(own, np.ones((5, 5), np.uint8)) > 0) & (own == 0)
    ring = ring[:corrected.shape[0] - y0, :corrected.shape[1] - x0]
    lit = float(base[y0:y1, x0:x1][ring].sum())
    if lit <= 0:
        return False
    return float(corrected[y0:y1, x0:x1][ring].sum()) / lit <= SHADOW_RATIO[1]


_serials = itertools.count()


@dataclass(eq=False)
class Blob:
    """A fragment or a group of fragments: all its pixels, and its outline pixels for fast distances.

    largest: pixels in its largest original fragment. serial: a unique, never reused key
    (id() is reused once a merged-away Blob is freed, so it cannot key a cache).
    """

    points: np.ndarray  # (N, 2) float32 (x, y)
    outline: np.ndarray  # (M, 2) float32 (x, y), M << N
    largest: int = 0
    serial: int = field(default_factory=lambda: next(_serials))
    _axis: Optional[tuple] = field(default=None, init=False, repr=False)
    _box: Optional[tuple] = field(default=None, init=False, repr=False)
    _extents: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        if not self.largest:
            self.largest = len(self.points)

    def merged(self, other):
        return Blob(np.vstack([self.points, other.points]), np.vstack([self.outline, other.outline]),
                    max(self.largest, other.largest))

    def solidity(self):
        """Pixel count over convex hull area: about 1 for a solid shape, low for a sparse cloud.

        Half the hull perimeter is added to its area because the hull runs through pixel centres.
        """
        hull = cv2.convexHull(self.points.reshape(-1, 1, 2))
        return len(self.points) / max(cv2.contourArea(hull) + 0.5 * cv2.arcLength(hull, True) + 1.0, 1.0)

    def principal_axis(self):
        """(mean, unit direction or None, eigenvalue ratio); computed once per Blob."""
        if self._axis is None:
            mean = self.points.mean(axis=0)
            if len(self.points) < 3:
                self._axis = (mean, None, 0.0)
            else:
                values, vectors = np.linalg.eigh(np.cov((self.points - mean).T))
                self._axis = (mean, vectors[:, 1].astype(np.float32), float(values[1] / max(values[0], 1e-6)))
        return self._axis

    def box(self):
        """((min x, min y), (max x, max y)) of the outline; computed once per Blob."""
        if self._box is None:
            self._box = (tuple(map(float, self.outline.min(axis=0))), tuple(map(float, self.outline.max(axis=0))))
        return self._box

    def extent(self, direction):
        """(min, max) of the pixels along direction and the 95th percentile distance across it,
        measured from the mean; memoised per direction."""
        key = direction.tobytes()
        if key not in self._extents:
            mean = self.principal_axis()[0]
            relative = self.points - mean
            along = relative @ direction
            normal = np.array([-direction[1], direction[0]], np.float32)
            width = float(np.percentile(np.abs(relative @ normal), 95))
            self._extents[key] = (float(along.min()), float(along.max()), width)
        return self._extents[key]

    def length(self):
        """Extent along the principal axis (px)."""
        mean, axis, _ = self.principal_axis()
        if axis is None:
            return 0.0
        return float(np.ptp((self.points - mean) @ axis))


def fragments(mask, min_pixels):
    """Connected components of mask with at least min_pixels, as Blobs, largest first."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        if area < min_pixels:
            continue
        component = (labels[y:y + height, x:x + width] == label).astype(np.uint8)
        ys, xs = np.nonzero(component)
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        outline = np.vstack([c.reshape(-1, 2) for c in contours]).astype(np.float32) + (x, y)
        found.append(Blob(np.column_stack([xs + x, ys + y]).astype(np.float32), outline))
    found.sort(key=lambda blob: len(blob.points), reverse=True)
    return found


def squared_distances(first, second):
    """(len(first), len(second)) matrix of squared distances between two point sets."""
    first = first.astype(np.float32)
    second = second.astype(np.float32)
    squared = ((first * first).sum(axis=1)[:, None] + (second * second).sum(axis=1)[None, :]
               - 2.0 * first @ second.T)
    return np.maximum(squared, 0.0)


def bounding_gap(first, second):
    """Distance between the bounding boxes of two Blobs (0 when they overlap); a lower bound."""
    (x0, y0), (x1, y1) = first.box()
    (u0, v0), (u1, v1) = second.box()
    dx = max(x0 - u1, u0 - x1, 0.0)
    dy = max(y0 - v1, v0 - y1, 0.0)
    return float(np.hypot(dx, dy))


class FragmentGrouper:
    """Groups fragments of one dart. Distances are given in warp pixels."""

    def __init__(self, scale, foot=None):
        self.near_gap = NEAR_GAP_MM * scale
        self.axis_gap = AXIS_GAP_MM * scale
        self.axis_width = AXIS_WIDTH_MM * scale
        self.axis_slope = float(np.tan(np.radians(AXIS_ANGLE_DEG)))
        self.point_min_length = POINT_MIN_LENGTH_MM * scale
        self.core_pixels = CORE_MIN_MM2 * scale * scale
        self.foot = None if foot is None else np.asarray(foot, np.float32)

    def has_core(self, blob):
        return blob.largest >= self.core_pixels

    def axes(self, group):
        """Candidate axis directions for a group: principal axis and/or away-from-foot direction."""
        mean, direction, ratio = group.principal_axis()
        found = []
        if direction is not None and ratio >= ELONGATED_RATIO:
            found.append(direction)
        if self.foot is not None:
            away = mean - self.foot
            norm = float(np.linalg.norm(away))
            if norm > 1e-6:
                found.append((away / norm).astype(np.float32))
        return mean, found

    def along_axis(self, group, fragment, outline_distances, gap):
        """True when the fragment's end nearest the group lies in a narrow wedge along a group axis.

        Only the near end is tested: a flight is broad, but the part of it facing the
        shaft is on the dart's axis. outline_distances: fragment outline -> group outline.
        """
        if gap > self.axis_gap:
            return False
        point = fragment.outline[outline_distances <= gap + self.near_gap].mean(axis=0)
        mean, axes = self.axes(group)
        for direction in axes:
            normal = np.array([-direction[1], direction[0]], np.float32)
            along_min, along_max, group_width = group.extent(direction)
            along = float((point - mean) @ direction)
            # Distance past the group's end along the axis (0 when overlapping).
            beyond = max(along - along_max, along_min - along, 0.0)
            offset = abs(float((point - mean) @ normal))
            allowed = max(group_width, self.axis_width) + self.axis_slope * beyond
            if offset <= allowed:
                return True
        return False

    def belongs(self, first, second):
        box_gap = bounding_gap(first, second)
        if box_gap > self.axis_gap:
            return False
        # Without a core fragment on either side, only touching pieces join (no chaining of specks).
        cored = self.has_core(first) or self.has_core(second)
        if not cored and box_gap > self.near_gap:
            return False
        pairwise = np.sqrt(squared_distances(first.outline, second.outline))
        gap = float(pairwise.min())
        if gap <= self.near_gap:
            return True
        if not cored:
            return False
        if not (self.along_axis(first, second, pairwise.min(axis=0), gap)
                or self.along_axis(second, first, pairwise.min(axis=1), gap)):
            return False
        large, small = (first, second) if len(first.points) >= len(second.points) else (second, first)
        return not self.beyond_tip(large, small) or self.point_shaped(large, small)

    def beyond_tip(self, large, small):
        """True when small lies past large's end nearest the foot point (where only the tip can be)."""
        if self.foot is None:
            return False
        nearest_large = float(np.linalg.norm(large.points - self.foot, axis=1).min())
        return float(np.linalg.norm(small.points.mean(axis=0) - self.foot)) < nearest_large

    def point_shaped(self, large, small):
        """True when small is solid, elongated and parallel to large, like a dart point cut off by a gap.

        Cast-shadow edges and noise speckles past the tip are sparse, blob-like or skewed.
        """
        _, small_axis, small_ratio = small.principal_axis()
        _, large_axes = self.axes(large)
        if small_axis is None or small_ratio < ELONGATED_RATIO or small.solidity() < POINT_SOLIDITY:
            return False
        length = np.ptp((small.points - small.points.mean(axis=0)) @ small_axis)
        if length < self.point_min_length:
            return False
        return any(abs(float(small_axis @ axis)) >= POINT_ALIGNMENT for axis in large_axes)

    def group(self, pieces):
        """Merge Blobs (largest first) until nothing more merges. Returns Blobs, largest first."""
        groups = list(pieces)
        apart = set()  # serials of (unchanged) blob pairs already found not to belong together
        merged = True
        while merged and len(groups) > 1:
            merged = False
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    pair = (groups[i].serial, groups[j].serial)
                    if pair in apart:
                        continue
                    if self.belongs(groups[i], groups[j]):
                        groups[i] = groups[i].merged(groups[j])
                        del groups[j]
                        merged = True
                        break
                    apart.add(pair)
                if merged:
                    break
        groups.sort(key=lambda blob: len(blob.points), reverse=True)
        return groups


def plausible_dart(group, scale):
    """A dart candidate has a core fragment that is a fair share of it, is long enough, and is not
    a thin chain (mean width = area / length along its principal axis)."""
    if group.largest < CORE_MIN_MM2 * scale * scale or group.largest < MIN_CORE_FRACTION * len(group.points):
        return False
    length_mm = group.length() / scale
    area_mm2 = len(group.points) / (scale * scale)
    return length_mm >= MIN_DART_LENGTH_MM and area_mm2 / length_mm >= MIN_MEAN_WIDTH_MM


def segment(frame, base, scale, center, board_radius_mm=172.0, foot=None):
    """Segment the new dart(s) in a warped frame against the warped base. See module docstring."""
    size = frame.shape[0]
    board_mask = board_disc(size, center, board_radius_mm * scale)
    gains = illumination_gains(frame, base, gain_samples(size, center, board_radius_mm * scale))
    if not all(GAIN_RANGE[0] <= gain <= GAIN_RANGE[1] for gain in gains):
        return Segmentation('large_change', gains=gains, changed_fraction=1.0)
    corrected, difference = normalised_difference(frame, base, gains)
    threshold = change_threshold(difference, board_mask)
    changed = (difference > threshold) & (board_mask > 0)
    board_pixels = max(int(np.count_nonzero(board_mask)), 1)
    changed_fraction = float(np.count_nonzero(changed)) / board_pixels
    result = Segmentation('none', gains=gains, threshold=threshold, changed_fraction=changed_fraction,
                          difference=difference)
    if changed_fraction > LARGE_CHANGE_FRACTION:
        result.kind = 'large_change'
        return result
    changed = grow_into_weak_change(difference, threshold, changed, board_mask)

    shadow = shadow_pixels(corrected, base, changed, threshold)
    result.shadow_pixels = int(np.count_nonzero(shadow))
    mask = (changed & ~shadow).astype(np.uint8) * 255
    # A symmetric kernel: an even-sized one would shift the mask by a pixel.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)))

    pixels_per_mm2 = scale * scale
    pieces = fragments(mask, max(3, int(round(MIN_FRAGMENT_MM2 * pixels_per_mm2))))
    pieces = [piece for piece in pieces
              if len(piece.points) >= MIN_DART_MM2 * pixels_per_mm2 or not inside_shadow(piece, corrected, base)]
    result.fragment_count = len(pieces)
    cores = sum(len(piece.points) >= CORE_MIN_MM2 * pixels_per_mm2 for piece in pieces)
    if len(pieces) > MAX_FRAGMENTS or cores > MAX_CORE_FRAGMENTS:
        result.kind = 'noisy'
        return result
    groups = FragmentGrouper(scale, foot).group(pieces)
    result.groups = groups
    sized = [g for g in groups if len(g.points) >= MIN_DART_MM2 * pixels_per_mm2]
    candidates = [g for g in sized if plausible_dart(g, scale)]
    result.implausible = len(sized) - len(candidates)
    if not candidates:
        if result.implausible:
            # Dart-sized change that is not dart-shaped: say so rather than a silent "Ready" (QA D5).
            result.kind = 'noisy'
        return result
    if len(candidates) > 1:
        result.kind = 'multiple'
        return result
    if result.implausible >= MAX_IMPLAUSIBLE_BESIDE_DART:
        # One dart-like group among several dart-sized non-darts: likely debris or noise, not a dart.
        result.kind = 'noisy'
        return result
    if len(candidates[0].points) > MAX_DART_MM2 * pixels_per_mm2:
        result.kind = 'too_large'
        return result
    result.kind = 'dart'
    result.points = candidates[0].points
    result.outline = candidates[0].outline
    return result
