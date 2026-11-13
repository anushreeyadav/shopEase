# Product search, filtering, pagination and sorting: evidence

Recorded 2026-11-12 09:54:09 UTC by `python -m scripts.product_search_evidence`.

**85 of 85 checks passed** (every HTTP status and every listing check).

## Part A: real app, MySQL test database, stand-in Authentication Service

Everything below happened inside one transaction that was rolled back afterwards. `search=EV-` limits each listing to the evidence products, in case the test database holds other rows.

## Setup: a known catalogue

| Name | SKU | Price | Stock | Category | Hidden from customers because |
|---|---|---|---|---|---|
| Galaxy Mobile | EV-MOB-100 | 1500.00 | 5 | phones |  |
| Pixel Mobile | EV-MOB-200 | 4500.00 | 0 | phones |  |
| Budget Phone | EV-PHN-300 | 800.00 | 12 | phones |  |
| Laptop Stand | EV-MOBILE-STAND | 1000.00 | 0 | laptops |  |
| Ultrabook | EV-LAP-500 | 5000.00 | 7 | laptops |  |
| Gaming Laptop | EV-LAP-600 | 5000.01 | 2 | laptops |  |
| Retired Mobile | EV-MOB-900 | 2000.00 | 4 | phones | product inactive |
| Archive Mobile | EV-MOB-950 | 3000.00 | 6 | archive | category inactive |

### PASS: Admin creates category Evidence Phones

`POST /api/categories/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "name": "Evidence Phones"
}
```

Response:
```json
{
  "id": 1496,
  "name": "Evidence Phones",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:09Z",
  "updated_at": "2026-11-12T09:54:09Z"
}
```

### PASS: Admin creates category Evidence Laptops

`POST /api/categories/` as **ADMIN**, expected **201**, got **201**

Request body:
```json
{
  "name": "Evidence Laptops"
}
```

Response:
```json
{
  "id": 1497,
  "name": "Evidence Laptops",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:10Z",
  "updated_at": "2026-11-12T09:54:10Z"
}
```

### PASS: Admin creates category Evidence Archive

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
  "id": 1498,
  "name": "Evidence Archive",
  "description": null,
  "is_active": true,
  "created_at": "2026-11-12T09:54:10Z",
  "updated_at": "2026-11-12T09:54:10Z"
}
```

Check, eight products created: **PASS**. Created with `POST /api/products/`; each must answer 201 (responses not repeated).

### PASS: Admin deactivates Retired Mobile

`PATCH /api/products/1480` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "is_active": false
}
```

Response:
```json
{
  "id": 1480,
  "category_id": 1496,
  "name": "Retired Mobile",
  "description": null,
  "sku": "EV-MOB-900",
  "price": "2000.00",
  "discount_price": null,
  "effective_price": "2000.00",
  "stock_quantity": 4,
  "in_stock": true,
  "image_url": null,
  "brand": null,
  "is_active": false,
  "created_at": "2026-11-12T09:54:10Z",
  "updated_at": "2026-11-12T09:54:10Z"
}
```

### PASS: Admin deactivates category Evidence Archive

`PATCH /api/categories/1498` as **ADMIN**, expected **200**, got **200**

Request body:
```json
{
  "is_active": false
}
```

Response:
```json
{
  "id": 1498,
  "name": "Evidence Archive",
  "description": null,
  "is_active": false,
  "created_at": "2026-11-12T09:54:10Z",
  "updated_at": "2026-11-12T09:54:10Z"
}
```

## The task's example requests (as a customer)

### PASS: search=mobile (name or SKU; hidden products left out)

`GET /api/products/?search=mobile` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200']`, got `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200']`.

Check, total: **PASS**. Expected 3, got 3.

### PASS: category_id

`GET /api/products/?category_id=1496` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1476,
      "category_id": 1496,
      "name": "Budget Phone",
      "description": null,
      "sku": "EV-PHN-300",
      "price": "800.00",
      "discount_price": null,
      "effective_price": "800.00",
      "stock_quantity": 12,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-PHN-300', 'EV-MOB-100', 'EV-MOB-200']`, got `['EV-PHN-300', 'EV-MOB-100', 'EV-MOB-200']`.

Check, total: **PASS**. Expected 3, got 3.

### PASS: min_price=1000&max_price=5000 (inclusive)

`GET /api/products/?search=EV-&min_price=1000&max_price=5000` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 4,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-LAP-500']`, got `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-LAP-500']`.

Check, total: **PASS**. Expected 4, got 4.

### PASS: page=1&page_size=10

`GET /api/products/?search=EV-&page=1&page_size=10` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1476,
      "category_id": 1496,
      "name": "Budget Phone",
      "description": null,
      "sku": "EV-PHN-300",
      "price": "800.00",
      "discount_price": null,
      "effective_price": "800.00",
      "stock_quantity": 12,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1479,
      "category_id": 1497,
      "name": "Gaming Laptop",
      "description": null,
      "sku": "EV-LAP-600",
      "price": "5000.01",
      "discount_price": null,
      "effective_price": "5000.01",
      "stock_quantity": 2,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 6,
  "page": 1,
  "page_size": 10,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-PHN-300', 'EV-MOB-100', 'EV-LAP-600', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-LAP-500']`, got `['EV-PHN-300', 'EV-MOB-100', 'EV-LAP-600', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-LAP-500']`.

Check, total: **PASS**. Expected 6, got 6.

### PASS: sort_by=price&sort_order=asc

`GET /api/products/?search=EV-&sort_by=price&sort_order=asc` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1476,
      "category_id": 1496,
      "name": "Budget Phone",
      "description": null,
      "sku": "EV-PHN-300",
      "price": "800.00",
      "discount_price": null,
      "effective_price": "800.00",
      "stock_quantity": 12,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1479,
      "category_id": 1497,
      "name": "Gaming Laptop",
      "description": null,
      "sku": "EV-LAP-600",
      "price": "5000.01",
      "discount_price": null,
      "effective_price": "5000.01",
      "stock_quantity": 2,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 6,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-PHN-300', 'EV-MOBILE-STAND', 'EV-MOB-100', 'EV-MOB-200', 'EV-LAP-500', 'EV-LAP-600']`, got `['EV-PHN-300', 'EV-MOBILE-STAND', 'EV-MOB-100', 'EV-MOB-200', 'EV-LAP-500', 'EV-LAP-600']`.

Check, total: **PASS**. Expected 6, got 6.

## Filters and combinations

### PASS: availability=in_stock

`GET /api/products/?search=EV-&availability=in_stock` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1476,
      "category_id": 1496,
      "name": "Budget Phone",
      "description": null,
      "sku": "EV-PHN-300",
      "price": "800.00",
      "discount_price": null,
      "effective_price": "800.00",
      "stock_quantity": 12,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1479,
      "category_id": 1497,
      "name": "Gaming Laptop",
      "description": null,
      "sku": "EV-LAP-600",
      "price": "5000.01",
      "discount_price": null,
      "effective_price": "5000.01",
      "stock_quantity": 2,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 4,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-PHN-300', 'EV-MOB-100', 'EV-LAP-600', 'EV-LAP-500']`, got `['EV-PHN-300', 'EV-MOB-100', 'EV-LAP-600', 'EV-LAP-500']`.

Check, total: **PASS**. Expected 4, got 4.

### PASS: availability=out_of_stock

`GET /api/products/?search=EV-&availability=out_of_stock` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOBILE-STAND', 'EV-MOB-200']`, got `['EV-MOBILE-STAND', 'EV-MOB-200']`.

Check, total: **PASS**. Expected 2, got 2.

### PASS: search + category + price range + availability + sort

`GET /api/products/?search=mobile&category_id=1496&min_price=1000&max_price=5000&availability=in_stock&sort_by=price&sort_order=desc` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-100']`, got `['EV-MOB-100']`.

Check, total: **PASS**. Expected 1, got 1.

### PASS: category + availability, newest first

`GET /api/products/?category_id=1497&availability=in_stock&sort_by=created_at&sort_order=desc` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1479,
      "category_id": 1497,
      "name": "Gaming Laptop",
      "description": null,
      "sku": "EV-LAP-600",
      "price": "5000.01",
      "discount_price": null,
      "effective_price": "5000.01",
      "stock_quantity": 2,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-LAP-600', 'EV-LAP-500']`, got `['EV-LAP-600', 'EV-LAP-500']`.

Check, total: **PASS**. Expected 2, got 2.

### PASS: Nothing matches

`GET /api/products/?search=EV-ZZZ` as **CUSTOMER (USER)**, expected **200**, got **200**

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

Check, SKUs in order: **PASS**. Expected `[]`, got `[]`.

Check, total: **PASS**. Expected 0, got 0.

## Pagination

### PASS: Page 1 of 3, two per page, by price

`GET /api/products/?search=EV-&page=1&page_size=2&sort_by=price` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1476,
      "category_id": 1496,
      "name": "Budget Phone",
      "description": null,
      "sku": "EV-PHN-300",
      "price": "800.00",
      "discount_price": null,
      "effective_price": "800.00",
      "stock_quantity": 12,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 6,
  "page": 1,
  "page_size": 2,
  "total_pages": 3
}
```

Check, SKUs in order: **PASS**. Expected `['EV-PHN-300', 'EV-MOBILE-STAND']`, got `['EV-PHN-300', 'EV-MOBILE-STAND']`.

Check, total: **PASS**. Expected 6, got 6.

### PASS: Page 3 of 3

`GET /api/products/?search=EV-&page=3&page_size=2&sort_by=price` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1478,
      "category_id": 1497,
      "name": "Ultrabook",
      "description": null,
      "sku": "EV-LAP-500",
      "price": "5000.00",
      "discount_price": null,
      "effective_price": "5000.00",
      "stock_quantity": 7,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1479,
      "category_id": 1497,
      "name": "Gaming Laptop",
      "description": null,
      "sku": "EV-LAP-600",
      "price": "5000.01",
      "discount_price": null,
      "effective_price": "5000.01",
      "stock_quantity": 2,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 6,
  "page": 3,
  "page_size": 2,
  "total_pages": 3
}
```

Check, SKUs in order: **PASS**. Expected `['EV-LAP-500', 'EV-LAP-600']`, got `['EV-LAP-500', 'EV-LAP-600']`.

Check, total: **PASS**. Expected 6, got 6.

Check, paging fields: **PASS**. page=3, page_size=2, total_pages=3.

### PASS: Page past the end: empty, total still correct

`GET /api/products/?search=EV-&page=9&page_size=2` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [],
  "total": 6,
  "page": 9,
  "page_size": 2,
  "total_pages": 3
}
```

Check, SKUs in order: **PASS**. Expected `[]`, got `[]`.

Check, total: **PASS**. Expected 6, got 6.

## Visibility

### PASS: Customer searches for the inactive product's exact SKU

`GET /api/products/?search=EV-MOB-900` as **CUSTOMER (USER)**, expected **200**, got **200**

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

Check, SKUs in order: **PASS**. Expected `[]`, got `[]`.

Check, total: **PASS**. Expected 0, got 0.

### PASS: Customer filters on the inactive category

`GET /api/products/?category_id=1498` as **CUSTOMER (USER)**, expected **200**, got **200**

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

Check, SKUs in order: **PASS**. Expected `[]`, got `[]`.

Check, total: **PASS**. Expected 0, got 0.

### PASS: Anonymous visitor, same search as above

`GET /api/products/?search=mobile` as **anonymous**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200']`, got `['EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200']`.

Check, total: **PASS**. Expected 3, got 3.

### PASS: Admin with include_inactive also sees both hidden products

`GET /api/products/?search=mobile&include_inactive=true` as **ADMIN**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1481,
      "category_id": 1498,
      "name": "Archive Mobile",
      "description": null,
      "sku": "EV-MOB-950",
      "price": "3000.00",
      "discount_price": null,
      "effective_price": "3000.00",
      "stock_quantity": 6,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1477,
      "category_id": 1497,
      "name": "Laptop Stand",
      "description": null,
      "sku": "EV-MOBILE-STAND",
      "price": "1000.00",
      "discount_price": null,
      "effective_price": "1000.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1475,
      "category_id": 1496,
      "name": "Pixel Mobile",
      "description": null,
      "sku": "EV-MOB-200",
      "price": "4500.00",
      "discount_price": null,
      "effective_price": "4500.00",
      "stock_quantity": 0,
      "in_stock": false,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    },
    {
      "id": 1480,
      "category_id": 1496,
      "name": "Retired Mobile",
      "description": null,
      "sku": "EV-MOB-900",
      "price": "2000.00",
      "discount_price": null,
      "effective_price": "2000.00",
      "stock_quantity": 4,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": false,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-950', 'EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-MOB-900']`, got `['EV-MOB-950', 'EV-MOB-100', 'EV-MOBILE-STAND', 'EV-MOB-200', 'EV-MOB-900']`.

Check, total: **PASS**. Expected 5, got 5.

### PASS: Customer asks for include_inactive

`GET /api/products/?include_inactive=true` as **CUSTOMER (USER)**, expected **403**, got **403**

Response:
```json
{
  "detail": "Admin role required"
}
```

## Database-level filtering and paging

### PASS: Combined request whose SQL is shown below

`GET /api/products/?search=mobile&min_price=1000&availability=in_stock&page=1&page_size=2&sort_by=price&sort_order=desc` as **CUSTOMER (USER)**, expected **200**, got **200**

Response:
```json
{
  "items": [
    {
      "id": 1474,
      "category_id": 1496,
      "name": "Galaxy Mobile",
      "description": null,
      "sku": "EV-MOB-100",
      "price": "1500.00",
      "discount_price": null,
      "effective_price": "1500.00",
      "stock_quantity": 5,
      "in_stock": true,
      "image_url": null,
      "brand": null,
      "is_active": true,
      "created_at": "2026-11-12T09:54:10Z",
      "updated_at": "2026-11-12T09:54:10Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 2,
  "total_pages": 1
}
```

Check, SKUs in order: **PASS**. Expected `['EV-MOB-100']`, got `['EV-MOB-100']`.

Check, total: **PASS**. Expected 1, got 1.

Check, two queries: COUNT, then one page with LIMIT: **PASS**. 2 statements sent for the products table.

SQL sent to MySQL for that request:
```sql
SELECT count(products.id) AS count_1 FROM products INNER JOIN categories ON categories.id = products.category_id WHERE ((lower(products.name) LIKE concat('%%', %(lower_1)s, '%%') ESCAPE '/') OR (lower(products.sku) LIKE concat('%%', %(lower_2)s, '%%') ESCAPE '/')) AND products.price >= %(price_1)s AND products.stock_quantity > %(stock_quantity_1)s AND products.is_active IS true AND categories.is_active IS true
-- parameters: {'lower_1': 'mobile', 'lower_2': 'mobile', 'price_1': Decimal('1000.00'), 'stock_quantity_1': 0}

SELECT products.id, products.category_id, products.name, products.description, products.sku, products.price, products.discount_price, products.stock_quantity, products.image_url, products.brand, products.is_active, products.created_at, products.updated_at FROM products INNER JOIN categories ON categories.id = products.category_id WHERE ((lower(products.name) LIKE concat('%%', %(lower_1)s, '%%') ESCAPE '/') OR (lower(products.sku) LIKE concat('%%', %(lower_2)s, '%%') ESCAPE '/')) AND products.price >= %(price_1)s AND products.stock_quantity > %(stock_quantity_1)s AND products.is_active IS true AND categories.is_active IS true ORDER BY products.price DESC, products.id DESC LIMIT %(param_1)s, %(param_2)s
-- parameters: {'lower_1': 'mobile', 'lower_2': 'mobile', 'price_1': Decimal('1000.00'), 'stock_quantity_1': 0, 'param_1': 0, 'param_2': 2}
```

Transaction rolled back: the test database holds none of the rows above.

## Part B: live container, configured database, real Authentication Service

Base URL `http://127.0.0.1:8006`. Read-only, as an anonymous visitor. The result depends on what the configured database holds, so the checks are on consistency: paging fields, page size, and that every product returned is active and matches the filter.

### PASS: search=mobile

`GET /api/products/?search=mobile` as **anonymous**, expected **200**, got **200**

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

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

### PASS: category_id=1

`GET /api/products/?category_id=1` as **anonymous**, expected **200**, got **200**

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

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

### PASS: min_price=1000&max_price=5000

`GET /api/products/?min_price=1000&max_price=5000` as **anonymous**, expected **200**, got **200**

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

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

### PASS: page=1&page_size=10

`GET /api/products/?page=1&page_size=10` as **anonymous**, expected **200**, got **200**

Response:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10,
  "total_pages": 0
}
```

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

### PASS: sort_by=price&sort_order=asc

`GET /api/products/?sort_by=price&sort_order=asc` as **anonymous**, expected **200**, got **200**

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

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

Check, ascending prices: **PASS**. `[]`

### PASS: availability=out_of_stock

`GET /api/products/?availability=out_of_stock` as **anonymous**, expected **200**, got **200**

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

Check, consistent: **PASS**. 0 items, total 0, total_pages 0.

### PASS: page=0

`GET /api/products/?page=0` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "page",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: page=-1

`GET /api/products/?page=-1` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "page",
      "message": "Input should be greater than or equal to 1"
    }
  ]
}
```

### PASS: page_size=101

`GET /api/products/?page_size=101` as **anonymous**, expected **422**, got **422**

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

### PASS: sort_by not allowed

`GET /api/products/?sort_by=id; DROP TABLE products` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "sort_by",
      "message": "Input should be 'name', 'price' or 'created_at'"
    }
  ]
}
```

### PASS: sort_order not allowed

`GET /api/products/?sort_order=up` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "sort_order",
      "message": "Input should be 'asc' or 'desc'"
    }
  ]
}
```

### PASS: availability not allowed

`GET /api/products/?availability=maybe` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "availability",
      "message": "Input should be 'in_stock' or 'out_of_stock'"
    }
  ]
}
```

### PASS: max_price below min_price

`GET /api/products/?min_price=50&max_price=10` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "max_price",
      "message": "max_price must not be lower than min_price"
    }
  ]
}
```

### PASS: Unknown parameter

`GET /api/products/?size=10` as **anonymous**, expected **422**, got **422**

Response:
```json
{
  "detail": "Validation failed",
  "errors": [
    {
      "field": "size",
      "message": "Unknown query parameter"
    }
  ]
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
