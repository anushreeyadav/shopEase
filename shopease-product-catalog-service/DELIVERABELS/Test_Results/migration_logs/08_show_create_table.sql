-- SHOW CREATE TABLE output from MySQL 8.4.11, database shopease_product_catalog_db
-- Captured 2026-11-12 05:28:57 UTC as catalog_svc. Evidence only: tables are created by Alembic, not by this file.

CREATE TABLE `categories` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `description` text,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_categories_name` (`name`),
  CONSTRAINT `ck_categories_name_not_blank` CHECK ((trim(`name`) <> _utf8mb4''))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

CREATE TABLE `products` (
  `id` int NOT NULL AUTO_INCREMENT,
  `category_id` int NOT NULL,
  `name` varchar(200) NOT NULL,
  `description` text,
  `sku` varchar(64) NOT NULL,
  `price` decimal(10,2) NOT NULL,
  `discount_price` decimal(10,2) DEFAULT NULL,
  `stock_quantity` int NOT NULL DEFAULT '0',
  `image_url` varchar(500) DEFAULT NULL,
  `brand` varchar(100) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_products_sku` (`sku`),
  KEY `ix_products_category_id` (`category_id`),
  KEY `ix_products_name` (`name`),
  CONSTRAINT `fk_products_category_id_categories` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_products_discount_price_valid` CHECK (((`discount_price` is null) or ((`discount_price` >= 0) and (`discount_price` < `price`)))),
  CONSTRAINT `ck_products_name_not_blank` CHECK ((trim(`name`) <> _utf8mb4'')),
  CONSTRAINT `ck_products_price_non_negative` CHECK ((`price` >= 0)),
  CONSTRAINT `ck_products_sku_not_blank` CHECK ((trim(`sku`) <> _utf8mb4'')),
  CONSTRAINT `ck_products_stock_quantity_non_negative` CHECK ((`stock_quantity` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

CREATE TABLE `inventory_transactions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `product_id` int NOT NULL,
  `transaction_type` varchar(3) NOT NULL,
  `quantity` int NOT NULL,
  `previous_stock` int NOT NULL,
  `updated_stock` int NOT NULL,
  `remarks` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `ix_inventory_transactions_product_id_created_at` (`product_id`,`created_at`),
  CONSTRAINT `fk_inventory_transactions_product_id_products` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `ck_inventory_transactions_previous_stock_non_negative` CHECK ((`previous_stock` >= 0)),
  CONSTRAINT `ck_inventory_transactions_quantity_positive` CHECK ((`quantity` > 0)),
  CONSTRAINT `ck_inventory_transactions_stock_arithmetic` CHECK ((((`transaction_type` = _utf8mb4'IN') and (`updated_stock` = (`previous_stock` + `quantity`))) or ((`transaction_type` = _utf8mb4'OUT') and (`updated_stock` = (`previous_stock` - `quantity`))))),
  CONSTRAINT `ck_inventory_transactions_transaction_type` CHECK ((`transaction_type` in (_utf8mb4'IN',_utf8mb4'OUT'))),
  CONSTRAINT `ck_inventory_transactions_updated_stock_non_negative` CHECK ((`updated_stock` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

