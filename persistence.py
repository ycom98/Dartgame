"""Save the match and the camera calibration to disk so a restart resumes (M1-16).

match.json        {schema, mode, options, state, history, revision, camera_game, auto_commit, saved_at}
                  written after every change of the match (atomically: temp file, fsync, rename)
calibration.json  the four-point calibration (reference homography and points, image size, mount side)
reference.png     the frozen calibration image, for the alignment check after a restart

A corrupt match.json is renamed to match.corrupt-<time>.json and the server starts with no match.
Pairing tokens are never saved. Calibration needs OpenCV; the match does not.
"""
import json
import os
import time
from pathlib import Path

SCHEMA = 1


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:  # make the rename itself durable (QA M1-16 L1); not available on every platform
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


class MatchStore:
    def __init__(self, path):
        self.path = Path(path)
        self.last_write_seconds = None
        self.error = None

    def save(self, app):
        """Write the current match (call with app.game_lock held)."""
        started = time.perf_counter()
        game = app.game.to_json() if app.game is not None else None
        payload = {'schema': SCHEMA, 'game': game, 'revision': app.revision, 'camera_game': app.camera_game,
                   'auto_commit': {'paused': app.flow.paused, 'seconds': app.flow.delay}, 'saved_at': time.time()}
        atomic_write(self.path, json.dumps(payload, allow_nan=False))
        self.last_write_seconds = time.perf_counter() - started

    def load(self, app):
        """Restore the saved match into app. Returns a message for the terminal, or None if there was nothing."""
        from core import Game
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                raise ValueError('not a JSON object')
            if payload.get('schema') != SCHEMA:
                raise ValueError(f"unknown schema {payload.get('schema')!r}")
            game = Game.from_json(payload['game']) if payload['game'] is not None else None
            revision, camera_game = payload['revision'], payload['camera_game']
            if type(revision) is not int or revision < 0 or type(camera_game) is not bool:
                raise ValueError('bad revision or camera_game')
            auto = payload.get('auto_commit', {})
            if auto is None:
                auto = {}
            if not isinstance(auto, dict):
                raise ValueError('bad auto_commit')
        except Exception as error:  # any damage at all: keep the file, start empty (QA M1-16 D1)
            corrupt = self.path.with_name(f'match.corrupt-{time.strftime("%Y%m%d-%H%M%S")}.json')
            try:
                os.replace(self.path, corrupt)
                kept = f'It was kept as {corrupt}'
            except OSError as move_error:
                kept = f'It could not be moved aside ({move_error}) and will be overwritten'
            return f'WARNING: the saved match could not be read ({error}). {kept}; starting with no match.'
        app.game, app.revision, app.camera_game = game, revision, camera_game
        app.flow.paused = bool(auto.get('paused', False))
        if game is None:
            return 'Saved state restored (no match in progress).'
        g = game.data
        return (f"Resumed the saved match: {', '.join(g['names'])}, turn {g['turn']}, "
                f"{g['names'][g['player']]} to throw (revision {revision}).")


def save_calibration(vision, directory):
    """Keep the four-point calibration and its reference image (call with vision.lock held)."""
    import cv2
    import numpy as np
    from vision import TARGETS
    if vision.reference is None or vision.reference_H is None:
        return False
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    points = cv2.perspectiveTransform(TARGETS.reshape(1, -1, 2), np.linalg.inv(vision.reference_H))[0]
    current = vision.overlay() if vision.aligned else None  # where the markers were when last aligned
    overlay = current.tolist() if current is not None else points.tolist()
    ok, png = cv2.imencode('.png', vision.reference)
    if not ok:
        return False
    temporary = directory / 'reference.png.tmp'
    temporary.write_bytes(png.tobytes())
    os.replace(temporary, directory / 'reference.png')
    data = {'schema': SCHEMA, 'points': points.tolist(), 'reference_H': vision.reference_H.tolist(),
            'width': int(vision.reference.shape[1]), 'height': int(vision.reference.shape[0]),
            'mount_side': vision.mount_side, 'camera_hfov': vision.camera_hfov,
            'pose': vision.pose, 'overlay': overlay, 'saved_at': time.time()}
    atomic_write(directory / 'calibration.json', json.dumps(data, default=float))
    return True


def load_calibration(vision, directory):
    """Load the saved calibration as the alignment reference (vision.lock held). The board is not trusted
    until align() matches the reference to a live frame and the host verifies the overlay."""
    import cv2
    import numpy as np
    directory = Path(directory)
    if not (directory / 'calibration.json').exists():
        return None
    data = json.loads((directory / 'calibration.json').read_text(encoding='utf-8'))
    reference = cv2.imread(str(directory / 'reference.png'), cv2.IMREAD_COLOR)
    if reference is None or data.get('schema') != SCHEMA:
        raise ValueError('saved calibration is incomplete')
    if reference.shape[:2] != (data['height'], data['width']):
        raise ValueError('saved calibration image has the wrong size')
    vision.reference = reference
    vision.reference_H = np.asarray(data['reference_H'], np.float64)
    vision.H = vision.reference_H.copy()
    vision.reference_mask = np.zeros(reference.shape[:2], np.uint8)
    cv2.fillConvexPoly(vision.reference_mask, np.asarray(data['points'], np.float32).astype(np.int32), 255)
    vision.ref_kp, vision.ref_desc = vision.orb.detectAndCompute(vision.reference, vision.reference_mask)
    vision.mount_side = data.get('mount_side')
    vision.aligned = False
    vision.message = 'Saved calibration loaded. Waiting for the camera to check the board position.'
    return data
