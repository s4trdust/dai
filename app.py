import os, re, sqlite3, time
import cv2
from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
import qrcode
from database import init_db, DB, DAY
from station import config as station_config
from station.classify import ClassificationError, classify, material_label
from station.measure import MeasurementError, decode_jpeg, measure, rectify

try:
    from google import genai
    # set GEMINI_API_KEY in your shell, don't hard-code it. A busy model is given up on
    # after 30 s so the backup model gets a turn before the ESP32 times out.
    client = (genai.Client(http_options=genai.types.HttpOptions(timeout=30_000))
              if os.environ.get('GEMINI_API_KEY') else None)
except ImportError:
    client = None
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash')
GEMINI_BACKUP_MODEL = os.environ.get('GEMINI_BACKUP_MODEL', 'gemini-3.5-flash-lite')  # used when the main one is busy
GEMINI_MODELS = [GEMINI_MODEL, GEMINI_BACKUP_MODEL]

CATEGORIES = {'small': 'Small', 'large': 'Large', 'unique': 'Unique'}
# default storage time before an item is flagged "to be recycled" (depends on material)
EXPIRY_DAYS = {'cardboard': 30, 'paper': 30, 'wood': 60, 'mdf': 60, 'acrylic': 90,
               'pla': 90, 'plastic': 90, 'metal': 120, 'wire': 120, 'electronics': 180}
SOON = 7 * DAY

app = Flask(__name__)
init_db()
station_config.SCAN_DIR.mkdir(exist_ok=True)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def decorate(row):
    """Row -> dict with a status the templates can show."""
    d = dict(row)
    left = d['expiry'] - time.time()
    d['status'] = 'recycle' if left <= 0 else 'soon' if left <= SOON else 'ok'
    d['days_left'] = int(left // DAY)
    d['category_label'] = CATEGORIES.get(d['category'], d['category'])
    d['labelled'] = d['category'] != 'small'   # small scraps are only counted; large/unique get a QR
    return d


def query_items(q='', category='all', expiring=False):
    sql, args = 'SELECT * FROM items WHERE 1=1', []
    if category in CATEGORIES:
        sql += ' AND category = ?'; args.append(category)
    if q:
        sql += ' AND (name LIKE ? OR material LIKE ? OR use LIKE ? OR location LIKE ? OR size LIKE ?)'
        args += [f'%{q}%'] * 5
    if expiring:
        sql += ' AND expiry <= ?'; args.append(int(time.time() + SOON))
    sql += ' ORDER BY expiry ASC'
    with db() as con:
        return [decorate(r) for r in con.execute(sql, args)]


def qr_path(item_id):
    return os.path.join(app.static_folder, 'qr', f'{item_id}.png')


def make_qr(item_id):
    """QR content = the item id (unix timestamp), as in the proposal."""
    qrcode.make(str(item_id)).save(qr_path(item_id))


def new_item_id(con):
    """Unix-timestamp id, bumped until unused (ids must stay unique)."""
    item_id = int(time.time())
    while con.execute('SELECT 1 FROM items WHERE id = ?', (item_id,)).fetchone():
        item_id += 1
    return item_id


def remove_item(item_id):
    with db() as con:
        return con.execute('DELETE FROM items WHERE id = ?', (item_id,)).rowcount


def take_item(item_id, n=1):
    """Checkout: lower the quantity by n; the item is removed when none are left.
    Returns (name, number taken, number left) or None if there is no such item."""
    with db() as con:
        row = con.execute('SELECT name, quantity FROM items WHERE id = ?', (item_id,)).fetchone()
        if not row:
            return None
        n = max(1, min(n, row['quantity']))
        left = row['quantity'] - n
        if left:
            con.execute('UPDATE items SET quantity = ? WHERE id = ?', (left, item_id))
        else:
            con.execute('DELETE FROM items WHERE id = ?', (item_id,))
    return row['name'], n, left


def add_to_count(location, name, material, use, size, n=1):
    """Small scraps are only counted: +n on the item for that location and material
    (created on first use, no QR label). Returns (item id, new quantity)."""
    expiry = int(time.time() + EXPIRY_DAYS.get(material.lower(), 60) * DAY)
    with db() as con:
        row = con.execute("SELECT id, quantity FROM items WHERE category = 'small' AND location = ? "
                          'AND material = ? COLLATE NOCASE', (location, material)).fetchone()
        if row:                               # newest piece resets the recycle countdown
            con.execute('UPDATE items SET quantity = quantity + ?, expiry = ? WHERE id = ?',
                        (n, expiry, row['id']))
            return row['id'], row['quantity'] + n
        item_id = new_item_id(con)
        con.execute('INSERT INTO items (id,category,size,material,expiry,location,use,name,quantity) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (item_id, 'small', size, material, expiry, location, use, name, n))
    return item_id, n


def section_for(material):
    """Storage section (1-4) for a material name like 'Acrylic' or 'Wires', or None."""
    m = material.strip().lower()
    return (station_config.SECTION_BY_MATERIAL.get(m)
            or station_config.SECTION_BY_MATERIAL.get(m.rstrip('s')))


def deposit_small(material, n=1, location='', use=''):
    """Count small scraps into their section, or into a per-material count elsewhere.
    Returns (item id, item name, new quantity, location)."""
    section = section_for(material)
    if section:
        s = station_config.SECTIONS[section]
        location = f'Section {section}'
        item_id, qty = add_to_count(location, s['name'], s['material'], s['use'],
                                    f'Under {station_config.MAX_LENGTH_CM:g} cm', n)
        return item_id, s['name'], qty, location
    name = f'{material} scraps'
    location = location or station_config.MANUAL_AREA_NAME
    item_id, qty = add_to_count(location, name, material, use or 'Small parts, prototyping', 'Small', n)
    return item_id, name, qty, location


# ---------- pages ----------
@app.route('/')
def dashboard():
    items = query_items()
    stats = {'total': len(items), **{k: sum(i['category'] == k for i in items) for k in CATEGORIES}}
    return render_template('dashboard.html', stats=stats,
                           recycle=[i for i in items if i['status'] == 'recycle'],
                           soon=[i for i in items if i['status'] == 'soon'])


@app.route('/items')
def items():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', 'all')
    expiring = request.args.get('expiring') == '1'
    return render_template('items.html', items=query_items(q, category, expiring),
                           q=q, category=category, expiring=expiring, categories=CATEGORIES)


@app.route('/item/<int:item_id>')
def item(item_id):
    with db() as con:
        row = con.execute('SELECT * FROM items WHERE id = ?', (item_id,)).fetchone()
    if not row:
        abort(404)
    item = decorate(row)
    if item['labelled'] and not os.path.exists(qr_path(item_id)):
        make_qr(item_id)                      # e.g. sample items added by database.py --seed
    return render_template('item.html', item=item)


@app.route('/new', methods=['GET', 'POST'])
def new():
    """Register a material. Large/unique items get their own entry and QR label;
    small scraps are only added to the count for their category."""
    if request.method == 'POST':
        f = request.form
        material = f.get('material', '').strip()
        quantity = max(1, int(f.get('quantity') or 1))
        if f.get('category') == 'small':
            item_id, name, total, location = deposit_small(material, quantity, f.get('location', '').strip(),
                                                           f.get('use', '').strip())
            return render_template('new.html', categories=CATEGORIES, defaults=EXPIRY_DAYS,
                                   deposited=dict(id=item_id, name=name, added=quantity, total=total,
                                                  location=location))
        days = int(f.get('days') or EXPIRY_DAYS.get(material.lower(), 60))
        with db() as con:
            item_id = new_item_id(con)
            con.execute('INSERT INTO items (id,category,size,material,expiry,location,use,name,quantity) '
                        'VALUES (?,?,?,?,?,?,?,?,?)',
                        (item_id, f.get('category', 'small'), f.get('size', '').strip() or 'Standard', material,
                         int(time.time() + days * DAY), f.get('location', '').strip(), f.get('use', '').strip(),
                         f.get('name', '').strip() or material, quantity))
        make_qr(item_id)
        return redirect(url_for('item', item_id=item_id))
    return render_template('new.html', categories=CATEGORIES, defaults=EXPIRY_DAYS)


@app.route('/guide')
def guide():
    return render_template('guide.html')


@app.route('/scan')
def scan():
    """Checkout page: scan a QR for large/unique items, or pick small scraps from the list."""
    small = sorted(query_items(category='small'), key=lambda i: i['location'])
    return render_template('scancode.html', small=small, taken=request.args.get('taken'))


@app.route('/take/<int:item_id>', methods=['POST'])
def take(item_id):
    """Checkout form for small scraps (and the 'Take' button on any item page)."""
    try:
        n = int(request.form.get('quantity') or 1)
    except ValueError:
        n = 1
    result = take_item(item_id, n)
    msg = f'Checked out {result[1]} × {result[0]} ({result[2]} left).' if result else 'Item not found.'
    return redirect(url_for('scan', taken=msg))


# ---------- QR / inventory API ----------
@app.route('/api/item/<code>')
def api_item(code):
    if not code.strip().isdigit():
        return jsonify(ok=False, error='Not a Re:Source code.'), 404
    with db() as con:
        row = con.execute('SELECT * FROM items WHERE id = ?', (int(code),)).fetchone()
    if not row:
        return jsonify(ok=False, error='No item with that code (already taken?).'), 404
    d = decorate(row)
    if not d['labelled']:
        return jsonify(ok=False, error='Small scraps have no label; pick them from the list below.'), 404
    return jsonify(ok=True, item={k: d[k] for k in ('id', 'name', 'category_label', 'material', 'size',
                                                    'quantity', 'location', 'use', 'status')})


@app.route('/checkout', methods=['POST'])
def checkout():
    """Called from scanning.js after the QR is decoded: takes `quantity` (default 1) of the item."""
    data = request.get_json(silent=True) or {}
    try:
        result = take_item(int(data.get('id')), int(data.get('quantity') or 1))
    except (TypeError, ValueError, sqlite3.DatabaseError):
        return jsonify(ok=False, error='Invalid code.'), 400
    if not result:
        return jsonify(ok=False, error='Item not found.')
    return jsonify(ok=True, error=None, taken=result[1], left=result[2])


@app.route('/recycle/<int:item_id>', methods=['POST'])
def recycle(item_id):
    """Staff confirm an expired item has been physically recycled."""
    remove_item(item_id)
    return redirect(url_for('dashboard'))


# ---------- scanning station (ESP32 camera + scale) ----------
@app.route('/station/background', methods=['POST'])
def station_background():
    """ESP32 sends a photo of the EMPTY board on boot / when lighting changes."""
    jpeg = request.get_data()
    try:
        rectify(decode_jpeg(jpeg))            # check the corner markers are visible
    except MeasurementError as e:
        return jsonify(ok=False, error=str(e)), 400
    station_config.BACKGROUND_PATH.write_bytes(jpeg)
    return jsonify(ok=True)


@app.route('/station/scan', methods=['POST'])
def station_scan():
    """ESP32 sends a photo (body) + weight; replies with the section the flap should turn to."""
    jpeg, weight_g = request.get_data(), request.args.get('weight_g', type=float)
    if not jpeg or weight_g is None:
        return jsonify(ok=False, error='send the JPEG as the body and ?weight_g=...'), 400
    return jsonify(process_piece(jpeg, weight_g))


def process_piece(jpeg, weight_g):
    """Small pieces are counted (into their section, or into the manual area if they have no
    section or the AI is unsure). Large pieces get their own library item and QR label."""
    reasons, size, annotated, ai = [], {}, None, {}
    oversize = unsure = False

    try:
        if not station_config.BACKGROUND_PATH.exists():
            raise MeasurementError('no empty-board photo yet')
        m = measure(decode_jpeg(jpeg), decode_jpeg(station_config.BACKGROUND_PATH.read_bytes()))
        size = {'length_cm': m.length_cm, 'width_cm': m.width_cm, 'area_cm2': m.area_cm2}
        annotated = cv2.imencode('.jpg', m.annotated)[1].tobytes()
        if (m.touches_edge or m.length_cm > station_config.MAX_LENGTH_CM
                or m.width_cm > station_config.MAX_WIDTH_CM):
            oversize = True
            reasons.append('too large for the sections')
    except MeasurementError as e:
        oversize = True                       # unknown size: treat as large, it might not fit
        reasons.append(f'size not measured: {e}')

    try:
        ai = classify(client, GEMINI_MODELS, jpeg, annotated, weight_g, size.get('length_cm'),
                      size.get('width_cm'), size.get('area_cm2'))
        if ai['material'] == 'unknown':
            unsure = True
            reasons.append('material unknown')
        elif ai['material_confidence'] < station_config.MIN_CONFIDENCE:
            unsure = True
            reasons.append(f"unsure of material ({ai['material_confidence']:.0%})")
    except ClassificationError as e:
        unsure = True
        reasons.append(f'not identified: {e}')

    material = 'Unsorted' if unsure else material_label(ai['material'])
    section = None if reasons else section_for(material)
    if section:
        item_id, name, quantity, _ = deposit_small(material)
        return dict(ok=True, section=section, item_id=item_id, quantity=quantity, name=name)

    if not reasons:
        reasons.append(f"no section for {ai['material']}")
    if oversize:
        item_id = add_manual_item(jpeg, weight_g, size, ai, reasons)
        name, quantity = ai.get('name', 'Unidentified piece'), 1
    else:                                     # small, but no section / AI unsure: staff sort it
        name = f'{material} scraps'
        item_id, quantity = add_to_count(station_config.MANUAL_AREA_NAME, name, material,
                                         ai.get('suggested_use') or 'Ask staff', 'Small')
    return dict(ok=True, section=station_config.MANUAL_AREA, item_id=item_id, quantity=quantity,
                name=name, reasons=reasons)


def add_manual_item(jpeg, weight_g, size, ai, reasons):
    """Large pieces become their own library item with full details and a QR label."""
    material = material_label(ai['material']) if ai else 'Unknown'
    dims = f"{size['length_cm']:g} x {size['width_cm']:g} cm" if size else 'Not measured'
    description = ' '.join(filter(None, [ai.get('description'), f"Manual check: {'; '.join(reasons)}."]))
    with db() as con:
        item_id = new_item_id(con)
        photo = f'scans/{item_id}.jpg'
        (station_config.SCAN_DIR / f'{item_id}.jpg').write_bytes(jpeg)
        con.execute('INSERT INTO items (id,category,size,material,expiry,location,use,name,quantity,'
                    'weight_g,colour,condition,transparency,description,photo) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (item_id, 'large', dims, material,
                     int(time.time() + EXPIRY_DAYS.get(material.lower(), 60) * DAY),
                     station_config.MANUAL_AREA_NAME,
                     ai.get('suggested_use') or 'Ask staff', ai.get('name') or 'Unidentified piece', 1,
                     round(weight_g, 1), ai.get('colour'), ai.get('condition'), ai.get('transparency'),
                     description, photo))
    make_qr(item_id)
    return item_id


# ---------- AI matcher ----------
PROMPT = ('You are Re:Source, a school scrapyard assistant. According to the project specifications below, '
          'recommend items from the inventory to use in the project. For each recommendation give the item '
          'ID, name, location and why it fits. Only recommend items in the inventory; if nothing fits, say so. '
          'Keep it short.\n\nINVENTORY (id | name | type | material | size | qty | location | suggested use):\n{inv}'
          '\n\nPROJECT SPECIFICATIONS:\n{text}')


def keyword_match(text, items):
    words = set(re.findall(r'[a-z]{3,}', text.lower()))
    scored = []
    for i in items:
        hay = set(re.findall(r'[a-z]{3,}', ' '.join(str(i[k]) for k in ('name', 'material', 'use', 'category_label')).lower()))
        if words & hay:
            scored.append((len(words & hay), i))
    scored.sort(key=lambda s: -s[0])
    if not scored:
        return 'No matching materials found in the scrapyard right now.'
    return '\n'.join(f"#{i['id']} {i['name']} ({i['material']}, {i['quantity']} units) at {i['location']}: {i['use']}"
                     for _, i in scored[:5])


def match(text):
    items = [i for i in query_items() if i['status'] != 'recycle']
    if client:
        inv = '\n'.join(f"{i['id']} | {i['name']} | {i['category']} | {i['material']} | {i['size']} | "
                        f"{i['quantity']} | {i['location']} | {i['use']}" for i in items) or '(empty)'
        for model in GEMINI_MODELS:           # backup model when the main one is busy
            try:
                return client.models.generate_content(model=model,
                                                      contents=PROMPT.format(inv=inv, text=text)).text, True
            except Exception as ex:
                print(f'Gemini error ({model}):', ex)
    return keyword_match(text, items), False


@app.route('/ai-matcher', methods=['GET', 'POST'])
def ai_matcher():
    text, reply, ai = '', None, True
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        if text:
            reply, ai = match(text)
    return render_template('ai.html', text=text, reply=reply, ai=ai)


if __name__ == '__main__':
    # 0.0.0.0 so the ESP32 can reach it over WiFi. Debug mode stays off on the network
    # because its error page lets anyone on the network run code; set FLASK_DEBUG=1 to enable.
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')
