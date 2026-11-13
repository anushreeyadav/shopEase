# Inventory API evidence

Recorded 2026-11-12 12:49:03 UTC by `python -m scripts.inventory_evidence`.

**48 of 48 checks passed** (every HTTP status and every content check).

## Part A: real app, MySQL test database, stand-in Authentication Service

Everything below happened inside one transaction that was rolled back afterwards. LOW_STOCK_THRESHOLD = 5.

### PASS: Admin creates a category

`POST /api/categories/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "name": "Evidence Inventory"
}
```

Response:
```json
{
  "id": 2270,
  "name": "Evidence Inventory",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T12:49:03Z",
  "updated_at": "2026-11-12T12:49:03Z"
}
```

## Initial stock

### PASS: Admin creates a product with initial_stock 10

`POST /api/products/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "category_id": 2270,
  "name": "Evidence Kettle",
  "sku": "EV-INV-1",
  "price": "30.00",
  "initial_stock": 10
}
```

Response:
```json
{
  "id": 2647,
  "category_id": 2270,
  "name": "Evidence Kettle",
  "description": null,
  "sku": "EV-INV-1",
  "price": "30.00",
  "discount_price": null,
  "effective_price": "30.00",
  "stock_quantity": 10,
  "in_stock": true,
  "image_url": null,
  "brand": null,
  "is_active": true,
  "created_at": "2026-11-12T12:49:03Z",
  "updated_at": "2026-11-12T12:49:03Z"
}
```

### PASS: Its history: one IN transaction, remarks Initial stock

`GET /api/inventory/2647/history` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 2042,
      "product_id": 2647,
      "transaction_type": "IN",
      "quantity": 10,
      "previous_stock": 0,
      "updated_stock": 10,
      "remarks": "Initial stock",
      "created_at": "2026-11-12T12:49:03Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### PASS: PATCH cannot change stock_quantity

`PATCH /api/products/2647` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "stock_quantity": 99
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "stock_quantity",
      "message": "Extra inputs are not permitted"
    }
  ]
}
```

## Current stock, stock-in, stock-out

### PASS: Current stock

`GET /api/inventory/2647` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "product_id": 2647,
  "sku": "EV-INV-1",
  "name": "Evidence Kettle",
  "stock_quantity": 10,
  "low_stock_threshold": 5,
  "is_low_stock": false
}
```

### PASS: Stock-in 5

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "quantity": 5,
  "remarks": "Supplier delivery, invoice 4471"
}
```

Response:
```json
{
  "transaction": {
    "id": 2043,
    "product_id": 2647,
    "transaction_type": "IN",
    "quantity": 5,
    "previous_stock": 10,
    "updated_stock": 15,
    "remarks": "Supplier delivery, invoice 4471",
    "created_at": "2026-11-12T12:49:03Z"
  },
  "stock": {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 15,
    "low_stock_threshold": 5,
    "is_low_stock": false
  }
}
```

### PASS: Stock-out 3

`POST /api/inventory/2647/stock-out` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "quantity": 3,
  "remarks": "Order 1001"
}
```

Response:
```json
{
  "transaction": {
    "id": 2044,
    "product_id": 2647,
    "transaction_type": "OUT",
    "quantity": 3,
    "previous_stock": 15,
    "updated_stock": 12,
    "remarks": "Order 1001",
    "created_at": "2026-11-12T12:49:03Z"
  },
  "stock": {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 12,
    "low_stock_threshold": 5,
    "is_low_stock": false
  }
}
```

### PASS: Stock-out 8: down to 4, at or below the threshold

`POST /api/inventory/2647/stock-out` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "quantity": 8
}
```

Response:
```json
{
  "transaction": {
    "id": 2045,
    "product_id": 2647,
    "transaction_type": "OUT",
    "quantity": 8,
    "previous_stock": 12,
    "updated_stock": 4,
    "remarks": null,
    "created_at": "2026-11-12T12:49:03Z"
  },
  "stock": {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 4,
    "low_stock_threshold": 5,
    "is_low_stock": true
  }
}
```

## Insufficient stock and invalid quantities

### PASS: Stock-out 5 with 4 available

`POST /api/inventory/2647/stock-out` as **ADMIN**, expected **409**, got **409**

Request body:
```json
{
  "quantity": 5
}
```

Response:
```json
{
  "detail": "Insufficient stock: 4 available, 5 requested"
}
```

### PASS: Stock is still 4

`GET /api/inventory/2647` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "product_id": 2647,
  "sku": "EV-INV-1",
  "name": "Evidence Kettle",
  "stock_quantity": 4,
  "low_stock_threshold": 5,
  "is_low_stock": true
}
```

### PASS: Stock-in quantity 0

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": 0
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: Stock-in quantity -2

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": -2
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: Stock-in quantity 1.5

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": 1.5
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Input should be a valid integer"
    }
  ]
}
```

### PASS: Stock-in quantity '3'

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": "3"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Input should be a valid integer"
    }
  ]
}
```

### PASS: Stock-out quantity 0

`POST /api/inventory/2647/stock-out` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": 0
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: Quantity missing

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "remarks": "no quantity"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "quantity",
      "message": "Field required"
    }
  ]
}
```

### PASS: Malformed JSON

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **400**, got **400**

Request body (raw): `{"quantity": `

Response:
```json
{
  "detail": "Request body is not valid JSON"
}
```

## Invalid and unknown product IDs

### PASS: Unknown product: stock

`GET /api/inventory/999999` as **ADMIN**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Unknown product: stock-in

`POST /api/inventory/999999/stock-in` as **ADMIN**, expected **404**, got **404**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Unknown product: stock-out

`POST /api/inventory/999999/stock-out` as **ADMIN**, expected **404**, got **404**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Unknown product: history

`GET /api/inventory/999999/history` as **ADMIN**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Invalid product ID 0

`GET /api/inventory/0` as **ADMIN**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "product_id",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: Invalid product ID abc

`POST /api/inventory/abc/stock-out` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "product_id",
      "message": "Input should be a valid integer, unable to parse string as an integer"
    }
  ]
}
```

## Access

### PASS: Customer cannot stock-in

`POST /api/inventory/2647/stock-in` as **CUSTOMER (USER)**, expected **403**, got **403**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Admin role required"
}
```

### PASS: Customer cannot stock-out

`POST /api/inventory/2647/stock-out` as **CUSTOMER (USER)**, expected **403**, got **403**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Admin role required"
}
```

### PASS: Anonymous cannot stock-in

`POST /api/inventory/2647/stock-in` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Customer cannot read the history

`GET /api/inventory/2647/history` as **CUSTOMER (USER)**, expected **403**, got **403**

Response:
```json
{
  "detail": "Admin role required"
}
```

## A failed write is rolled back

A listener makes MySQL's `INSERT INTO inventory_transactions` fail, as a lost connection would, after the product's `UPDATE` has already been sent in the same transaction.

### PASS: Stock-in 50 while the history insert fails

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **503**, got **503**

Request body:
```json
{
  "quantity": 50
}
```

Response:
```json
{
  "detail": "Service temporarily unavailable"
}
```

### PASS: Stock afterwards: still 4, the UPDATE was rolled back

`GET /api/inventory/2647` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "product_id": 2647,
  "sku": "EV-INV-1",
  "name": "Evidence Kettle",
  "stock_quantity": 4,
  "low_stock_threshold": 5,
  "is_low_stock": true
}
```

Check, stock unchanged: **PASS**. stock_quantity = 4.

### PASS: The row lock was released: the next stock-in works

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "transaction": {
    "id": 2046,
    "product_id": 2647,
    "transaction_type": "IN",
    "quantity": 1,
    "previous_stock": 4,
    "updated_stock": 5,
    "remarks": null,
    "created_at": "2026-11-12T12:49:04Z"
  },
  "stock": {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 5,
    "low_stock_threshold": 5,
    "is_low_stock": true
  }
}
```

## History and low stock

### PASS: Complete history, newest first

`GET /api/inventory/2647/history` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 2046,
      "product_id": 2647,
      "transaction_type": "IN",
      "quantity": 1,
      "previous_stock": 4,
      "updated_stock": 5,
      "remarks": null,
      "created_at": "2026-11-12T12:49:04Z"
    },
    {
      "id": 2045,
      "product_id": 2647,
      "transaction_type": "OUT",
      "quantity": 8,
      "previous_stock": 12,
      "updated_stock": 4,
      "remarks": null,
      "created_at": "2026-11-12T12:49:03Z"
    },
    {
      "id": 2044,
      "product_id": 2647,
      "transaction_type": "OUT",
      "quantity": 3,
      "previous_stock": 15,
      "updated_stock": 12,
      "remarks": "Order 1001",
      "created_at": "2026-11-12T12:49:03Z"
    },
    {
      "id": 2043,
      "product_id": 2647,
      "transaction_type": "IN",
      "quantity": 5,
      "previous_stock": 10,
      "updated_stock": 15,
      "remarks": "Supplier delivery, invoice 4471",
      "created_at": "2026-11-12T12:49:03Z"
    },
    {
      "id": 2042,
      "product_id": 2647,
      "transaction_type": "IN",
      "quantity": 10,
      "previous_stock": 0,
      "updated_stock": 10,
      "remarks": "Initial stock",
      "created_at": "2026-11-12T12:49:03Z"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, history length: **PASS**. total = 5: initial 10, +5, −3, −8, +1 (the failed +50 is absent).

### PASS: History page 2 of 3, two per page

`GET /api/inventory/2647/history?page=2&page_size=2` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 2044,
      "product_id": 2647,
      "transaction_type": "OUT",
      "quantity": 3,
      "previous_stock": 15,
      "updated_stock": 12,
      "remarks": "Order 1001",
      "created_at": "2026-11-12T12:49:03Z"
    },
    {
      "id": 2043,
      "product_id": 2647,
      "transaction_type": "IN",
      "quantity": 5,
      "previous_stock": 10,
      "updated_stock": 15,
      "remarks": "Supplier delivery, invoice 4471",
      "created_at": "2026-11-12T12:49:03Z"
    }
  ],
  "total": 5,
  "page": 2,
  "page_size": 2,
  "total_pages": 3
}
```

### PASS: Only OUT transactions

`GET /api/inventory/2647/history?transaction_type=OUT` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 2045,
      "product_id": 2647,
      "transaction_type": "OUT",
      "quantity": 8,
      "previous_stock": 12,
      "updated_stock": 4,
      "remarks": null,
      "created_at": "2026-11-12T12:49:03Z"
    },
    {
      "id": 2044,
      "product_id": 2647,
      "transaction_type": "OUT",
      "quantity": 3,
      "previous_stock": 15,
      "updated_stock": 12,
      "remarks": "Order 1001",
      "created_at": "2026-11-12T12:49:03Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, stock matches history: **PASS**. 5 transactions replay 0 → 10 → 15 → 12 → 4 → 5; current stock 5.

### PASS: Low-stock report

`GET /api/inventory/low-stock` as **ADMIN**, expected **200**, got **200**

Response:
```json
[
  {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 5,
    "low_stock_threshold": 5,
    "is_low_stock": true
  }
]
```

Check, product in low-stock report: **PASS**. stock 5 ≤ threshold 5: {'product_id': 2647, 'sku': 'EV-INV-1', 'name': 'Evidence Kettle', 'stock_quantity': 5, 'low_stock_threshold': 5, 'is_low_stock': True}.

### PASS: Stock-in 20

`POST /api/inventory/2647/stock-in` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "quantity": 20
}
```

Response:
```json
{
  "transaction": {
    "id": 2047,
    "product_id": 2647,
    "transaction_type": "IN",
    "quantity": 20,
    "previous_stock": 5,
    "updated_stock": 25,
    "remarks": null,
    "created_at": "2026-11-12T12:49:04Z"
  },
  "stock": {
    "product_id": 2647,
    "sku": "EV-INV-1",
    "name": "Evidence Kettle",
    "stock_quantity": 25,
    "low_stock_threshold": 5,
    "is_low_stock": false
  }
}
```

### PASS: Low-stock report again

`GET /api/inventory/low-stock` as **ADMIN**, expected **200**, got **200**

Response:
```json
[]
```

Check, product left the report: **PASS**. stock 25 is above the threshold.

Check, stock matches history: **PASS**. 6 transactions replay 0 → 10 → 15 → 12 → 4 → 5 → 25; current stock 25.

Transaction rolled back: the test database holds none of the rows above.

## Part B: live container, real Authentication Service

Base URL `http://127.0.0.1:8006`. Only requests that must be refused.

### PASS: Current stock without a token

`GET /api/inventory/1` as **anonymous**, expected **401**, got **401**

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Stock-in without a token

`POST /api/inventory/1/stock-in` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Stock-out without a token

`POST /api/inventory/1/stock-out` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: History without a token

`GET /api/inventory/1/history` as **anonymous**, expected **401**, got **401**

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Low-stock report without a token

`GET /api/inventory/low-stock` as **anonymous**, expected **401**, got **401**

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Stock-in with a forged ADMIN token (rejected by the real Authentication Service)

`POST /api/inventory/1/stock-in` as **forged token**, expected **401**, got **401**

Request body:
```json
{
  "quantity": 1
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```
