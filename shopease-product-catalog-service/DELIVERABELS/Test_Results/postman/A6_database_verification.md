# Database verification, run 794492268

Queried directly in MySQL (shopease_product_catalog_test_db) after the Newman runs and the Swagger UI requests, before the rows were deleted.

Products of run PM794492268:

| id | sku | stock | active | category |
|---|---|---|---|---|
| 3787 | PM794492268-MOB-1 | 4 | False | 3140 PM794492268 Phones |
| 3788 | PM794492268-HIDDEN | 1 | False | 3140 PM794492268 Phones |
| 3789 | PM794492268-DEL-1 | 2 | False | 3140 PM794492268 Phones |
| 3790 | PM794492268-PHN-1 | 12 | True | 3140 PM794492268 Phones |
| 3791 | PM794492268-MOB-2 | 0 | True | 3140 PM794492268 Phones |
| 3792 | PM794492268-LAP-1 | 7 | True | 3141 PM794492268 Laptops |
| 3793 | PM794492268-CONC | 0 | True | 3140 PM794492268 Phones |
| 3794 | PM794492268-SWG-1 | 13 | True | 3141 PM794492268 Laptops |

| Result | Check | Detail |
|---|---|---|
| PASS | Exactly the products the scenarios created | 8 products; refused requests (duplicate SKU, invalid category, negative price, customer, no token) created none |
| PASS | Every product's category exists (foreign key) | LEFT JOIN categories: no NULL |
| PASS | Stock equals the replayed history, for every product | broken: none |
| PASS | History rows per product | CONC 6, DEL-1 1, HIDDEN 1, LAP-1 1, MOB-1 4, MOB-2 0, PHN-1 1, SWG-1 2 |
| PASS | No inventory transaction without its product (whole test database) | 0 orphans |
| PASS | SKUs unique, ignoring case (whole test database) | 0 duplicates |
| PASS | Category names unique, ignoring case (whole test database) | 0 duplicates |
| PASS | No negative stock (whole test database) | 0 rows |
| PASS | Categories of the run | PM794492268 Phones active=False, PM794492268 Laptops active=False, PM794492268 Archive active=False |
| PASS | Foreign keys defined, ON DELETE RESTRICT | inventory_transactions.fk_inventory_transactions_product_id_products -> products (RESTRICT); products.fk_products_category_id_categories -> categories (RESTRICT) |
| PASS | Unique and CHECK constraints present | ck_inventory_transactions_quantity_positive, ck_inventory_transactions_stock_arithmetic, ck_products_discount_price_valid, ck_products_price_non_negative, ck_products_stock_quantity_non_negative, uq_categories_name, uq_products_sku |
