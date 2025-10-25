-- ROMIX: esquema de inventario y pedidos
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT,
  base_price REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS product_variants (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL,
  color TEXT NOT NULL,
  size TEXT NOT NULL,
  on_hand INTEGER NOT NULL DEFAULT 0,   -- stock físico en depósito
  reserved INTEGER NOT NULL DEFAULT 0,  -- reservado por pedidos pendientes/confirmados
  sold INTEGER NOT NULL DEFAULT 0,      -- vendido (confirmado)
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE(product_id, color, size),
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('reserved','paid','canceled')),
  channel TEXT,
  note TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  variant_id INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  unit_price REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE CASCADE
);

-- Vistas útiles
CREATE VIEW IF NOT EXISTS v_variant_availability AS
SELECT
  v.id AS variant_id,
  p.name AS product_name,
  p.type AS product_type,
  v.color,
  v.size,
  v.on_hand,
  v.reserved,
  v.sold,
  (v.on_hand - v.reserved) AS available
FROM product_variants v
JOIN products p ON p.id = v.product_id;

