"""Every camera threshold that must be refit on real-board footage, in one place (M4).

All values here were chosen on synthetic scenes (sim/, seed 1). None of them has seen a real board yet.
Each one is marked REAL DATA: refit it with tools/tune_params.py once trial recordings exist.

Two kinds of entries:
  * Thresholds introduced by M4 (multi-dart turns, occlusion-aware confidence) are defined here and read by
    vision.py at call time, so a tuning run can change them without restarting.
  * Older thresholds still live next to the code that uses them (vision_segment.py, vision.py). TUNABLE lists
    them too, with the module that owns them, so tools/tune_params.py can sweep everything from this table.

No OpenCV here.
"""
import contextlib
import importlib

# ---- Stability gate (moved out of Vision.ingest; values unchanged since M1) ---------------------------------
MOTION_PIXEL_DELTA = 22          # REAL DATA: gray-level change that counts a warp pixel as moving
MOTION_LARGE_FRACTION = 0.10     # REAL DATA: moving share of the warp that means a hand/person in front
MOTION_STILL_FRACTION = 0.004    # REAL DATA: moving share below which a frame counts as still
STABLE_FRAMES = 3                # REAL DATA: still frames in a row before a frame is analysed

# ---- Multi-dart turns (M4-01) -------------------------------------------------------------------------------
MAX_PENDING_DARTS = 3            # a turn has three darts; more new darts than free slots are not separated
# Several dart-like blobs in one still frame are separate darts only when they are at least this far apart.
# Closer blobs are usually one dart cut in two by an earlier dart in front of it (seed 1: every such split had
# a gap of at most 19 mm; two real darts in one frame were 12-300 mm apart, 74 of 76 over 20 mm). Closer
# blobs are proposed as one dart, flagged CHECK_PIECES.
SEPARATE_GAP_MM = 20.0           # REAL DATA
# A tracked dart is "removed" (bounce-out, or pulled) when this share of its pixels went back to what the
# board looked like before it landed. REAL DATA: a dart pulled out leaves a hole; real holes are tiny.
REMOVED_FRACTION = 0.6           # REAL DATA
REVERT_PIXEL_DELTA = 30          # REAL DATA: per-channel difference (0-255) under which a pixel "went back"
DART_MASK_GROW_MM = 1.5          # a tracked dart's pixels, grown by this, are its region (for removal/occlusion)
# A board-moved check after a large change: the ORB board fit may move the overlay by at most this many pixels
# before the board counts as moved (needs alignment). The same 2 px as align(preserve_verification=True).
BOARD_MOVED_PX = 2.0             # REAL DATA

# ---- Occlusion-aware confidence (M4-02) ---------------------------------------------------------------------
# A new dart may be hiding its tip behind an earlier dart when an earlier dart lies right past its visible tip
# on the camera side (toward the foot point): the visible part of the dart then ends at the earlier dart's
# outline, and the tip found is where the dart comes out from behind it, not where it entered the board.
# Chosen on seed 1 (ceiling-1.5ft, realistic, darts 2-3 of 150 turns): an earlier dart within 1 mm past the
# visible tip on the camera side flags 20 of 30 wrong scores and 15% of right ones. Flagging any earlier dart
# within 0.5-1 mm in any direction catches no more and flags more right ones, so it is off (0).
OCCLUSION_TOUCH_MM = 0.0         # REAL DATA: an earlier dart this close to the visible tip in any direction
OCCLUSION_CONE_DEG = 60.0        # REAL DATA: "camera side": within this angle of the tip-to-foot-point direction
OCCLUSION_REACH_MM = 1.0         # REAL DATA: an earlier dart this close past the visible tip on the camera side
OCCLUSION_SEARCH_MM = 15.0       # distances are measured (and logged with each proposal) up to this far
# Calibration check (QA M4 M3): the calibration image becomes the camera's "empty board". A board cell (one
# segment of one ring, wires excluded) has one colour; pixels far from it are marks such as darts. More marked
# area than this warns (never blocks) that the board may not be empty. Synthetic: empty boards 0 mm2, boards
# with a dart 100-2000 mm2. REAL DATA: worn boards and printed logos add marks.
EMPTY_CELL_DELTA = 60            # REAL DATA: per-channel difference (0-255) from the cell's median colour
EMPTY_BOARD_MARKS_MM2 = 30.0     # REAL DATA

CHECK_HIDDEN_TIP = 'tip may be hidden'
CHECK_PIECES = 'seen in pieces'
CHECK_TIP_UNCLEAR = 'tip unclear'


# ---- Registry for tools/tune_params.py ----------------------------------------------------------------------
# name -> (owning module, attribute, small grid to sweep). The default is whatever the module holds now.
TUNABLE = {
    'change_threshold': ('vision_segment', 'CHANGE_THRESHOLD', (24, 30, 36)),
    'noise_factor': ('vision_segment', 'NOISE_FACTOR', (4.0, 5.0, 6.0)),
    'min_dart_mm2': ('vision_segment', 'MIN_DART_MM2', (30.0, 40.0, 55.0)),
    'min_dart_length_mm': ('vision_segment', 'MIN_DART_LENGTH_MM', (12.0, 15.0, 18.0)),
    'stable_frames': ('vision_tuning', 'STABLE_FRAMES', (2, 3, 4)),
    'motion_still_fraction': ('vision_tuning', 'MOTION_STILL_FRACTION', (0.002, 0.004, 0.008)),
    'tip_bias_mm': ('vision', 'TIP_BIAS_MM', (-0.5, 0.0, 0.5, 1.0)),
    'occlusion_reach_mm': ('vision_tuning', 'OCCLUSION_REACH_MM', (0.5, 1.0, 2.0, 3.0)),
    'occlusion_touch_mm': ('vision_tuning', 'OCCLUSION_TOUCH_MM', (0.0, 0.5, 1.0)),
    'removed_fraction': ('vision_tuning', 'REMOVED_FRACTION', (0.4, 0.6, 0.8)),
}


def current(name):
    module, attribute, _ = TUNABLE[name]
    return getattr(importlib.import_module(module), attribute)


@contextlib.contextmanager
def overridden(settings):
    """Temporarily set TUNABLE thresholds: {name: value}. Restores the old values on exit.

    Vision copies TIP_BIAS_MM when it is created, so create Vision objects inside the block.
    """
    saved = []
    try:
        for name, value in settings.items():
            module, attribute, _ = TUNABLE[name]
            owner = importlib.import_module(module)
            saved.append((owner, attribute, getattr(owner, attribute)))
            setattr(owner, attribute, value)
        yield
    finally:
        for owner, attribute, value in reversed(saved):
            setattr(owner, attribute, value)

# Alignment fallback (zoomed-in real board, where ORB features all look alike): a direct image fit of the live
# picture to the calibration image is trusted only above this correlation (1.0 = identical). REAL DATA.
ECC_MIN_CORRELATION = 0.85
# ... and only when the board markers moved at most this far (image px) since calibration. REAL DATA.
ECC_MAX_SHIFT_PX = 25.0

# A picture that never settles for this long (seconds) gets a message saying so instead of silent waiting.
UNSETTLED_SECONDS = 4.0
# The still limit adapts to the camera's noise floor but never goes above this moving share.
MOTION_STILL_MAX = 0.03
# A still picture that differs from the turn reference everywhere for this long (s) gets a new reference. REAL DATA.
LARGE_CHANGE_REBASE_SECONDS = 3.0
