import json
import os
import sqlite3
from urllib.parse import urlparse
from http.server import SimpleHTTPRequestHandler, HTTPServer

BASE_DIR = os.path.dirname(__file__)
DEFAULT_DB = os.path.join(BASE_DIR, 'db', 'romix.db')
DB_PATH = os.environ.get('DB_PATH', DEFAULT_DB)
SCHEMA_PATH = os.path.join(BASE_DIR, 'db', 'schema.sql')


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    return conn


def init_db():
    with get_conn() as conn, open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())


def upsert_product(conn, name, ptype=None, base_price=0.0):
    cur = conn.execute(
        'INSERT INTO products(name, type, base_price) VALUES(?,?,?)
         ON CONFLICT(name) DO UPDATE SET updated_at = datetime("now")
         RETURNING id', (name, ptype, base_price)
    )
    return cur.fetchone()[0]


def upsert_variant(conn, product_id, color, size, on_hand_delta=0):
    cur = conn.execute(
        'INSERT INTO product_variants(product_id, color, size, on_hand)
         VALUES(?,?,?,?)
         ON CONFLICT(product_id, color, size)
         DO UPDATE SET on_hand = product_variants.on_hand + excluded.on_hand,
                       updated_at = datetime("now")
         RETURNING id', (product_id, color, size, max(0, on_hand_delta))
    )
    return cur.fetchone()[0]


def dict_from_stock(conn):
    # Devuelve formato { product_name: { colors: { color: { sizes: {size: qty} } } } }
    data = {}
    rows = conn.execute(
        'SELECT p.name, v.color, v.size, (v.on_hand - v.reserved) AS available
         FROM product_variants v JOIN products p ON p.id = v.product_id'
    ).fetchall()
    for r in rows:
        prod = data.setdefault(r['name'], {'colors': {}})
        col = prod['colors'].setdefault(r['color'], {'sizes': {}})
        col['sizes'][r['size']] = max(0, int(r['available']))
    return data


def list_products(conn):
    rows = conn.execute('SELECT * FROM v_variant_availability ORDER BY product_name, color, size').fetchall()
    return [dict(r) for r in rows]


def reserve_order(conn, items, channel=None, note=None):
    # items: [{name, color, size, qty, unit_price}]
    # Regla: al reservar, restar de disponibilidad incrementando reserved
    cur = conn.cursor()
    cur.execute('BEGIN')
    try:
        cur.execute('INSERT INTO orders(status, channel, note) VALUES("reserved", ?, ?)', (channel, note))
        order_id = cur.lastrowid
        for it in items:
            name = it.get('name')
            color = it.get('color')
            size = it.get('size')
            qty = int(it.get('quantity') or it.get('qty') or 1)
            unit_price = float(it.get('unit_price') or it.get('price') or 0)
            if not (name and color and size and qty > 0):
                raise ValueError('Item inválido')
            pid = upsert_product(conn, name)
            # asegurar variante
            vr = conn.execute('SELECT id, on_hand, reserved FROM product_variants WHERE product_id=? AND color=? AND size=?', (pid, color, size)).fetchone()
            if vr is None:
                # variante nueva sin stock -> no permite reservar
                raise ValueError(f'Sin stock para {name} {color} {size}')
            available = int(vr['on_hand']) - int(vr['reserved'])
            if available < qty:
                raise ValueError(f'Sin stock suficiente para {name} {color} {size}. Disponible: {available}')
            cur.execute('UPDATE product_variants SET reserved = reserved + ?, updated_at = datetime("now") WHERE id=?', (qty, vr['id']))
            cur.execute('INSERT INTO order_items(order_id, variant_id, qty, unit_price) VALUES(?,?,?,?)', (order_id, vr['id'], qty, unit_price))
        cur.execute('COMMIT')
        return order_id
    except Exception:
        cur.execute('ROLLBACK')
        raise


def change_order_status(conn, order_id, new_status):
    # paid: mover reserved -> sold y descontar on_hand
    # canceled: restituir reserved
    cur = conn.cursor()
    cur.execute('BEGIN')
    try:
        order = cur.execute('SELECT id, status FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order:
            raise ValueError('Pedido no existe')
        if order['status'] == new_status:
            cur.execute('COMMIT')
            return
        items = cur.execute('SELECT variant_id, qty FROM order_items WHERE order_id=?', (order_id,)).fetchall()
        if new_status == 'paid':
            for it in items:
                cur.execute('UPDATE product_variants SET reserved = reserved - ?, on_hand = on_hand - ?, sold = sold + ?, updated_at = datetime("now") WHERE id=?', (it['qty'], it['qty'], it['qty'], it['variant_id']))
        elif new_status == 'canceled':
            for it in items:
                cur.execute('UPDATE product_variants SET reserved = reserved - ?, updated_at = datetime("now") WHERE id=?', (it['qty'], it['variant_id']))
        else:
            raise ValueError('Estado no soportado')
        cur.execute('UPDATE orders SET status=?, updated_at=datetime("now") WHERE id=?', (new_status, order_id))
        cur.execute('COMMIT')
    except Exception:
        cur.execute('ROLLBACK')
        raise


def restock_variant(conn, name, color, size, qty, ptype=None):
    pid = upsert_product(conn, name, ptype)
    vid = upsert_variant(conn, pid, color, size, on_hand_delta=0)
    conn.execute('UPDATE product_variants SET on_hand = on_hand + ?, updated_at = datetime("now") WHERE id=?', (qty, vid))


class Handler(SimpleHTTPRequestHandler):
    def _set_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            body = b'OK'
            self.send_response(200)
            self._set_cors()
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == '/api/stock':
            try:
                with get_conn() as conn:
                    data = dict_from_stock(conn)
                body = json.dumps(data).encode('utf-8')
                self.send_response(200)
                self._set_cors()
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(500, str(e))
            return
        if parsed.path == '/api/products':
            try:
                with get_conn() as conn:
                    data = list_products(conn)
                body = json.dumps(data).encode('utf-8')
                self.send_response(200)
                self._set_cors()
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(500, str(e))
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        if parsed.path == '/api/orders':
            try:
                items = payload.get('items') or []
                channel = payload.get('channel')
                note = payload.get('note')
                with get_conn() as conn:
                    order_id = reserve_order(conn, items, channel, note)
                    data = {'order_id': order_id, 'status': 'reserved'}
                body = json.dumps(data).encode('utf-8')
                self.send_response(201)
                self._set_cors()
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = json.dumps({'error': str(e)}).encode('utf-8')
                self.send_response(400)
                self._set_cors()
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        if parsed.path.startswith('/api/orders/') and parsed.path.endswith('/confirm'):
            try:
                order_id = int(parsed.path.split('/')[3])
                with get_conn() as conn:
                    change_order_status(conn, order_id, 'paid')
                self.send_response(204)
                self._set_cors()
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        if parsed.path.startswith('/api/orders/') and parsed.path.endswith('/cancel'):
            try:
                order_id = int(parsed.path.split('/')[3])
                with get_conn() as conn:
                    change_order_status(conn, order_id, 'canceled')
                self.send_response(204)
                self._set_cors()
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        if parsed.path == '/api/variants/restock':
            try:
                name = payload['name']
                color = payload['color']
                size = payload['size']
                qty = int(payload['qty'])
                ptype = payload.get('type')
                with get_conn() as conn:
                    restock_variant(conn, name, color, size, qty, ptype)
                self.send_response(204)
                self._set_cors()
                self.end_headers()
            except Exception as e:
                self.send_error(400, str(e))
            return

        self.send_error(404, 'Not Found')


def ensure_seed():
    # Opcional: Sembrar algunos productos de ejemplo si la tabla está vacía
    with get_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM product_variants').fetchone()[0]
        if count == 0:
            samples = [
                ('Calza lycra chupin', 'Negro', '1', 5),
                ('Calza lycra chupin', 'Negro', '2', 5),
                ('Calza lycra chupin', 'Gris', '1', 2),
                ('Camiseta Térmica Frisado', 'Negro', 'M', 3),
                ('Campera Polar Corderito Largo', 'Gris', 'M', 1),
            ]
            for name, color, size, qty in samples:
                restock_variant(conn, name, color, size, qty)


def run(host=None, port=None):
    # Railway: usa PORT y 0.0.0.0
    host = host or os.environ.get('HOST', '0.0.0.0')
    try:
        port = int(os.environ.get('PORT', str(port or 8000)))
    except ValueError:
        port = 8000
    init_db()
    ensure_seed()
    httpd = HTTPServer((host, port), Handler)
    print(f"ROMIX server escuchando en http://{host}:{port}")
    print("Endpoints: /api/stock, /api/products, POST /api/orders, POST /api/orders/<id>/confirm, /cancel, POST /api/variants/restock")
    httpd.serve_forever()


if __name__ == '__main__':
    run()
