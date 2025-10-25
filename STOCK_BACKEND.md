ROMIX inventario y pedidos (SQLite + Python)

Resumen
- Base de datos SQLite con productos, variantes (color/talle), pedidos y renglones.
- Servidor HTTP con la librería estándar de Python: sirve `index.html` y expone APIs.
- La página usa el backend si está corriendo; si no, sigue con stock local por defecto.

Requisitos
- Python 3.8+ instalado (incluye `sqlite3` y `http.server`). No se requieren paquetes externos.

Cómo iniciar
1) Opcional: revise/edite el seed en `server.py::ensure_seed()`.
2) Desde la raíz del repo, ejecute:
   - Windows: `python server.py`
   - macOS/Linux: `python3 server.py`
3) Abra `http://127.0.0.1:8000` en el navegador.

Esquema (SQLite)
- Archivo: `db/romix.db` (se crea automáticamente)
- DDL: `db/schema.sql`
- Tablas clave:
  - `products`: producto base (nombre, tipo, precio base)
  - `product_variants`: variante por color/talle con columnas `on_hand` (físico), `reserved`, `sold`
  - `orders`: pedidos con estados `reserved`, `paid`, `canceled`
  - `order_items`: renglones del pedido

Reglas de stock
- Al crear un pedido (reserva) se incrementa `reserved` y se reduce la disponibilidad inmediatamente.
- Al confirmar (pago) se mueve `reserved -> sold` y se descuenta `on_hand`.
- Al cancelar se revierte `reserved`.

Endpoints
- GET `/api/stock` → mapa `{ producto: { colors: { color: { sizes: { talle: cantidad }}}}}` usado por el frontend.
- GET `/api/products` → lista detallada por variante con `available`.
- POST `/api/orders` → reserva un pedido.
  - Body JSON: `{ items: [{ name, color, size, quantity, unit_price }], channel?, note? }`
- POST `/api/orders/{id}/confirm` → confirma el pedido.
- POST `/api/orders/{id}/cancel` → cancela el pedido.
- POST `/api/variants/restock` → reponer una variante.
  - Body JSON: `{ name, color, size, qty, type? }`

Ejemplos (PowerShell)
1) Reponer stock:
```
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/variants/restock -Method POST -ContentType 'application/json' -Body '{"name":"Calza lycra chupin","color":"Negro","size":"1","qty":10}'
```

2) Reservar pedido:
```
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/orders -Method POST -ContentType 'application/json' -Body '{"items":[{"name":"Calza lycra chupin","color":"Negro","size":"1","quantity":2}]}'
```

3) Confirmar pedido:
```
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/orders/1/confirm -Method POST
```

4) Cancelar pedido:
```
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/orders/1/cancel -Method POST
```

Notas
- Si el backend no corre, la página usa stock por defecto y no reserva.
- Puede ajustar los productos y variantes que aparecen en `ensure_seed()` o reponer variantes específicas con el endpoint de restock.

