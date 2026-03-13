-- Migration 001: Create product_inventory table
-- size is '' (empty string) for products with no size variant
-- size is 'XL', '2XL', etc. for products with size variants

CREATE TABLE IF NOT EXISTS product_inventory (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    product_id    VARCHAR(100) NOT NULL,
    size          VARCHAR(50)  NOT NULL DEFAULT '',
    quantity      INT          NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_product_size (product_id, size)
);

-- -------------------------------------------------------
-- Seed initial inventory
-- NOTE: product_id values must match the productId values
--       used in the frontend cart items.
--       Update these IDs to match your frontend if needed.
-- -------------------------------------------------------

INSERT INTO product_inventory (product_id, size, quantity) VALUES
    ('shirt', 'XL',  1),
    ('shirt', '2XL', 2),
    ('shirt', 'L',   2),
    ('shirt', 'M',   2),
    ('journal',   '', 10),
    ('wristband', '', 30)
ON DUPLICATE KEY UPDATE quantity = VALUES(quantity);
