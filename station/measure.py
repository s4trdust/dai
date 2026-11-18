"""Measure a scrap piece from a top-down photo using ArUco corner markers.

Steps:
  1. Find the 4 corner markers and warp the photo to a flat top-down view
     where 1 cm = config.PX_PER_CM pixels (fixes camera tilt/perspective).
  2. Compare against a photo of the empty board to find the piece.
  3. Fit the smallest rotated rectangle around it -> length and width.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from . import config

_ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_DETECTOR = cv2.aruco.ArucoDetector(_ARUCO_DICT, cv2.aruco.DetectorParameters())


class MeasurementError(Exception):
    pass


@dataclass
class Measurement:
    length_cm: float
    width_cm: float
    area_cm2: float
    touches_edge: bool       # piece runs off the measured area -> dimensions unreliable
    annotated: np.ndarray    # rectified BGR image with the outline drawn on it


def decode_jpeg(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise MeasurementError("could not decode image")
    return img


def rectify(img: np.ndarray) -> np.ndarray:
    """Warp the photo so the area between marker centres becomes a flat, scaled rectangle."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _DETECTOR.detectMarkers(gray)
    found = {}
    if ids is not None:
        for marker_id, c in zip(ids.flatten(), corners):
            found[int(marker_id)] = c.reshape(4, 2).mean(axis=0)
    missing = [i for i in range(4) if i not in found]
    if missing:
        raise MeasurementError(f"corner markers not visible: {missing}")

    w = config.MARKER_SPAN_X_CM * config.PX_PER_CM
    h = config.MARKER_SPAN_Y_CM * config.PX_PER_CM
    src = np.float32([found[0], found[1], found[2], found[3]])
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, matrix, (int(w), int(h)))


def _marker_mask(shape) -> np.ndarray:
    """Mask (255 = usable) that hides the quarter of each marker inside the board."""
    mask = np.full(shape[:2], 255, np.uint8)
    r = int((config.MARKER_SIZE_CM / 2 + 0.5) * config.PX_PER_CM)
    h, w = shape[:2]
    for x, y in [(0, 0), (w, 0), (w, h), (0, h)]:
        cv2.rectangle(mask, (x - r, y - r), (x + r, y + r), 0, -1)
    return mask


def measure(photo: np.ndarray, background: np.ndarray) -> Measurement:
    board = rectify(photo)
    empty = rectify(background)

    # Colour difference in Lab space; brightness (L) is down-weighted so soft
    # shadows count less than real colour changes.
    a = cv2.cvtColor(cv2.GaussianBlur(board, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(cv2.GaussianBlur(empty, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    d = a - b
    d[..., 0] *= 0.5
    diff = np.linalg.norm(d, axis=2)

    mask = (diff > config.DIFF_THRESHOLD).astype(np.uint8) * 255
    mask = cv2.bitwise_and(mask, _marker_mask(mask.shape))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_px = config.MIN_PIECE_AREA_CM2 * config.PX_PER_CM ** 2
    contours = [c for c in contours if cv2.contourArea(c) >= min_px]
    if not contours:
        raise MeasurementError("no piece found on the board (is the background photo current?)")

    # Keep the biggest blob plus any sizeable fragments of it (e.g. a clear
    # plastic piece that segments in several parts).
    contours.sort(key=cv2.contourArea, reverse=True)
    largest = cv2.contourArea(contours[0])
    piece = [c for c in contours if cv2.contourArea(c) >= 0.1 * largest]
    points = np.vstack(piece)

    (cx, cy), (rw, rh), angle = cv2.minAreaRect(points)
    length_cm = max(rw, rh) / config.PX_PER_CM
    width_cm = min(rw, rh) / config.PX_PER_CM
    area_cm2 = sum(cv2.contourArea(c) for c in piece) / config.PX_PER_CM ** 2

    x, y, bw, bh = cv2.boundingRect(points)
    H, W = mask.shape
    touches_edge = x <= 1 or y <= 1 or x + bw >= W - 1 or y + bh >= H - 1

    annotated = board.copy()
    cv2.drawContours(annotated, piece, -1, (0, 255, 0), 2)
    box = cv2.boxPoints(((cx, cy), (rw, rh), angle)).astype(np.int32)
    cv2.polylines(annotated, [box], True, (0, 0, 255), 2)
    cv2.putText(annotated, f"{length_cm:.1f} x {width_cm:.1f} cm", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

    return Measurement(round(length_cm, 2), round(width_cm, 2), round(area_cm2, 2),
                       touches_edge, annotated)
