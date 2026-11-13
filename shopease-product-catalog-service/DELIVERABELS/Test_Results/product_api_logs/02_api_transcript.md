# Product API evidence

Recorded 2026-11-12 09:54:14 UTC by `python -m scripts.product_api_evidence`.

**54 of 54 steps returned the expected status.**

## Part A: write scenarios (real app, MySQL test database, stand-in Authentication Service)

All changes below were made inside one transaction that was rolled back afterwards.

### PASS: Admin creates a category

`POST /api/categories/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "name": "Evidence Apparel"
}
```

Response:
```json
{
  "id": 1499,
  "name": "Evidence Apparel",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Admin creates a second category, to be deactivated

`POST /api/categories/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "name": "Evidence Archive"
}
```

Response:
```json
{
  "id": 1500,
  "name": "Evidence Archive",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Admin deactivates it

`PATCH /api/categories/1500` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "is_active": false
}
```

Response:
```json
{
  "id": 1500,
  "name": "Evidence Archive",
  "description": null,
  "is_active": false,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

## Create

### PASS: Admin creates a product with initial stock

`POST /api/products/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "category_id": 1499,
  "name": "Red  Cotton T-Shirt",
  "sku": "ev-tee-red-m",
  "price": "19.5",
  "discount_price": "14.99",
  "brand": "Basics",
  "image_url": "https://cdn.example.com/tee.png",
  "initial_stock": 25
}
```

Response:
```json
{
  "id": 1482,
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": null,
  "sku": "EV-TEE-RED-M",
  "price": "19.50",
  "discount_price": "14.99",
  "effective_price": "14.99",
  "stock_quantity": 25,
  "in_stock": true,
  "image_url": "https://cdn.example.com/tee.png",
  "brand": "Basics",
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Duplicate SKU, different letter case

`POST /api/products/` as **ADMIN**, expected **409**, got **409**

Request body:
```json
{
  "category_id": 1499,
  "name": "Copy",
  "sku": "EV-TEE-RED-M",
  "price": "5.00"
}
```

Response:
```json
{
  "detail": "A product with this SKU already exists"
}
```

### PASS: Required fields missing

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "category_id",
      "message": "Field required"
    },
    {
      "field": "name",
      "message": "Field required"
    },
    {
      "field": "sku",
      "message": "Field required"
    },
    {
      "field": "price",
      "message": "Field required"
    }
  ]
}
```

### PASS: Negative price

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1499,
  "name": "Bad",
  "sku": "EV-BAD-1",
  "price": "-1.00"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "price",
      "message": "Input should be greater than or equal to 0"
    }
  ]
}
```

### PASS: Discount equal to price

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1499,
  "name": "Bad",
  "sku": "EV-BAD-2",
  "price": "10.00",
  "discount_price": "10.00"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "discount_price",
      "message": "discount_price must be lower than price"
    }
  ]
}
```

### PASS: Three decimal places

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1499,
  "name": "Bad",
  "sku": "EV-BAD-3",
  "price": "1.999"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "price",
      "message": "Decimal input should have no more than 2 decimal places"
    }
  ]
}
```

### PASS: Negative initial stock

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1499,
  "name": "Bad",
  "sku": "EV-BAD-4",
  "price": "1.00",
  "initial_stock": -3
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "initial_stock",
      "message": "Input should be greater than or equal to 0"
    }
  ]
}
```

### PASS: stock_quantity cannot be set

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1499,
  "name": "Bad",
  "sku": "EV-BAD-5",
  "price": "1.00",
  "stock_quantity": 5
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

### PASS: Category does not exist

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 999999,
  "name": "Bad",
  "sku": "EV-BAD-6",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "category_id",
      "message": "category_id does not refer to an existing category"
    }
  ]
}
```

### PASS: Category is inactive

`POST /api/products/` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1500,
  "name": "Bad",
  "sku": "EV-BAD-7",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "category_id",
      "message": "category_id refers to an inactive category"
    }
  ]
}
```

### PASS: Malformed JSON

`POST /api/products/` as **ADMIN**, expected **400**, got **400**

Request body (raw): `{"name": "x",`

Response:
```json
{
  "detail": "Request body is not valid JSON"
}
```

### PASS: Customer cannot create

`POST /api/products/` as **CUSTOMER (USER)**, expected **403**, got **403**

Request body:
```json
{
  "category_id": 1499,
  "name": "Nope",
  "sku": "EV-NOPE",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Admin role required"
}
```

### PASS: Anonymous cannot create

`POST /api/products/` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "category_id": 1499,
  "name": "Nope",
  "sku": "EV-NOPE",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

## Read

### PASS: Admin creates a second product

`POST /api/products/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "category_id": 1499,
  "name": "Plain Mug",
  "sku": "EV-MUG",
  "price": "8.00"
}
```

Response:
```json
{
  "id": 1483,
  "category_id": 1499,
  "name": "Plain Mug",
  "description": null,
  "sku": "EV-MUG",
  "price": "8.00",
  "discount_price": null,
  "effective_price": "8.00",
  "stock_quantity": 0,
  "in_stock": false,
  "image_url": null,
  "brand": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Customer lists products

`GET /api/products/` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1483,
      "category_id": 1499,
      "name": "Plain Mug",
      "description": null,
      "sku": "EV-MUG",
      "price": "8.00",
      "discount_price": null,
      "effective_price": "8.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:14Z",
      "updated_at": "2026-11-12T09:54:14Z"
    },
    {
      "id": 1482,
      "category_id": 1499,
      "name": "Red Cotton T-Shirt",
      "description": null,
      "sku": "EV-TEE-RED-M",
      "price": "19.50",
      "discount_price": "14.99",
      "effective_price": "14.99",
      "stock_quantity": 25,
      "in_stock": true,
      "image_url": "https://cdn.example.com/tee.png",
      "brand": "Basics",
      "is_active": true,
      "created_at": "2026-11-12T09:54:14Z",
      "updated_at": "2026-11-12T09:54:14Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### PASS: Customer gets a product

`GET /api/products/1482` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "id": 1482,
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": null,
  "sku": "EV-TEE-RED-M",
  "price": "19.50",
  "discount_price": "14.99",
  "effective_price": "14.99",
  "stock_quantity": 25,
  "in_stock": true,
  "image_url": "https://cdn.example.com/tee.png",
  "brand": "Basics",
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Missing product

`GET /api/products/999999` as **CUSTOMER (USER)**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Invalid product ID

`GET /api/products/abc` as **CUSTOMER (USER)**, expected **422**, got **422**

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

### PASS: Customer asks for inactive products

`GET /api/products/?include_inactive=true` as **CUSTOMER (USER)**, expected **403**, got **403**

Response:
```json
{
  "detail": "Admin role required"
}
```

## Update

### PASS: Admin replaces a product (PUT)

`PUT /api/products/1482` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": "Regular fit",
  "sku": "EV-TEE-RED-M",
  "price": "21.00",
  "discount_price": null,
  "image_url": null,
  "brand": "Basics",
  "is_active": true
}
```

Response:
```json
{
  "id": 1482,
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": "Regular fit",
  "sku": "EV-TEE-RED-M",
  "price": "21.00",
  "discount_price": null,
  "effective_price": "21.00",
  "stock_quantity": 25,
  "in_stock": true,
  "image_url": null,
  "brand": "Basics",
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: PUT without every field

`PUT /api/products/1482` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "name": "Only a name"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "category_id",
      "message": "Field required"
    },
    {
      "field": "description",
      "message": "Field required"
    },
    {
      "field": "sku",
      "message": "Field required"
    },
    {
      "field": "price",
      "message": "Field required"
    },
    {
      "field": "discount_price",
      "message": "Field required"
    },
    {
      "field": "image_url",
      "message": "Field required"
    },
    {
      "field": "brand",
      "message": "Field required"
    },
    {
      "field": "is_active",
      "message": "Field required"
    }
  ]
}
```

### PASS: PUT to the other product's SKU

`PUT /api/products/1483` as **ADMIN**, expected **409**, got **409**

Request body:
```json
{
  "category_id": 1499,
  "name": "Mug",
  "description": "Regular fit",
  "sku": "EV-TEE-RED-M",
  "price": "21.00",
  "discount_price": null,
  "image_url": null,
  "brand": "Basics",
  "is_active": true
}
```

Response:
```json
{
  "detail": "A product with this SKU already exists"
}
```

### PASS: Admin changes one field (PATCH)

`PATCH /api/products/1482` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "discount_price": "18.00"
}
```

Response:
```json
{
  "id": 1482,
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": "Regular fit",
  "sku": "EV-TEE-RED-M",
  "price": "21.00",
  "discount_price": "18.00",
  "effective_price": "18.00",
  "stock_quantity": 25,
  "in_stock": true,
  "image_url": null,
  "brand": "Basics",
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: PATCH a discount above the stored price

`PATCH /api/products/1482` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "discount_price": "25.00"
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "discount_price",
      "message": "discount_price must be lower than price"
    }
  ]
}
```

### PASS: PATCH stock directly

`PATCH /api/products/1482` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "stock_quantity": -1
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

### PASS: PATCH into an inactive category

`PATCH /api/products/1482` as **ADMIN**, expected **422**, got **422**

Request body:
```json
{
  "category_id": 1500
}
```

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "category_id",
      "message": "category_id refers to an inactive category"
    }
  ]
}
```

### PASS: PATCH a missing product

`PATCH /api/products/999999` as **ADMIN**, expected **404**, got **404**

Request body:
```json
{
  "name": "X"
}
```

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Customer cannot PUT

`PUT /api/products/1482` as **CUSTOMER (USER)**, expected **403**, got **403**

Request body:
```json
{
  "category_id": 1499,
  "name": "Red Cotton T-Shirt",
  "description": "Regular fit",
  "sku": "EV-TEE-RED-M",
  "price": "21.00",
  "discount_price": null,
  "image_url": null,
  "brand": "Basics",
  "is_active": true
}
```

Response:
```json
{
  "detail": "Admin role required"
}
```

### PASS: Customer cannot PATCH

`PATCH /api/products/1482` as **CUSTOMER (USER)**, expected **403**, got **403**

Request body:
```json
{
  "price": "0.01"
}
```

Response:
```json
{
  "detail": "Admin role required"
}
```

## Deactivate and reactivate

### PASS: Admin deletes (deactivates) a product

`DELETE /api/products/1483` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "message": "Product deactivated"
}
```

### PASS: Customer no longer sees it

`GET /api/products/1483` as **CUSTOMER (USER)**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Customer listing leaves it out

`GET /api/products/` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1482,
      "category_id": 1499,
      "name": "Red Cotton T-Shirt",
      "description": "Regular fit",
      "sku": "EV-TEE-RED-M",
      "price": "21.00",
      "discount_price": "18.00",
      "effective_price": "18.00",
      "stock_quantity": 25,
      "in_stock": true,
      "image_url": null,
      "brand": "Basics",
      "is_active": true,
      "created_at": "2026-11-12T09:54:14Z",
      "updated_at": "2026-11-12T09:54:14Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

### PASS: Admin still sees it with include_inactive

`GET /api/products/1483?include_inactive=true` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "id": 1483,
  "category_id": 1499,
  "name": "Plain Mug",
  "description": null,
  "sku": "EV-MUG",
  "price": "8.00",
  "discount_price": null,
  "effective_price": "8.00",
  "stock_quantity": 0,
  "in_stock": false,
  "image_url": null,
  "brand": null,
  "is_active": false,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Admin reactivates it

`PATCH /api/products/1483` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "is_active": true
}
```

Response:
```json
{
  "id": 1483,
  "category_id": 1499,
  "name": "Plain Mug",
  "description": null,
  "sku": "EV-MUG",
  "price": "8.00",
  "discount_price": null,
  "effective_price": "8.00",
  "stock_quantity": 0,
  "in_stock": false,
  "image_url": null,
  "brand": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:14Z"
}
```

### PASS: Customer cannot delete

`DELETE /api/products/1482` as **CUSTOMER (USER)**, expected **403**, got **403**

Response:
```json
{
  "detail": "Admin role required"
}
```

### PASS: Delete a missing product

`DELETE /api/products/999999` as **ADMIN**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

## Products in an inactive category

### PASS: Admin deactivates the product's category

`PATCH /api/categories/1499` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "is_active": false
}
```

Response:
```json
{
  "id": 1499,
  "name": "Evidence Apparel",
  "description": null,
  "is_active": false,
  "created_at": "2026-11-12T09:54:14Z",
  "updated_at": "2026-11-12T09:54:15Z"
}
```

### PASS: Customer listing is now empty

`GET /api/products/` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

### PASS: Customer gets 404 for the product

`GET /api/products/1482` as **CUSTOMER (USER)**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

Transaction rolled back: the test database holds none of the rows above.

## Part B: live container, configured database, real Authentication Service

Base URL `http://127.0.0.1:8006`. Only reads and refused writes.

### PASS: List products, anonymous

`GET /api/products/` as **anonymous**, expected **200**, got **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

### PASS: List products without the slash, no redirect

`GET /api/products` as **anonymous**, expected **200**, got **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

### PASS: Missing product

`GET /api/products/999999` as **anonymous**, expected **404**, got **404**

Response:
```json
{
  "detail": "Product not found"
}
```

### PASS: Invalid product ID

`GET /api/products/0` as **anonymous**, expected **422**, got **422**

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

### PASS: Bad query parameter

`GET /api/products/?page_size=1000` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "page_size",
      "message": "Input should be less than or equal to 100"
    }
  ]
}
```

### PASS: Create without a token

`POST /api/products/` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "category_id": 1,
  "name": "X",
  "sku": "LIVE-X",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Create with a forged ADMIN token (rejected by the real Authentication Service)

`POST /api/products/` as **forged token**, expected **401**, got **401**

Request body:
```json
{
  "category_id": 1,
  "name": "X",
  "sku": "LIVE-X",
  "price": "1.00"
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: PUT without a token

`PUT /api/products/1` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "category_id": 1,
  "name": "X",
  "description": null,
  "sku": "LIVE-X",
  "price": "1.00",
  "discount_price": null,
  "image_url": null,
  "brand": null,
  "is_active": true
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: PATCH without a token

`PATCH /api/products/1` as **anonymous**, expected **401**, got **401**

Request body:
```json
{
  "price": "0.01"
}
```

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: DELETE without a token

`DELETE /api/products/1` as **anonymous**, expected **401**, got **401**

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: include_inactive without a token

`GET /api/products/?include_inactive=true` as **anonymous**, expected **401**, got **401**

Response:
```json
{
  "detail": "Could not validate credentials"
}
```

### PASS: Malformed JSON

`POST /api/products/` as **anonymous**, expected **400**, got **400**

Request body (raw): `{not json`

Response:
```json
{
  "detail": "Request body is not valid JSON"
}
```
