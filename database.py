"""Creates/updates database.db.  Run:  python database.py [--seed]"""
import sqlite3, sys, time

DB = 'database.db'
DAY = 86400

def init_db():
    con = sqlite3.connect(DB)
    # PDF schema: Item(id, category, size, material, expiry, location, use)
    # id = unix timestamp (same value is encoded in the QR code); expiry is unix time.
    con.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER NOT NULL PRIMARY KEY,
        category TEXT NOT NULL,      -- small | large | unique
        size TEXT NOT NULL,
        material TEXT NOT NULL,
        expiry INTEGER NOT NULL,
        location TEXT NOT NULL,
        use TEXT NOT NULL
    )''')
    # extra columns the Library UI and scanning station need (added safely to an existing db).
    # The station columns are only filled for pieces sent to the manual area.
    extra = {'name': "TEXT NOT NULL DEFAULT ''", 'quantity': 'INTEGER NOT NULL DEFAULT 1',
             'weight_g': 'REAL', 'colour': 'TEXT', 'condition': 'TEXT', 'transparency': 'TEXT',
             'description': 'TEXT', 'photo': 'TEXT'}
    cols = {r[1] for r in con.execute('PRAGMA table_info(items)')}
    for col, kind in extra.items():
        if col not in cols:
            con.execute(f'ALTER TABLE items ADD COLUMN {col} {kind}')
    # small scraps are only counted, so they have no size (older versions stored e.g. "Under 8 cm")
    con.execute("UPDATE items SET size = '' WHERE category = 'small' AND size != ''")
    con.commit(); con.close()

def seed():
    now = int(time.time())
    rows = [
        ('Arduino Uno', 'unique', 'Standard', 'Electronics', 180, 'Shelf C01', 'Electronics, robotics', 2),
        ('Servo Motor', 'unique', 'Standard', 'Electronics', 180, 'Shelf C02', 'Robotics, mechanisms', 3),
        ('Acrylic offcuts', 'small', '', 'Acrylic', 90, 'Section 1', 'Signs, window panels, models', 12),
        ('Cardboard', 'small', '', 'Cardboard', 30, 'Section 2', 'Prototyping, bridges, packaging', 20),
        ('Heavy plywood sheet', 'large', '100 x 80 cm', 'Wood', 60, 'Rack B1', 'Bases, frames', 1),
        ('Large cardboard panel', 'large', '120 x 90 cm', 'Cardboard', 30, 'Rack B2', 'Large models, backdrops', 2),
    ]
    con = sqlite3.connect(DB)
    for i, (n, c, s, m, d, loc, use, q) in enumerate(rows):
        con.execute('INSERT OR IGNORE INTO items (id,category,size,material,expiry,location,use,name,quantity) '
                    'VALUES (?,?,?,?,?,?,?,?,?)', (now - i, c, s, m, now + d * DAY, loc, use, n, q))
    con.commit(); con.close()

if __name__ == '__main__':
    init_db()
    if '--seed' in sys.argv:
        seed()
    print('database ready')
