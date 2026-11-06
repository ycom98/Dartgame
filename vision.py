"""Camera prototype. Every proposed dart requires confirmation by the player.

Turns (M4-01). The reference image (base) holds the board as it was after the latest dart the camera saw, so
each new dart is detected as the new change even while earlier darts are still waiting for the host:
  * turn_base is the board at the start of the turn; base is turn_base plus every dart seen since.
  * A stable new dart becomes a pending dart (self.pending, oldest first, at most MAX_PENDING_DARTS) and the
    base rolls forward to the current frame. Two new darts in one stable frame are separated when they are
    two clear blobs. self.proposal is the oldest pending dart (the one a commit applies to).
  * commit_dart(id) marks a pending dart committed (it stays in the reference); end_turn() drops what is still
    pending at Next player; absorb() makes the current frame the reference after a manual score.
  * A tracked dart whose pixels go back to the board behind it was removed: a pending one is retracted
    (bounce-out); a committed one was pulled. When the board matches turn_base again, every dart was pulled:
    the turn reference restarts (board cleared).
  * A large stable change (a person in front, lights) is not an invalidation: the board is checked against
    the calibration reference once, and only a moved board needs alignment.
Thresholds that need real footage are in vision_tuning.py.
"""
import collections
import functools
import itertools
import secrets
import threading
import time
from dataclasses import dataclass
import cv2
import numpy as np
from core import score_point, near_wire
import vision_calibrate
import vision_pose
import vision_segment
import vision_tuning

SIZE = 700
SCALE = 1.7
CENTER = SIZE / 2
TARGETS = np.float32([[0, -170], [170, 0], [0, 170], [-170, 0]]) * SCALE + CENTER
CALIBRATION_SECONDS = 300

# Tip rules (M1-05). 'foot': the tip is the blob end nearer the camera's foot point
# (off-plane dart parts project away from it). 'centre': legacy "end nearer the bull" rule,
# kept selectable for the evaluation harness.
TIP_RULES = ('foot', 'centre')
DEFAULT_RULE = 'foot'
# Extension of the chosen endpoint along the blob axis toward the foot point, in mm.
# 0.0 until it can be fit on held-out synthetic seeds or, preferably, real footage (M2-03).
# History: M1-05 shipped 0.2, the median signed error over all proposals on the same seed-1 darts it was
# then scored on (fragment outliers included); the robust median (tips within 5 mm) was -0.10 mm, and
# QA measured slightly lower tip error with 0.0 and identical exact scores.
TIP_BIAS_MM = 0.0
# Change detection covers the board and most of the number ring (mm): a dart body near the
# double ring often projects outside the scoring area. This disc is also the denominator of
# vision_segment.LARGE_CHANGE_FRACTION: 12% of it (about 15,100 mm2) changed means the camera or
# board moved. (M1-05 used 172 mm, where 12% was about 11,200 mm2.)
BOARD_CHANGE_RADIUS_MM = 200.0
# Pixels within this distance of the chosen blob end refine the tip along the point's own axis (mm).
TIP_REFINE_MM = 12.0
# How far beyond the pixel end the half-contrast edge search looks (mm).
EDGE_SEARCH_MM = 2.0
# Refine the four-click homography from the board's own ring edges and wires (M1-05c).
# The harness turns it off to reproduce M1-05b (click-only calibration).
CALIBRATION_REFINEMENT = True
SEGMENTATION_MESSAGES = {
    'none': 'Ready',
    'multiple': 'More than one new dart; enter scores manually',
    'too_large': 'Change is too large for one dart; enter score manually',
    'noisy': 'Too many small changes (noise, debris or a moving shadow); enter score manually',
}
PENDING_MESSAGE = 'Possible dart found — confirm or correct score'
BOARD_NOT_EMPTY = ('The board does not look empty: pull every dart, then press Board clear · reset image '
                   '(the camera uses this picture as the empty board).')
BOARD_STILL_HAS_DARTS = ('Darts still in the board? The turn was reset, but the empty-board picture was kept. '
                         'Pull them and press Board clear · reset image again.')
# Darts kept for removal checks; older ones simply stay part of the reference image.
MAX_TRACKED_DARTS = 12


@functools.lru_cache(maxsize=1)
def board_cells():
    """(cell index per warp pixel, mask of pixels away from wires and the board edge), for board_marks_mm2."""
    yy, xx = np.mgrid[:SIZE, :SIZE]
    x, y = (xx - CENTER) / SCALE, (yy - CENTER) / SCALE
    radius = np.hypot(x, y)
    angle = (np.degrees(np.arctan2(x, -y)) + 9) % 360
    edges = [0.0, 6.35, 15.9, 99.0, 107.0, 162.0, 170.0]
    ring = np.digitize(radius, edges) - 1
    margin = 2.5  # mm from every wire
    to_ring_wire = np.min([np.abs(radius - edge) for edge in edges[1:]], axis=0)
    to_spoke = np.minimum(angle % 18, 18 - angle % 18) * np.pi / 180 * radius
    usable = (radius < edges[-1] - margin) & (to_ring_wire > margin) & ((ring <= 1) | (to_spoke > margin))
    cell = np.where(ring <= 1, ring, 2 + ring * 20 + (angle // 18).astype(int))
    return cell, usable


def board_marks_mm2(warped):
    """Area (mm2) of marks on the board: pixels far from their cell's own colour (darts, debris)."""
    cell, usable = board_cells()
    pixels = cv2.medianBlur(warped, 5).astype(np.int16)  # camera grain is not a mark; a dart is wider than 5 px
    marks = np.zeros((SIZE, SIZE), np.uint8)
    for index in np.unique(cell[usable]):
        inside = usable & (cell == index)
        colour = np.median(pixels[inside], axis=0)
        marks[inside] = np.abs(pixels[inside] - colour).max(axis=1) > vision_tuning.EMPTY_CELL_DELTA
    marks = cv2.morphologyEx(marks, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return float(marks.sum()) / SCALE ** 2


@dataclass(eq=False)
class TrackedDart:
    """A dart the camera saw this turn. region: its warp pixels (bool mask, grown a little); before: the
    reference image just before it landed (what its pixels go back to if it falls out or is pulled)."""
    id: str
    proposal: dict
    status: str  # 'pending', 'committed' or 'dismissed' (still pending at Next player)
    region: np.ndarray
    before: np.ndarray


def refine_tip(points, tip, direction, difference=None):
    """Re-locate a blob-end tip on the dart point's own axis. Returns (tip, unit direction toward the tip).

    The blob's principal axis is dominated by the flight and can be a few degrees off
    the point, so its extreme pixel is often a corner of the point. Pixels within
    TIP_REFINE_MM of that end give the point's local axis; the tip is the centre of the
    pixels at the far end along it. With the change image (difference), the end is then
    moved to the sub-pixel half-contrast crossing (half_contrast_end).
    """
    near = points[np.linalg.norm(points - tip, axis=1) <= TIP_REFINE_MM * SCALE]
    if len(near) < 6:
        return tip, direction
    mean = near.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((near - mean).T))
    axis = vectors[:, 1].astype(np.float32)
    if float(axis @ direction) < 0:
        axis = -axis
    normal = np.array([-axis[1], axis[0]], np.float32)
    along = (near - mean) @ axis
    across = (near - mean) @ normal
    end = float(along.max())
    centre = float(np.median(across[along >= end - 1.5]))  # last 1.5 warp px (~0.9 mm) of the point
    tip = mean + axis * end + normal * centre
    if difference is not None:
        tip = half_contrast_end(difference, tip, axis)
    return tip, axis


def half_contrast_end(difference, tip, axis):
    """Move tip along axis to where the change falls to half the point's own contrast.

    A fixed threshold puts the end of a blurred point too far out where the point contrasts
    strongly with the board and too far in where it contrasts weakly. The plateau is the
    change along the point's centre line 1-3 mm inside the pixel end; the edge is the
    outermost half-plateau crossing within EDGE_SEARCH_MM, by linear interpolation.
    """
    step = 0.25
    offsets = np.arange(-3.0 * SCALE, EDGE_SEARCH_MM * SCALE + step, step, dtype=np.float32)
    samples = tip[None, :] + offsets[:, None] * axis[None, :]
    profile = cv2.remap(difference.astype(np.float32), samples[:, 0].reshape(1, -1),
                        samples[:, 1].reshape(1, -1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
    inside = (offsets >= -3.0 * SCALE) & (offsets <= -1.0 * SCALE)
    half = 0.5 * float(np.median(profile[inside]))
    above = np.nonzero(profile >= half)[0]
    if half <= 0 or len(above) == 0 or above[-1] + 1 >= len(profile):
        return tip
    last = int(above[-1])
    high, low = float(profile[last]), float(profile[last + 1])
    fraction = (high - half) / max(high - low, 1e-6)
    return tip + axis * float(offsets[last] + fraction * step)


class Vision:
    def __init__(self):
        self.frame = None; self.timestamp = 0; self.reference = None; self.H = None
        self.base = None; self.last_warp = None; self.stable = 0
        # Multi-dart turns (M4-01): see the module docstring.
        self.turn_base = None
        self.pending = []            # public proposal dicts of the pending darts, oldest first
        self.tracked = []            # TrackedDart, oldest first
        self.dart_session = secrets.token_hex(4)  # dart ids are '<session>-<n>' (replay maps them by n)
        self.dart_count = 0
        self.board_checked = False   # the board-moved check already ran in this large-change episode
        self.counters = {'board_cleared': 0, 'retracted': 0, 'pulled': 0, 'separated': 0}
        # The board known to hold no darts (QA M4 H1), in warp pixels: from the calibration image until a cleared
        # board is seen. A change where the frame goes back to it is a pulled dart, never a new one.
        self.empty = None
        # The turn reference kept through an invalidation (stream drop, realign): restored by align() when the
        # board has not moved, so the darts already in the board stay known (QA M4 H1).
        self.suspended_turn = None
        self.board_warning = None    # the board did not look empty at calibration / Board clear (QA M4 M3, M4)
        self.aligned = False; self.message = 'Connect the phone rear camera to begin'; self.version = 0
        self.segmentation = None
        self.verified_version = None
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        self.orb = cv2.ORB_create(nfeatures=2500)
        self.diagnostics = {}; self.unsettled_since = None; self.large_since = None
        self.motion_history = collections.deque(maxlen=60)
        # The last few still warped frames, (version, warp): averaged before comparing, so camera grain (a zoomed-in
        # phone picture) cancels out while a dart, which does not move, stays.
        self.still_warps = collections.deque(maxlen=vision_tuning.STILL_AVERAGE_FRAMES)  # live numbers for the Setup page
        # Camera pose from calibration (M1-04). pose is the effective pose (manual override applied).
        self.camera_hfov = vision_pose.DEFAULT_CAMERA_HFOV
        self.mount_side = None
        self.solved_pose = None
        self.pose = None
        self.rule = DEFAULT_RULE
        self.tip_bias_mm = TIP_BIAS_MM
        # Calibration refinement (M1-05c): report of the last calibrate(), shown by the setup UI.
        self.refine_calibration = CALIBRATION_REFINEMENT
        self.calibration_quality = None
        # Threading boundary (M1-06). Vision methods do not lock themselves: the server's vision worker
        # (vision_worker.py) holds self.lock around every action and frame, then calls publish().
        # Readers on other threads use current_state() and never wait for the lock.
        self.lock = threading.RLock()
        self.state_snapshot = None
        self.publish()
    def decode(self, data):
        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None or frame.shape[0] < 200 or frame.shape[1] < 200 or max(frame.shape[:2]) > 1920:
            raise ValueError('Use a valid JPEG/PNG between 200px and 1920px per side')
        return frame
    @property
    def proposal(self):
        """The oldest pending dart (the one a commit applies to), or None. Kept for older callers."""
        return self.pending[0] if self.pending else None

    @proposal.setter
    def proposal(self, value):
        # Tests and older callers set one untracked proposal (or None for none).
        self.pending = [] if value is None else [value]

    def fresh(self): return self.frame is not None and time.time() - self.timestamp < 5
    def verified(self): return self.aligned and self.fresh() and self.verified_version == self.version
    def warp(self, frame): return cv2.warpPerspective(frame, self.H, (SIZE, SIZE))
    def invalidate(self, message):
        if self.turn_base is not None and self.suspended_turn is None:
            self.suspended_turn = (self.turn_base, self.base, self.tracked, self.pending)
        self.aligned = False; self.verified_version = None; self.pending = []; self.tracked = []
        self.version += 1; self.message = message
        # The pose belongs to the geometry just invalidated; a successful calibrate()/align() re-solves it.
        # mount_side is kept on purpose: it describes where the phone is mounted, not this calibration.
        self.solved_pose = None; self.pose = None
        self.segmentation = None
    def reset_camera(self):
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        self.timestamp = 0
        self.invalidate('Camera session changed. Connect the camera, check alignment, then verify.')
        self.suspended_turn = None
    def begin_calibration(self):
        if not self.fresh(): raise ValueError('Connect the live phone camera before calibration')
        self.invalidate('Image frozen: select 20, 6, 3, then 11. Keep the phone streaming.')
        self.suspended_turn = None  # a new calibration starts a new turn reference
        self.calibration_frame = self.frame.copy()
        self.calibration_id = secrets.token_urlsafe(18)
        self.calibration_started = time.time()
        return {'snapshot_id': self.calibration_id, 'expires_in': CALIBRATION_SECONDS}
    def snapshot_frame(self, snapshot_id):
        if not isinstance(snapshot_id, str) or not self.calibration_id or snapshot_id != self.calibration_id:
            raise ValueError('Calibration image was replaced or cancelled. Select Set four points again.')
        if time.time() - self.calibration_started > CALIBRATION_SECONDS:
            self.cancel_calibration()
            raise ValueError('Calibration image expired after 5 minutes. Select Set four points again.')
        return self.calibration_frame
    def cancel_calibration(self):
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        self.invalidate('Calibration cancelled. Select Set four points to try again.')
    def calibrate(self, points, snapshot_id=None):
        if not self.fresh(): raise ValueError('Connect a live camera first (frame must be under 5 seconds old)')
        source = self.snapshot_frame(snapshot_id) if snapshot_id is not None else self.frame
        if source.shape != self.frame.shape:
            raise ValueError('Camera dimensions changed during calibration. Select Set four points again.')
        p = np.asarray(points, dtype=np.float32)
        h,w = source.shape[:2]
        if p.shape != (4,2) or not np.isfinite(p).all() or (p < 0).any() or (p[:,0] >= w).any() or (p[:,1] >= h).any():
            raise ValueError('Select four valid points inside the camera image')
        if not cv2.isContourConvex(p.reshape(-1,1,2)) or cv2.contourArea(p, oriented=True) <= 0:
            raise ValueError('Click the points in order: 20 (top), 6 (right), 3 (bottom), 11 (left) of the picture. '
                             'If 20 is not at the top of the picture, turn the phone or the number ring.')
        if abs(cv2.contourArea(p)) < w*h*.01:
            raise ValueError('The board is too small in the picture. Use the Zoom slider in step 1 so the board fills '
                             'most of the picture, then set the four points again.')
        lengths = np.linalg.norm(p - np.roll(p,1,axis=0), axis=1)
        if min(lengths) < 40 or max(lengths) / min(lengths) > 4:
            raise ValueError('Board is too small or camera angle too steep')
        self.H = cv2.getPerspectiveTransform(p, TARGETS)
        self.calibration_quality = self.refine_clicks(source)
        self.update_pose()
        self.reference = source.copy(); self.reference_H = self.H.copy()
        self.empty = None; self.suspended_turn = None  # the board is checked against this image from now on
        self.reference_mask = np.zeros((h,w), np.uint8)
        cv2.fillConvexPoly(self.reference_mask, p.astype(np.int32), 255)
        self.ref_kp,self.ref_desc = self.orb.detectAndCompute(self.reference, self.reference_mask)
        self.verified_version = None
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        if snapshot_id is not None:
            # Selected points belong to the frozen source, never the newest frame.
            # Match that reference onto the live image before accepting its geometry.
            try: self.align()
            except ValueError as error:
                self.message = str(error)
                raise
        else:
            self.aligned = True; self.version += 1; self.reset_base()
        self.message = 'Calibration complete. Check the four markers on the LIVE image, then verify.'
        if self.calibration_quality['method'] == 'clicks' and self.refine_calibration:
            self.message = ('Calibration complete from your four points only (automatic board fit not confident: '
                            + self.calibration_quality['reason'] + '). Check the markers on the LIVE image, then verify.')
        # The calibration image is the camera's empty board (QA M4 M3): warp it, never block on it.
        marks = board_marks_mm2(self.empty_board())
        self.calibration_quality['board_marks_mm2'] = round(marks, 1)
        self.calibration_quality['board_empty'] = marks <= vision_tuning.EMPTY_BOARD_MARKS_MM2
        self.board_warning = None if self.calibration_quality['board_empty'] else BOARD_NOT_EMPTY
        if self.board_warning:
            self.message += ' ' + self.board_warning
        return {'ok': True, 'message': self.message, 'calibration': dict(self.calibration_quality)}

    def refine_clicks(self, source):
        """Refine self.H (from the four clicks) on the calibration image; returns the quality report.

        Keeps the click homography when the refinement is not confident (vision_calibrate.refine).
        """
        if not self.refine_calibration:
            return vision_calibrate.clicks_report('refinement disabled', confidence=None)
        self.H, quality = vision_calibrate.refine(source, self.H, SCALE, CENTER)
        return quality
    def overlay(self):
        if self.H is None: return None
        try: return cv2.perspectiveTransform(TARGETS.reshape(1,-1,2),np.linalg.inv(self.H))[0]
        except (ValueError,cv2.error,np.linalg.LinAlgError): return None
    def align(self, preserve_verification=False):
        if not self.fresh():
            self.verified_version = None
            raise ValueError('Camera frame is stale; reconnect phone')
        if self.reference is None: raise ValueError('Complete initial four-point calibration first')
        old_verified = self.verified()
        old_overlay = self.overlay()
        kp,desc = self.orb.detectAndCompute(self.frame, None)
        self.invalidate('Checking board alignment…')
        try:
            H, inliers = self.match_reference(kp, desc)
            current_targets = cv2.perspectiveTransform(TARGETS.reshape(1,-1,2), np.linalg.inv(H))[0]
            height,width = self.frame.shape[:2]
            if not np.isfinite(current_targets).all() or (current_targets < 0).any() or (current_targets[:,0]>=width).any() or (current_targets[:,1]>=height).any():
                raise ValueError('Board is outside camera frame')
            unchanged = old_overlay is not None and np.max(np.linalg.norm(current_targets-old_overlay,axis=1)) <= 2
            self.H = H; self.aligned = True
            suspended, self.suspended_turn = self.suspended_turn, None
            if unchanged and suspended is not None:
                # The board has not moved: keep the turn (darts in the board, pending darts) as it was.
                self.turn_base, self.base, self.tracked, self.pending = suspended
                self.last_warp = self.warp(self.frame); self.stable = 0; self.segmentation = None
            else:
                self.reset_base()
            self.update_pose()
            if preserve_verification and old_verified and unchanged:
                self.verified_version = self.version
            self.message = 'Ready to play' if self.verified() else 'Board realigned. Check the live overlay, then verify.'
            return {'ok':True, 'inliers':int(inliers.sum()), 'message':self.message}
        except (ValueError, np.linalg.LinAlgError, cv2.error) as error:
            self.message = str(error)
            raise ValueError('Alignment failed: '+str(error)) from error
    def match_reference(self, kp=None, desc=None):
        """(H, inlier mask): the board map of the current frame. ORB features first; when they are not
        confident (a zoomed-in, noisy picture where every sector looks alike), a direct image fit (ECC) against
        the calibration image. Raises ValueError when neither is confident."""
        try:
            return self.orb_match_reference(kp, desc)
        except (ValueError, cv2.error) as error:
            try:
                return self.ecc_match_reference(), np.ones(1, bool)
            except (ValueError, cv2.error, np.linalg.LinAlgError):
                raise ValueError(str(error)) from None

    def ecc_match_reference(self):
        """Board map from an intensity fit (cv2.findTransformECC, homography) of the current frame to the
        calibration image inside the board. Confident only when the pictures correlate strongly."""
        if self.reference is None or self.frame is None or self.reference.shape != self.frame.shape:
            raise ValueError('No calibration image of this size')
        s = 0.5 if max(self.frame.shape[:2]) > 1000 else 1.0
        def prepare(image):
            gray = cv2.cvtColor(cv2.resize(image, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            return cv2.GaussianBlur(gray, (5, 5), 0)
        reference, current = prepare(self.reference), prepare(self.frame)
        mask = cv2.resize(self.reference_mask, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_NEAREST)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5)
        rho, warp = cv2.findTransformECC(reference, current, np.eye(3, dtype=np.float32), cv2.MOTION_HOMOGRAPHY,
                                         criteria, mask, 5)
        if rho < vision_tuning.ECC_MIN_CORRELATION:
            raise ValueError(f'Board picture does not match the calibration image (correlation {rho:.2f})')
        scale = np.diag([s, s, 1.0])
        reference_to_current = np.linalg.inv(scale) @ warp.astype(np.float64) @ scale
        if np.linalg.det(reference_to_current[:2, :2]) <= 0:
            raise ValueError('Board picture is mirrored relative to the calibration image')
        # Only small movements are trusted: the board is nearly symmetric, so a large fit could land on the wrong sector.
        markers = cv2.perspectiveTransform(TARGETS.reshape(1, -1, 2), np.linalg.inv(self.reference_H))[0]
        moved = cv2.perspectiveTransform(markers.reshape(1, -1, 2).astype(np.float64), reference_to_current)[0]
        if np.max(np.linalg.norm(moved - markers, axis=1)) > vision_tuning.ECC_MAX_SHIFT_PX:
            raise ValueError('Board moved too far to realign automatically; set four points again')
        return self.reference_H @ np.linalg.inv(reference_to_current)

    def orb_match_reference(self, kp=None, desc=None):
        """(H, inlier mask): the board map of the current frame from ORB matches with the calibration
        reference. Raises ValueError when the fit is not confident."""
        if kp is None:
            kp, desc = self.orb.detectAndCompute(self.frame, None)
        if desc is None or self.ref_desc is None:
            raise ValueError('Not enough board detail; improve light or recalibrate')
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc, self.ref_desc, k=2)
        good = [m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance < .7*n.distance]
        if len(good) < 25: raise ValueError('Could not find the board from the saved calibration (zoom or phone moved?). Take the darts out, then Freeze and set four points again.')
        src = np.float32([kp[m.queryIdx].pt for m in good]); dst = np.float32([self.ref_kp[m.trainIdx].pt for m in good])
        transform,mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.5)
        inliers = mask.ravel().astype(bool) if mask is not None else np.zeros(len(good),bool)
        if transform is None or inliers.sum() < 20 or inliers.mean() < .6:
            raise ValueError('Board alignment is uncertain; use four-point calibration')
        hull = cv2.convexHull(dst[inliers])
        if cv2.contourArea(hull) < cv2.countNonZero(self.reference_mask)*.25:
            raise ValueError('Matching features cover too little of board; recalibrate')
        return self.reference_H @ transform, inliers

    def update_pose(self):
        """Recompute the camera pose and foot point from the current H. Never raises."""
        if self.H is None or self.frame is None:
            self.solved_pose = None
        else:
            height, width = self.frame.shape[:2]
            self.solved_pose = vision_pose.estimate_pose(self.H, width, height, SCALE, CENTER, self.camera_hfov)
        self.apply_mount_side()

    def apply_mount_side(self):
        if self.mount_side is not None:
            self.pose = vision_pose.manual_pose(self.mount_side, self.solved_pose)
        else:
            self.pose = self.solved_pose

    def set_mount_side(self, mount_side):
        """Manual foot-point override: 'top', 'bottom', 'left', 'right', or None to use the solved pose."""
        if mount_side is not None and mount_side not in vision_pose.MOUNT_SIDES:
            raise ValueError('mount_side must be top, bottom, left, right or none')
        self.mount_side = mount_side
        self.apply_mount_side()

    def foot_point(self):
        """Foot point in board mm, or None when no pose is available."""
        if self.pose is None or self.pose.get('foot') is None:
            return None
        return self.pose['foot']

    def verify(self, version):
        if not self.fresh() or not self.aligned or self.calibration_id:
            raise ValueError('Connect the camera and complete calibration/alignment first')
        if type(version) is not int or version != self.version:
            raise ValueError('The overlay changed. Check the latest live markers before verifying again.')
        self.verified_version = version; self.message = 'Ready to play'
    def reset_base(self):
        """Start a new turn reference from the current frame (new game, baseline button, board cleared)."""
        if not self.aligned or not self.fresh(): raise ValueError('Calibrate with a fresh camera frame first')
        self.base = self.current_warp(); self.last_warp = self.warp(self.frame); self.turn_base = self.base
        self.stable = 0; self.pending = []; self.tracked = []; self.segmentation = None
        self.suspended_turn = None

    def board_is_empty(self):
        """The host says the board is empty now (Board clear · reset image): a new turn reference, and, if the
        picture does look empty, the camera's empty board (QA M4 M3: recovers a calibration made with darts in
        the board). A board with marks keeps the old empty board (QA M4 M4). Returns the measurement."""
        self.reset_base()
        marks = board_marks_mm2(self.base)
        empty = marks <= vision_tuning.EMPTY_BOARD_MARKS_MM2
        if empty:
            self.empty = self.base
            self.board_warning = None
            self.message = 'Board clear: this picture is now the empty board.'
        else:
            self.board_warning = BOARD_STILL_HAS_DARTS
            self.message = self.board_warning
        # Logged with the action (events.jsonl), so the threshold can be tuned on real boards.
        return {'board_empty': empty, 'board_marks_mm2': round(marks, 1),
                'threshold_mm2': vision_tuning.EMPTY_BOARD_MARKS_MM2}

    def current_warp(self):
        """The current board picture (warp pixels): the average of the still frames seen with the current geometry
        (camera grain averages out), else the newest frame."""
        warps = [w for version, w in self.still_warps if version == self.version]
        if len(warps) < 2:
            return self.warp(self.frame)
        # Only frames that show the same board as the newest: a dart that landed with little motion must not be
        # averaged with the frames from before it landed.
        newest = cv2.GaussianBlur(cv2.cvtColor(warps[-1], cv2.COLOR_BGR2GRAY), (5, 5), 0)
        same = [warps[-1]]
        for older in reversed(warps[:-1]):
            gray = cv2.GaussianBlur(cv2.cvtColor(older, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            if np.mean(cv2.absdiff(gray, newest) > vision_tuning.MOTION_PIXEL_DELTA) > vision_tuning.AVERAGE_SAME_FRACTION:
                break
            same.append(older)
        if len(same) < 2:
            return warps[-1]
        return np.mean(np.stack(same), axis=0).round().astype(np.uint8)

    def empty_board(self):
        """The board with no darts (warp pixels), or None: the last cleared board seen, else the calibration
        image (calibrate on an empty board)."""
        if self.empty is None and self.reference is not None and self.reference_H is not None:
            self.empty = cv2.warpPerspective(self.reference, self.reference_H, (SIZE, SIZE))
        return self.empty

    def absorb(self):
        """A dart was scored by hand: the current frame becomes the reference, and the turn goes on."""
        if not self.aligned or not self.fresh(): raise ValueError('Calibrate with a fresh camera frame first')
        self.base = self.current_warp()
        if self.turn_base is None: self.turn_base = self.base
        self.pending = [p for p in self.pending if p.get('id')]  # an untracked proposal is now part of the board

    def commit_dart(self, dart_id):
        """The host committed (accepted or corrected) pending dart dart_id: it stays in the reference.
        An id vision does not track (a proposal set directly) is handled like a manual score (absorb)."""
        dart = next((d for d in self.tracked if d.id == dart_id), None)
        if dart is None:
            self.absorb()
            return
        dart.status = 'committed'
        self.pending = [p for p in self.pending if p.get('id') != dart_id]

    def end_turn(self):
        """Next player: darts still pending were not scored for this turn and are dropped (they stay in the
        reference image, so they are not proposed again)."""
        for dart in self.tracked:
            if dart.status == 'pending':
                dart.status = 'dismissed'
        self.pending = []
        if self.suspended_turn is not None:  # also in a turn kept through a realign
            turn_base, base, tracked, _ = self.suspended_turn
            for dart in tracked:
                if dart.status == 'pending':
                    dart.status = 'dismissed'
            self.suspended_turn = (turn_base, base, tracked, [])
    def ingest(self, data):
        # data: encoded image bytes (/api/frame) or a decoded BGR frame from a camera source (M1-07).
        frame = data if isinstance(data, np.ndarray) else self.decode(data)
        if self.frame is not None and not self.fresh():
            self.invalidate('Camera reconnected. Check / realign board, then verify the overlay.')
        if self.frame is not None and frame.shape != self.frame.shape:
            self.invalidate('Camera dimensions changed; recalibrate')
        self.frame = frame; self.timestamp = time.time()
        if not self.aligned: return
        warped = self.warp(frame)
        # Blurred first: camera grain (a zoomed-in phone picture) must not count as motion, a dart still does.
        gray = cv2.GaussianBlur(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        oldgray = cv2.GaussianBlur(cv2.cvtColor(self.last_warp, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        motion = float(np.mean(cv2.absdiff(gray, oldgray) > vision_tuning.MOTION_PIXEL_DELTA))
        self.last_warp = warped
        self.diagnostics = {**self.diagnostics, 'motion_pct':round(motion*100, 2),
                            'still_pct':round(vision_tuning.MOTION_STILL_FRACTION*100, 2)}
        if motion > vision_tuning.MOTION_LARGE_FRACTION:
            # A hand or a person: pending darts stay (they were seen on a still board), nothing new is read.
            self.stable = 0; self.board_checked = False
            self.message = 'Motion detected; wait. If board moved, check / realign board.'
            return
        # The still limit follows the camera's own noise floor (a real phone picture is never perfectly still):
        # twice the quiet level of the last few seconds, between the simulated default and MOTION_STILL_MAX.
        self.motion_history.append(motion)
        floor = float(np.percentile(self.motion_history, 20)) if len(self.motion_history) >= 10 else 0.0
        still_limit = min(max(vision_tuning.MOTION_STILL_FRACTION, 2 * floor + 0.001), vision_tuning.MOTION_STILL_MAX)
        self.diagnostics['still_pct'] = round(still_limit * 100, 2)
        self.stable = self.stable + 1 if motion < still_limit else 0
        if self.stable: self.still_warps.append((self.version, warped))
        else: self.still_warps.clear()
        now = time.monotonic()
        if self.stable:
            self.unsettled_since = None
            if self.message.startswith('The picture never settles'):
                self.message = 'Ready to play' if self.verified() else 'Check the live overlay, then verify.'
        elif self.unsettled_since is None: self.unsettled_since = now
        elif now - self.unsettled_since > vision_tuning.UNSETTLED_SECONDS and not self.pending:
            # Silent waiting looked like "not detecting" on the real board: say why.
            self.message = (f'The picture never settles ({motion*100:.1f}% of the board keeps changing), so no dart '
                            'is read. Lock focus, exposure and white balance in IP Webcam, and keep lights steady.')
        if self.stable < vision_tuning.STABLE_FRAMES: return
        warped = self.current_warp()
        foot_mm = self.foot_point()
        foot = None if foot_mm is None else np.asarray(foot_mm, np.float32) * SCALE + CENTER
        segmentation = self.segment(warped, self.base, foot)
        self.diagnostics = {**self.diagnostics, 'last_look':segmentation.kind, 'looked_at':round(time.time(), 1),
                            'changed_blobs':len(segmentation.groups),
                            'changed_pct':round(100 * float(segmentation.changed_fraction or 0), 1),
                            'gains':[round(float(g), 2) for g in (segmentation.gains or [])]}
        if segmentation.kind not in ('none', 'large_change'):
            removed = self.remove_missing_darts(warped) if self.tracked else []
            pulled = any(dart.status != 'pending' for dart in removed)
            if self.board_cleared(warped, foot, against_turn=bool(self.tracked) or pulled):
                return
            if removed:
                segmentation = self.segment(warped, self.base, foot)
                if segmentation.kind == 'none':
                    return  # keep the message saying which dart went
        if segmentation.kind in ('large_change', 'noisy'):
            if segmentation.kind == 'large_change':
                self.large_change()
            else:
                self.message = SEGMENTATION_MESSAGES['noisy']
            # Still, the board did not move, but the picture differs from the reference everywhere or in many small
            # places (light, exposure or camera settings changed): after a few seconds take a new turn reference
            # instead of reporting it for ever. Waiting darts are never absorbed.
            now = time.monotonic()
            if self.large_since is None: self.large_since = now
            elif (self.aligned and not self.pending
                    and now - self.large_since > vision_tuning.LARGE_CHANGE_REBASE_SECONDS):
                self.reset_base(); self.large_since = None
                self.diagnostics['refreshed'] = self.diagnostics.get('refreshed', 0) + 1
                self.message = ('The picture of the board changed (light or camera settings): the camera refreshed '
                                'its reference. Throw when ready.')
            return
        self.large_since = None
        self.board_checked = False
        if segmentation.kind == 'none':
            if self.pending: self.message = PENDING_MESSAGE
            elif self.verified(): self.message = SEGMENTATION_MESSAGES['none']  # never "Ready" before verify
            return
        if segmentation.kind not in ('dart', 'multiple'):
            self.message = SEGMENTATION_MESSAGES[segmentation.kind]
            return
        groups, pieces = self.without_holes(warped, segmentation.candidates), False
        if not groups:
            return  # only darts the camera was not tracking were pulled (QA M4 H1)
        if len(groups) > 1 and not self.apart(groups):
            groups, pieces = [functools.reduce(vision_segment.Blob.merged, groups)], True  # one dart in pieces?
        free = vision_tuning.MAX_PENDING_DARTS - len(self.pending)
        if len(groups) > free:
            self.message = ('Three camera darts are waiting: accept or correct them first' if free <= 0
                            else SEGMENTATION_MESSAGES['multiple'])
            return
        self.add_darts(warped, segmentation, groups, pieces)

    @staticmethod
    def apart(groups):
        """True when every two dart-like blobs are at least SEPARATE_GAP_MM apart (separate darts)."""
        limit = (vision_tuning.SEPARATE_GAP_MM * SCALE) ** 2
        return all(float(vision_segment.squared_distances(a.outline, b.outline).min()) >= limit
                   for a, b in itertools.combinations(groups, 2))

    def segment(self, warped, base, foot):
        segmentation = vision_segment.segment(warped, base, SCALE, CENTER, BOARD_CHANGE_RADIUS_MM, foot)
        self.segmentation = segmentation
        return segmentation

    def add_darts(self, warped, segmentation, groups, pieces=False):
        """New darts (segmentation candidates) become pending darts and part of the reference image.
        pieces: the one group is several blobs merged (flagged for a check)."""
        found = []
        regions = [self.dart_region(group.points) for group in groups]
        for index, group in enumerate(groups):
            tip, confidence, rule = self.locate_tip(group.outline, group.points, segmentation.difference)
            if tip is None:
                continue
            x, y = (tip - CENTER) / SCALE
            self.dart_count += 1
            proposal = {**score_point(float(x), float(y)), 'x': float(x), 'y': float(y),
                        'id': f'{self.dart_session}-{self.dart_count}',
                        'review_required': True, 'near_wire': near_wire(float(x), float(y)),
                        'confidence': confidence, 'rule': rule, 'check': [],
                        'note': 'Prototype endpoint guess. Verify actual tip; hidden tips can be wrong.'}
            if confidence == 'low':
                proposal['check'].append(vision_tuning.CHECK_TIP_UNCLEAR)
            if pieces:
                proposal['check'].append(vision_tuning.CHECK_PIECES)
            # Occlusion-aware confidence (M4-02): the darts already in the board, and the others found now.
            occluders = [d.region for d in self.tracked] + regions[:index] + regions[index + 1:]
            touch, cone = self.occlusion_distances(tip, functools.reduce(np.logical_or, occluders)) \
                if occluders else (None, None)
            proposal['occlusion'] = {'any_mm': None if touch is None else round(touch, 2),
                                     'cone_mm': None if cone is None else round(cone, 2)}
            if self.hidden_tip_risk(touch, cone):
                proposal['check'].append(vision_tuning.CHECK_HIDDEN_TIP)
            if proposal['check']:
                proposal['confidence'] = 'low'  # waits for Accept or a tap (no auto-commit)
            if len(groups) > 1:
                proposal['together'] = len(groups)  # landed in the same still frame: throw order unknown
            found.append(TrackedDart(proposal['id'], proposal, 'pending', regions[index], self.base))
        if not found:
            self.message = 'Change is not dart-shaped; use manual scoring'
            return
        if len(found) > 1:
            self.counters['separated'] += 1
        self.tracked = (self.tracked + found)[-MAX_TRACKED_DARTS:]
        self.pending = self.pending + [dart.proposal for dart in found]
        self.base = warped
        self.message = PENDING_MESSAGE

    def occlusion_distances(self, tip, occluders):
        """(nearest earlier-dart pixel in any direction, nearest within OCCLUSION_CONE_DEG of the direction from
        the visible tip toward the foot point), in mm, within vision_tuning.OCCLUSION_SEARCH_MM; None where there is none.

        occluders: bool warp mask of the darts already in the board (and other darts found in the same frame).
        """
        search = vision_tuning.OCCLUSION_SEARCH_MM * SCALE
        x0, y0 = np.maximum(np.floor(tip - search).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(tip + search).astype(int) + 1, SIZE)
        ys, xs = np.nonzero(occluders[y0:y1, x0:x1])
        if len(xs) == 0:
            return None, None
        offsets = np.column_stack([xs + x0, ys + y0]).astype(np.float32) - tip
        distances = np.linalg.norm(offsets, axis=1)
        nearest = float(distances.min()) / SCALE
        foot_mm = self.foot_point()
        if foot_mm is None:
            return nearest, None
        toward = np.asarray(foot_mm, np.float32) * SCALE + CENTER - tip
        toward /= max(float(np.linalg.norm(toward)), 1e-6)
        cosines = (offsets @ toward) / np.maximum(distances, 1e-6)
        inside = cosines >= np.cos(np.radians(vision_tuning.OCCLUSION_CONE_DEG))
        return nearest, (float(distances[inside].min()) / SCALE if inside.any() else None)

    @staticmethod
    def hidden_tip_risk(touch, cone):
        """M4-02: an earlier dart touches the visible tip, or lies just past it on the camera side (toward the
        foot point), so the real tip may be hidden behind it. Thresholds: vision_tuning.OCCLUSION_*."""
        return ((touch is not None and touch <= vision_tuning.OCCLUSION_TOUCH_MM)
                or (cone is not None and cone <= vision_tuning.OCCLUSION_REACH_MM))

    def dart_region(self, points):
        region = np.zeros((SIZE, SIZE), np.uint8)
        region[points[:, 1].astype(int), points[:, 0].astype(int)] = 1
        grow = max(1, int(round(vision_tuning.DART_MASK_GROW_MM * SCALE)))
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
        return region.astype(bool)

    def board_cleared(self, warped, foot, against_turn=True):
        """Every dart was pulled: the board matches the start of the turn (against_turn) or the known empty
        board again. Starts a new turn reference. The empty board works even when the camera does not know
        which darts are in the board (after a restart or a realign, or for darts scored by hand)."""
        empty = self.empty_board()
        references = ([self.turn_base] if against_turn else []) + [empty]
        for reference in references:
            if reference is None or vision_segment.segment(
                    warped, reference, SCALE, CENTER, BOARD_CHANGE_RADIUS_MM, foot).kind != 'none':
                continue
            self.reset_base()
            if reference is empty:
                self.board_warning = None
                # The freshest picture of the empty board. Never from a turn reference: after a restart or a
                # moved board it can hold darts the camera does not know about (QA M4 H1b).
                self.empty = warped
            self.counters['board_cleared'] += 1
            self.message = 'Board cleared: ready for the next turn'
            return True
        return False

    def without_holes(self, warped, groups):
        """Drop changes that are holes: a dart the camera did not track was pulled, and the board there looks
        empty again. Their part of the reference image is updated; they are never proposed (QA M4 H1)."""
        empty = self.empty_board()
        if empty is None:
            return groups
        samples = vision_segment.gain_samples(SIZE, CENTER, BOARD_CHANGE_RADIUS_MM * SCALE)
        now = warped.astype(np.float32) / np.asarray(vision_segment.illumination_gains(warped, empty, samples), np.float32)
        base = self.base.astype(np.float32) / np.asarray(
            vision_segment.illumination_gains(self.base, empty, samples), np.float32)
        kept, holes = [], []
        for group in groups:
            cols, rows = group.points[:, 0].astype(int), group.points[:, 1].astype(int)
            behind = empty[rows, cols].astype(np.float32)
            back = np.abs(now[rows, cols] - behind).max(axis=1) < vision_tuning.REVERT_PIXEL_DELTA
            telling = np.abs(base[rows, cols] - behind).max(axis=1) >= vision_tuning.REVERT_PIXEL_DELTA
            hole = telling.sum() >= 0.5 * len(rows) and \
                (back & telling).sum() >= vision_tuning.REMOVED_FRACTION * telling.sum()
            (holes if hole else kept).append(group)
        if holes:
            patched = self.base.copy()
            for group in holes:
                region = self.dart_region(group.points)
                patched[region] = warped[region]
            self.base = patched
            self.counters['pulled'] += len(holes)
            self.message = 'A dart was pulled out'
        return kept

    def remove_missing_darts(self, warped):
        """Tracked darts whose pixels went back to the board behind them: retract pending ones (bounce-out),
        forget committed ones (pulled). Their region of the reference is replaced by the current frame.
        Returns the removed darts."""
        gains = vision_segment.illumination_gains(
            warped, self.base, vision_segment.gain_samples(SIZE, CENTER, BOARD_CHANGE_RADIUS_MM * SCALE))
        corrected = warped.astype(np.float32) / np.asarray(gains, np.float32)
        removed = []
        for dart in self.tracked:
            rows, cols = np.nonzero(dart.region)
            now = corrected[rows, cols]
            back = np.abs(now - dart.before[rows, cols]).max(axis=1) < vision_tuning.REVERT_PIXEL_DELTA
            moved = np.abs(now - self.base[rows, cols]).max(axis=1) >= vision_tuning.REVERT_PIXEL_DELTA
            # Only pixels where the dart made a difference can show that it left.
            telling = np.abs(dart.before[rows, cols].astype(np.float32) - self.base[rows, cols]).max(axis=1) \
                >= vision_tuning.REVERT_PIXEL_DELTA
            if telling.sum() and (back & moved & telling).sum() >= vision_tuning.REMOVED_FRACTION * telling.sum():
                removed.append(dart)
        if not removed:
            return removed
        base = self.base.copy()
        for dart in removed:
            base[dart.region] = warped[dart.region]
            self.tracked.remove(dart)
            if dart.status == 'pending':
                self.pending = [p for p in self.pending if p['id'] != dart.id]
                self.counters['retracted'] += 1
                self.message = 'A dart fell out: its camera score was withdrawn'
            else:
                self.counters['pulled'] += 1
                self.message = 'A dart was pulled out'
        self.base = base
        return removed

    def large_change(self):
        """A large still change. Once per episode, check whether the board itself moved (ORB fit against the
        calibration reference): only then does the geometry need alignment. Otherwise wait it out."""
        if not self.board_checked:
            self.board_checked = True
            shift = self.board_shift()
            if shift is not None and shift > vision_tuning.BOARD_MOVED_PX:
                self.invalidate('Board or camera moved: check / realign board before continuing')
                return
        self.message = ('Something is in front of the board; waiting. '
                        'If this stays, check / realign board.')

    def board_shift(self):
        """How far (image px) the calibration markers moved, from an ORB fit of the current frame; None
        when the fit is not confident (the board is covered, dark or too changed to tell)."""
        try:
            H, _ = self.match_reference()
            now = cv2.perspectiveTransform(TARGETS.reshape(1, -1, 2), np.linalg.inv(H))[0]
        except (ValueError, np.linalg.LinAlgError, cv2.error):
            return None
        before = self.overlay()
        return None if before is None else float(np.max(np.linalg.norm(now - before, axis=1)))

    def locate_tip(self, contour, pixels=None, difference=None):
        """Return (tip warp px, confidence, rule) for one dart, or (None, None, rule).

        contour: the dart's outline points (axis, elongation and ends come from it).
        pixels: all of the dart's pixels for refine_tip (default: contour).
        difference: the change image, for the sub-pixel edge in refine_tip.

        'foot' rule: the end of the blob's principal axis nearer the camera foot point,
        refined along the point's own axis (refine_tip), then extended by tip_bias_mm
        toward the foot point. A blob that is not elongated (a dart pointing at the
        lens) uses the contour pixel nearest the foot point with low confidence.
        Without a pose, the legacy 'centre' rule is used.
        """
        foot_mm = self.foot_point()
        rule = self.rule
        if rule == 'foot' and foot_mm is None:
            rule = 'centre'
        _, vectors, values = cv2.PCACompute2(contour, mean=None)
        elongated = values[0, 0] / max(values[1, 0], 1) >= 3
        if rule == 'centre':
            if not elongated:
                return None, None, rule
            direction = vectors[0]
            projection = contour @ direction
            ends = [contour[np.argmin(projection)], contour[np.argmax(projection)]]
            tip = min(ends, key=lambda p: np.linalg.norm(p - CENTER))
            confidence = 'high' if self.rule == 'centre' else 'low'
            return tip, confidence, rule
        foot = np.asarray(foot_mm, dtype=np.float32) * SCALE + CENTER
        if not elongated:
            nearest = contour[np.argmin(np.linalg.norm(contour - foot, axis=1))]
            return nearest, 'low', rule
        direction = vectors[0].astype(np.float32)
        projection = contour @ direction
        ends = [contour[np.argmin(projection)], contour[np.argmax(projection)]]
        tip = min(ends, key=lambda p: np.linalg.norm(p - foot))
        if float((foot - tip) @ direction) < 0:
            direction = -direction
        tip, direction = refine_tip(contour if pixels is None else pixels, tip, direction, difference)
        tip = tip + direction * (self.tip_bias_mm * SCALE)
        return tip, 'high', rule

    def publish(self):
        """Replace state_snapshot with a new state() dict. Call with self.lock held."""
        self.state_snapshot = self.state()
        return self.state_snapshot

    def current_state(self):
        """The latest published state, safe from any thread without the lock.

        Freshness is re-evaluated now from the live frame timestamp, so a camera that stops
        sending frames shows as disconnected even while the worker is busy (for example in align()).
        """
        state = dict(self.state_snapshot)
        timestamp = self.timestamp
        if not timestamp:
            return state
        age = time.time() - timestamp
        state['age_seconds'] = round(age, 1)
        if state['fresh'] and age >= 5:
            state.update(fresh=False, aligned=False, verified=False, proposal=None, pending=[], phase='camera_disconnected')
        if state.get('phase') == 'camera_disconnected':  # never an old "Ready" while the stream is lost
            state['message'] = 'Camera stream lost: waiting for the phone. It reconnects by itself.'
        return state

    def state(self):
        fresh = self.fresh()
        if not fresh: self.verified_version = None
        active = bool(self.calibration_id)
        if active and time.time() - self.calibration_started > CALIBRATION_SECONDS:
            self.cancel_calibration(); active = False
            self.message = 'Calibration image expired. Select Set four points again.'
        if self.frame is None: phase = 'waiting_camera'
        elif not fresh: phase = 'camera_disconnected'
        elif active: phase = 'calibrating'
        elif self.reference is None: phase = 'ready_to_calibrate'
        elif not self.aligned: phase = 'needs_alignment'
        elif not self.verified(): phase = 'review_overlay'
        else: phase = 'ready'
        overlay = self.overlay()
        return {'fresh':fresh, 'age_seconds':round(time.time()-self.timestamp,1) if self.timestamp else None,
                'aligned':self.aligned and fresh, 'verified':self.verified(), 'phase':phase, 'message':self.message,
                'calibration_active':active,
                'calibration_elapsed':int(time.time()-self.calibration_started) if active else None,
                'proposal':self.proposal if fresh else None, 'pending':list(self.pending) if fresh else [],
                'turn':dict(self.counters, tracked=len(self.tracked)), 'board_warning':self.board_warning, 'overlay':overlay.tolist() if overlay is not None else None,
                'version':self.version, 'width':int(self.frame.shape[1]) if self.frame is not None else 0,
                'height':int(self.frame.shape[0]) if self.frame is not None else 0,
                'pose':dict(self.pose) if self.pose is not None else None,
                'foot':self.foot_point(), 'mount_side':self.mount_side,
                'calibration':dict(self.calibration_quality) if self.calibration_quality is not None else None,
                'diagnostics':dict(self.diagnostics, stable=self.stable, stable_needed=vision_tuning.STABLE_FRAMES)}
