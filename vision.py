"""Camera prototype. Every proposed dart requires confirmation by the player."""
import secrets
import threading
import time
import cv2
import numpy as np
from core import score_point, near_wire
import vision_pose
import vision_segment

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
# double ring often projects outside the scoring area.
BOARD_CHANGE_RADIUS_MM = 200.0
# Pixels within this distance of the chosen blob end refine the tip along the point's own axis (mm).
TIP_REFINE_MM = 12.0
# How far beyond the pixel end the half-contrast edge search looks (mm).
EDGE_SEARCH_MM = 2.0
SEGMENTATION_MESSAGES = {
    'none': 'Ready',
    'multiple': 'More than one new dart; enter scores manually',
    'too_large': 'Change is too large for one dart; enter score manually',
}


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
    centre = float(np.median(across[along >= end - 1.5]))
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
        self.base = None; self.last_warp = None; self.stable = 0; self.proposal = None
        self.aligned = False; self.message = 'Connect the phone rear camera to begin'; self.version = 0
        self.segmentation = None
        self.verified_version = None
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        self.orb = cv2.ORB_create(nfeatures=2500)
        # Camera pose from calibration (M1-04). pose is the effective pose (manual override applied).
        self.camera_hfov = vision_pose.DEFAULT_CAMERA_HFOV
        self.mount_side = None
        self.solved_pose = None
        self.pose = None
        self.rule = DEFAULT_RULE
        self.tip_bias_mm = TIP_BIAS_MM
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
    def fresh(self): return self.frame is not None and time.time() - self.timestamp < 5
    def verified(self): return self.aligned and self.fresh() and self.verified_version == self.version
    def warp(self, frame): return cv2.warpPerspective(frame, self.H, (SIZE, SIZE))
    def invalidate(self, message):
        self.aligned = False; self.verified_version = None; self.proposal = None
        self.version += 1; self.message = message
        # The pose belongs to the geometry just invalidated; a successful calibrate()/align() re-solves it.
        # mount_side is kept on purpose: it describes where the phone is mounted, not this calibration.
        self.solved_pose = None; self.pose = None
    def reset_camera(self):
        self.calibration_frame = None; self.calibration_id = None; self.calibration_started = 0
        self.timestamp = 0
        self.invalidate('Camera session changed. Connect the camera, check alignment, then verify.')
    def begin_calibration(self):
        if not self.fresh(): raise ValueError('Connect the live phone camera before calibration')
        self.invalidate('Image frozen: select 20, 6, 3, then 11. Keep the phone streaming.')
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
        if not cv2.isContourConvex(p.reshape(-1,1,2)) or abs(cv2.contourArea(p)) < w*h*.03:
            raise ValueError('Points must trace top, right, bottom, left around the board')
        lengths = np.linalg.norm(p - np.roll(p,1,axis=0), axis=1)
        if min(lengths) < 40 or max(lengths) / min(lengths) > 4:
            raise ValueError('Board is too small or camera angle too steep')
        self.H = cv2.getPerspectiveTransform(p, TARGETS)
        self.update_pose()
        self.reference = source.copy(); self.reference_H = self.H.copy()
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
        return {'ok': True, 'message': self.message}
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
            if desc is None or self.ref_desc is None:
                raise ValueError('Not enough board detail; improve light or recalibrate')
            matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc, self.ref_desc, k=2)
            good = [m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance < .7*n.distance]
            if len(good) < 25: raise ValueError('Cannot confidently locate board; recalibrate manually')
            src = np.float32([kp[m.queryIdx].pt for m in good]); dst = np.float32([self.ref_kp[m.trainIdx].pt for m in good])
            transform,mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.5)
            inliers = mask.ravel().astype(bool) if mask is not None else np.zeros(len(good),bool)
            if transform is None or inliers.sum() < 20 or inliers.mean() < .6:
                raise ValueError('Board alignment is uncertain; use four-point calibration')
            hull = cv2.convexHull(dst[inliers])
            if cv2.contourArea(hull) < cv2.countNonZero(self.reference_mask)*.25:
                raise ValueError('Matching features cover too little of board; recalibrate')
            H = self.reference_H @ transform
            current_targets = cv2.perspectiveTransform(TARGETS.reshape(1,-1,2), np.linalg.inv(H))[0]
            height,width = self.frame.shape[:2]
            if not np.isfinite(current_targets).all() or (current_targets < 0).any() or (current_targets[:,0]>=width).any() or (current_targets[:,1]>=height).any():
                raise ValueError('Board is outside camera frame')
            self.H = H; self.aligned = True; self.reset_base()
            self.update_pose()
            unchanged = old_overlay is not None and np.max(np.linalg.norm(current_targets-old_overlay,axis=1)) <= 2
            if preserve_verification and old_verified and unchanged:
                self.verified_version = self.version
            self.message = 'Ready to play' if self.verified() else 'Board realigned. Check the live overlay, then verify.'
            return {'ok':True, 'inliers':int(inliers.sum()), 'message':self.message}
        except (ValueError, np.linalg.LinAlgError, cv2.error) as error:
            self.message = str(error)
            raise ValueError('Alignment failed: '+str(error)) from error
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
        if not self.aligned or not self.fresh(): raise ValueError('Calibrate with a fresh camera frame first')
        self.base = self.warp(self.frame); self.last_warp = self.base.copy()
        self.stable = 0; self.proposal = None
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
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        oldgray = cv2.cvtColor(self.last_warp, cv2.COLOR_BGR2GRAY)
        motion = np.mean(cv2.absdiff(gray, oldgray) > 22)
        self.last_warp = warped
        if motion > .10:
            self.stable = 0; self.proposal = None
            self.message = 'Motion detected; wait. If board moved, check / realign board.'
            return
        self.stable = self.stable + 1 if motion < .004 else 0
        if self.stable < 3: return
        foot_mm = self.foot_point()
        foot = None if foot_mm is None else np.asarray(foot_mm, np.float32) * SCALE + CENTER
        segmentation = vision_segment.segment(warped, self.base, SCALE, CENTER, BOARD_CHANGE_RADIUS_MM, foot)
        self.segmentation = segmentation
        if segmentation.kind == 'large_change':
            self.invalidate('Large scene change: check board alignment before continuing')
            return
        if segmentation.kind != 'dart':
            self.proposal = None
            self.message = SEGMENTATION_MESSAGES[segmentation.kind]
            return
        tip, confidence, rule = self.locate_tip(segmentation.outline, segmentation.points, segmentation.difference)
        if tip is None:
            self.proposal = None; self.message = 'Change is not dart-shaped; use manual scoring'; return
        x,y = (tip-CENTER)/SCALE
        self.proposal = {**score_point(float(x),float(y)), 'x':float(x), 'y':float(y),
                         'review_required':True, 'near_wire':near_wire(float(x),float(y)),
                         'confidence':confidence, 'rule':rule,
                         'note':'Prototype endpoint guess. Verify actual tip; hidden tips can be wrong.'}
        self.message = 'Possible dart found — confirm or correct score'

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
            state.update(fresh=False, aligned=False, verified=False, proposal=None, phase='camera_disconnected')
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
                'proposal':self.proposal if fresh else None, 'overlay':overlay.tolist() if overlay is not None else None,
                'version':self.version, 'width':int(self.frame.shape[1]) if self.frame is not None else 0,
                'height':int(self.frame.shape[0]) if self.frame is not None else 0,
                'pose':dict(self.pose) if self.pose is not None else None,
                'foot':self.foot_point(), 'mount_side':self.mount_side}
