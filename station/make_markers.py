"""Run from the project folder:  python -m station.make_markers

Makes markers_board_A4.pdf: a ready-to-print A4 measuring board with the 4 corner
markers, a 1 cm grid and cm labels. Print at 100% / "Actual size" (NOT "fit to
page") and check the 10 cm ruler with a real ruler. The marker spacing it uses
is printed below and must match MARKER_SPAN_X_CM / MARKER_SPAN_Y_CM in config.py.
"""
import cv2
import numpy as np
from PIL import Image

from station import config

DPI = 300
PX = DPI / 2.54                       # pixels per cm
PAGE_W, PAGE_H = 21.0, 29.7           # A4 in cm
INSET = 2.5                           # marker centre distance from the paper edge (cm);
                                      # keeps markers clear of the printer's unprintable margin
SPAN_X, SPAN_Y = PAGE_W - 2 * INSET, PAGE_H - 2 * INSET
BACKGROUND = (247, 235, 220)          # light blue (BGR): makes silver/white/clear pieces stand out
GRID, GRID_5 = (215, 195, 170), (180, 155, 125)


def px(cm):
    return int(round(cm * PX))


page = np.full((px(PAGE_H), px(PAGE_W), 3), 255, np.uint8)

# coloured measuring area between the marker centres
x0, y0, x1, y1 = px(INSET), px(INSET), px(INSET + SPAN_X), px(INSET + SPAN_Y)
page[y0:y1, x0:x1] = BACKGROUND

# 1 cm grid, a little bolder every 5 cm, measured from marker 0's centre
for i in range(int(SPAN_X) + 1):
    x = px(INSET + i)
    cv2.line(page, (x, y0), (x, y1), GRID_5 if i % 5 == 0 else GRID, 3 if i % 5 == 0 else 1)
    if i % 5 == 0 and 0 < i < SPAN_X - 2:
        cv2.putText(page, str(i), (x - 15, y0 - px(0.3)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (90, 90, 90), 2)
for j in range(int(SPAN_Y) + 1):
    y = px(INSET + j)
    cv2.line(page, (x0, y), (x1, y), GRID_5 if j % 5 == 0 else GRID, 3 if j % 5 == 0 else 1)
    if j % 5 == 0 and 0 < j < SPAN_Y - 2:
        cv2.putText(page, str(j), (px(INSET - 1.2), y + 15), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (90, 90, 90), 2)

# corner markers on white squares (the white border is needed for detection)
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
side = px(config.MARKER_SIZE_CM)
quiet = px(0.5)
for marker_id, (cx, cy) in enumerate([(INSET, INSET), (INSET + SPAN_X, INSET),
                                      (INSET + SPAN_X, INSET + SPAN_Y), (INSET, INSET + SPAN_Y)]):
    mx, my = px(cx) - side // 2, px(cy) - side // 2
    page[my - quiet:my + side + quiet, mx - quiet:mx + side + quiet] = 255
    page[my:my + side, mx:mx + side] = cv2.cvtColor(
        cv2.aruco.generateImageMarker(dictionary, marker_id, side), cv2.COLOR_GRAY2BGR)

# 10 cm ruler and instructions in the bottom margin
ry = px(PAGE_H - 0.9)
rx = px(PAGE_W / 2 - 5)
cv2.line(page, (rx, ry), (rx + px(10), ry), (0, 0, 0), 3)
for k in range(11):
    cv2.line(page, (rx + px(k), ry), (rx + px(k), ry - (30 if k % 5 == 0 else 15)), (0, 0, 0), 3)
cv2.putText(page, "10 cm - check with a ruler", (rx + px(1.8), ry - px(0.35)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 60, 60), 2)
cv2.putText(page, "Re:Source measuring board - print at 100% / Actual size",
            (px(INSET + 2), px(0.9)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (60, 60, 60), 2)

Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB)).save("markers_board_A4.pdf", resolution=DPI)
print(f"Wrote markers_board_A4.pdf. Marker spacing: X = {SPAN_X:g} cm, Y = {SPAN_Y:g} cm")
if (config.MARKER_SPAN_X_CM, config.MARKER_SPAN_Y_CM) != (SPAN_X, SPAN_Y):
    print(f"Set MARKER_SPAN_X_CM = {SPAN_X:g} and MARKER_SPAN_Y_CM = {SPAN_Y:g} in station/config.py")
