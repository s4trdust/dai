"""Run from the project folder:  python -m station.make_markers

Make a printable A4 sheet (300 DPI PNG) with the 4 corner markers.

Print at 100% / "actual size" (NOT "fit to page"), cut the markers out and tape
them at the corners of the grid: 0 top-left, 1 top-right, 2 bottom-right,
3 bottom-left. Then measure the centre-to-centre distances and put them in config.py.
"""
import cv2
import numpy as np

from station import config

DPI = 300
PX_PER_CM = DPI / 2.54
page = np.full((int(29.7 * PX_PER_CM), int(21.0 * PX_PER_CM)), 255, np.uint8)
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
side = int(config.MARKER_SIZE_CM * PX_PER_CM)
gap = int(2 * PX_PER_CM)

for i in range(4):
    marker = cv2.aruco.generateImageMarker(dictionary, i, side)
    x = gap + (i % 2) * (side + gap)
    y = gap + (i // 2) * (side + gap + int(1 * PX_PER_CM))
    page[y:y + side, x:x + side] = marker
    cv2.putText(page, f"ID {i}", (x, y + side + int(0.6 * PX_PER_CM)),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, 0, 3)

cv2.imwrite("markers_A4.png", page)
print(f"Wrote markers_A4.png ({config.MARKER_SIZE_CM} cm markers). Print at 100% scale.")
