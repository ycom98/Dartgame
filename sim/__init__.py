"""Synthetic dartboard scenes with known ground truth.

Everything here is a simulation used to measure the vision pipeline before
hardware exists. Results produced with it are NOT evidence of real-board
accuracy; the physical trial is the real gate.

Coordinates follow core.py: millimetres, origin at the bull, +x right,
+y down (20 at the top), +z out of the board toward the thrower.
"""
from sim.board import board_texture
from sim.camera import Camera, MOUNTS, camera_for_mount
from sim.scene import (
    Dart,
    Degradation,
    PROFILES,
    random_dart,
    render_scene,
    CALIBRATION_BOARD_POINTS,
)

__all__ = [
    'board_texture',
    'Camera',
    'MOUNTS',
    'camera_for_mount',
    'Dart',
    'Degradation',
    'PROFILES',
    'random_dart',
    'render_scene',
    'CALIBRATION_BOARD_POINTS',
]
