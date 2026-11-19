"""Settings for the scanning station (ESP32 camera + scale + sorting flap)."""
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKGROUND_PATH = Path(__file__).parent / "background.jpg"   # photo of the empty board
SCAN_DIR = ROOT / "static" / "scans"                        # photos of manual-area items

# --- Measuring board (ArUco markers) ----------------------------------------
# Four markers from DICT_4X4_50 at the corners of the board:
#   ID 0 = top-left, ID 1 = top-right, ID 2 = bottom-right, ID 3 = bottom-left
# These values match the printable A4 board from `python -m station.make_markers`.
# If you place markers yourself, measure CENTRE-to-CENTRE distances instead.
# These numbers set the scale for every measurement.
MARKER_SPAN_X_CM = 16.0   # centre of marker 0 -> centre of marker 1
MARKER_SPAN_Y_CM = 24.7   # centre of marker 0 -> centre of marker 3
MARKER_SIZE_CM = 3.0      # printed side length of one marker (black border included)
PX_PER_CM = 20            # resolution of the rectified top-down image

# --- Segmentation -----------------------------------------------------------
DIFF_THRESHOLD = 28.0     # colour difference vs. empty-board photo that counts as "object"
MIN_PIECE_AREA_CM2 = 1.0  # ignore blobs smaller than this (dust, noise)

# --- AI classification ------------------------------------------------------
MIN_CONFIDENCE = 0.6      # below this, the piece goes to the manual area

# --- Sorting ----------------------------------------------------------------
# Small pieces are only counted. Sections 1-4 are each one library item whose
# quantity goes up by 1 per piece. Small pieces with no section, or that the AI
# is unsure about, are counted in the manual area (section 0) for staff to sort.
# Large pieces also go to the manual area and get their own item and QR label.
SECTIONS = {
    1: {"name": "Acrylic offcuts", "material": "Acrylic", "use": "Signs, window panels, models"},
    2: {"name": "Cardboard", "material": "Cardboard", "use": "Prototyping, bridges, packaging"},
    3: {"name": "Wires", "material": "Wire", "use": "Circuits, wiring, binding"},
    4: {"name": "PLA", "material": "PLA", "use": "Small parts, models, re-printing"},
}
SECTION_BY_MATERIAL = {"acrylic": 1, "cardboard": 2, "wire": 3, "pla": 4}
MANUAL_AREA = 0
MANUAL_AREA_NAME = "Manual area"   # storage location shown in the library
MAX_LENGTH_CM = 8.0       # set these to what actually fits in a section
MAX_WIDTH_CM = 5.0
