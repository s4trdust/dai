"""Showcase item: the DC Motor Speed Controller.

    python showcase/showcase_item.py          put it (back) in the library database
    python showcase/showcase_item.py --pdf    also remake the printable QR label PDF

Or just double-click showcase/load_showcase_item.bat.
The item always gets the same code, so the printed QR label keeps working after a reload.
"""
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from database import DAY, init_db  # noqa: E402  (creates/updates the table if needed)

ITEM = {
    'id': 1795101273,                         # = the QR code content; keep it fixed
    'category': 'unique',
    'name': 'DC Motor Speed Controller',
    'material': 'Electronics',
    'size': 'about 5 x 4.5 cm',
    'quantity': 1,
    'location': '',
    'use': 'robotics, motor speed control, adjustable power supply projects',
    'weight_g': 30.7,
    'colour': 'red',
    'condition': 'intact',
    'transparency': 'opaque',
    'description': 'A small red printed circuit board module with screw terminals, a heatsink, '
                   'and electronic components.',
    'photo': 'scans/1795101273.jpg',
}
SHELF_LIFE_DAYS = 365                         # electronics
PHOTO = HERE / 'dc_motor_controller.jpg'
PDF = HERE / 'dc_motor_controller_qr.pdf'


def load():
    db = ROOT / 'database.db'
    os.chdir(ROOT)                            # database.py uses a relative path
    init_db()
    row = dict(ITEM, expiry=int(time.time() + SHELF_LIFE_DAYS * DAY))
    cols = ', '.join(row)
    with sqlite3.connect(db) as con:          # same id -> replaces an older copy instead of duplicating
        con.execute(f'INSERT OR REPLACE INTO items ({cols}) VALUES ({", ".join("?" * len(row))})',
                    list(row.values()))
    scans = ROOT / 'static' / 'scans'
    scans.mkdir(parents=True, exist_ok=True)
    if PHOTO.exists():
        shutil.copyfile(PHOTO, scans / f"{ITEM['id']}.jpg")
    qr_dir = ROOT / 'static' / 'qr'
    qr_dir.mkdir(parents=True, exist_ok=True)
    qrcode.make(str(ITEM['id'])).save(qr_dir / f"{ITEM['id']}.png")
    print(f"Loaded '{ITEM['name']}' (item code {ITEM['id']}) into the library.")


def font(size, bold=False):
    for name in (['arialbd.ttf', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf'] if bold
                 else ['arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf']):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def make_pdf():
    """A4 page at 300 dpi: one large label (QR 8 cm) and four small cut-out labels (QR 4 cm)."""
    dpi, cm = 300, 300 / 2.54
    page = Image.new('RGB', (2480, 3508), 'white')
    d = ImageDraw.Draw(page)

    def label(x, y, qr_cm, scale):
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
        qr.add_data(str(ITEM['id'])); qr.make(fit=True)
        side = int(qr_cm * cm)
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB').resize((side, side), Image.NEAREST)
        pad = int(0.4 * cm * scale)
        w, h = side + 2 * pad, side + int(3.2 * cm * scale)
        d.rounded_rectangle([x, y, x + w, y + h], radius=int(0.4 * cm), outline=(150, 150, 150), width=3)
        page.paste(img, (x + pad, y + pad))
        cx, ty = x + w // 2, y + pad + side + int(0.25 * cm * scale)
        d.text((cx, ty), 'Re:Source', font=font(int(44 * scale), True), fill='black', anchor='mt')
        d.text((cx, ty + int(0.8 * cm * scale)), ITEM['name'], font=font(int(40 * scale)), fill='black', anchor='mt')
        d.text((cx, ty + int(1.6 * cm * scale)), f"Item code: {ITEM['id']}", font=font(int(46 * scale), True),
               fill='black', anchor='mt')
        return w, h

    d.text((1240, int(1.2 * cm)), 'Showcase label - print at 100% (actual size)', font=font(40), fill=(110, 110, 110), anchor='mt')
    big_w = int(8 * cm) + 2 * int(0.4 * cm)   # label width = QR + padding, to centre it
    label((2480 - big_w) // 2, int(2.2 * cm), 8, 1.0)
    d.text((1240, int(15.6 * cm)), 'Cut-out labels', font=font(40), fill=(110, 110, 110), anchor='mt')
    small_w = int(4 * cm) + 2 * int(0.4 * cm * 0.6)
    gap = int(1.5 * cm)
    x0 = (2480 - (2 * small_w + gap)) // 2
    for row in range(2):
        for colm in range(2):
            label(x0 + colm * (small_w + gap), int(16.6 * cm) + row * int(7 * cm), 4, 0.6)
    page.save(PDF, 'PDF', resolution=dpi)
    print(f'QR label PDF saved: {PDF}')


if __name__ == '__main__':
    load()
    if '--pdf' in sys.argv or not PDF.exists():
        make_pdf()
