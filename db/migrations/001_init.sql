-- RadarOfertas — esquema inicial (Supabase / PostgreSQL)
-- Costo Real GT (Amazon):
--   (precio_usd * tipo_cambio_gtq)
-- + (peso_libras * tarifa_lb_usd * tipo_cambio_gtq)
-- + DAI% sobre (CIF = producto_gtq + flete_gtq)
-- + IVA 12% sobre (CIF + DAI)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- tiendas
-- ---------------------------------------------------------------------------
CREATE TABLE tiendas (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                    TEXT NOT NULL UNIQUE,
    nombre                  TEXT NOT NULL,
    pais                    CHAR(2) NOT NULL CHECK (pais IN ('GT', 'US')),
    tipo                    TEXT NOT NULL CHECK (tipo IN ('local', 'amazon', 'propia')),
    url_base                TEXT NOT NULL,
    selector_config         JSONB NOT NULL DEFAULT '{}'::jsonb,
    envio_gratis_default    BOOLEAN NOT NULL DEFAULT FALSE,
    tarifa_envio_local_gtq  NUMERIC(10, 2) NOT NULL DEFAULT 35.00,
    moneda_nativa           CHAR(3) NOT NULL DEFAULT 'GTQ',
    activo                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- categorias
-- ---------------------------------------------------------------------------
CREATE TABLE categorias (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL UNIQUE,
    nombre          TEXT NOT NULL,
    parent_id       UUID REFERENCES categorias (id) ON DELETE SET NULL,
    -- DAI arancelario SAT GT (fracción simplificada por vertical)
    dai_porcentaje  NUMERIC(5, 2) NOT NULL DEFAULT 0.00
                        CHECK (dai_porcentaje >= 0 AND dai_porcentaje <= 15),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- productos
-- ---------------------------------------------------------------------------
CREATE TABLE productos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku_interno         TEXT UNIQUE,
    gtin                TEXT,
    asin                TEXT UNIQUE,
    nombre              TEXT NOT NULL,
    marca               TEXT,
    modelo              TEXT,
    categoria_id        UUID NOT NULL REFERENCES categorias (id),
    peso_libras         NUMERIC(8, 3) NOT NULL DEFAULT 1.000
                            CHECK (peso_libras > 0),
    imagen_url          TEXT,
    url_canonica        TEXT,
    -- e-shop inventario propio
    es_stock_propio     BOOLEAN NOT NULL DEFAULT FALSE,
    stock               INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    precio_venta_gtq    NUMERIC(12, 2),
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_productos_categoria ON productos (categoria_id);
CREATE INDEX idx_productos_marca ON productos (marca);
CREATE INDEX idx_productos_nombre_trgm ON productos USING gin (nombre gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- historial_precios  (snapshot por scrape)
-- ---------------------------------------------------------------------------
CREATE TABLE historial_precios (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    producto_id         UUID NOT NULL REFERENCES productos (id) ON DELETE CASCADE,
    tienda_id           UUID NOT NULL REFERENCES tiendas (id) ON DELETE CASCADE,
    precio_usd          NUMERIC(12, 2),
    precio_nativo       NUMERIC(12, 2) NOT NULL,
    moneda              CHAR(3) NOT NULL,
    envio_gratis        BOOLEAN NOT NULL DEFAULT FALSE,
    costo_envio_gtq     NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    -- Costo Real Puesto en GT (solo relevante para amazon; local = nativo + envío)
    costo_real_gtq      NUMERIC(12, 2) NOT NULL,
    url_oferta          TEXT NOT NULL,
    disponibilidad      TEXT NOT NULL DEFAULT 'unknown'
                            CHECK (disponibilidad IN ('in_stock', 'out_of_stock', 'preorder', 'unknown')),
    scraped_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_hp_producto_tiempo ON historial_precios (producto_id, scraped_at DESC);
CREATE INDEX idx_hp_tienda_tiempo ON historial_precios (tienda_id, scraped_at DESC);
CREATE INDEX idx_hp_costo_real ON historial_precios (producto_id, costo_real_gtq);

-- última oferta por (producto, tienda) — consulta de comparador
CREATE UNIQUE INDEX uq_hp_latest_slot ON historial_precios (producto_id, tienda_id, scraped_at);

-- ---------------------------------------------------------------------------
-- costos_courier  (vigencias tipo de cambio + tarifa lb + IVA)
-- ---------------------------------------------------------------------------
CREATE TABLE costos_courier (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre              TEXT NOT NULL,
    tarifa_lb_usd       NUMERIC(8, 4) NOT NULL DEFAULT 4.0000,
    iva_porcentaje      NUMERIC(5, 2) NOT NULL DEFAULT 12.00,
    tipo_cambio_gtq     NUMERIC(10, 4) NOT NULL,
    vigente_desde       DATE NOT NULL DEFAULT CURRENT_DATE,
    vigente_hasta       DATE,
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    notas               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_vigencia CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
);

CREATE INDEX idx_courier_vigente ON costos_courier (activo, vigente_desde DESC);

-- ---------------------------------------------------------------------------
-- seeds mínimos
-- ---------------------------------------------------------------------------
INSERT INTO tiendas (slug, nombre, pais, tipo, url_base, envio_gratis_default, tarifa_envio_local_gtq, moneda_nativa) VALUES
    ('kemik',       'Kemik',        'GT', 'local',  'https://kemikgt.com',          FALSE, 35.00, 'GTQ'),
    ('pacifiko',    'Pacifiko',     'GT', 'local',  'https://www.pacifiko.com',     FALSE, 35.00, 'GTQ'),
    ('tiendas-max', 'Tiendas Max',  'GT', 'local',  'https://www.tiendasmax.com',   FALSE, 35.00, 'GTQ'),
    ('tecnofacil',  'Tecnofácil',   'GT', 'local',  'https://www.tecnofacil.com.gt',FALSE, 35.00, 'GTQ'),
    ('elektra',     'Elektra',      'GT', 'local',  'https://www.elektra.com.gt',    FALSE, 35.00, 'GTQ'),
    ('cemaco',      'Cemaco',       'GT', 'local',  'https://www.cemaco.com',        FALSE, 35.00, 'GTQ'),
    ('epa',         'EPA',          'GT', 'local',  'https://www.epa.com.gt',        FALSE, 35.00, 'GTQ'),
    ('novex',       'Novex',        'GT', 'local',  'https://www.novex.com.gt',      FALSE, 35.00, 'GTQ'),
    ('amazon-us',   'Amazon EE.UU.','US', 'amazon', 'https://www.amazon.com',        TRUE,   0.00, 'USD'),
    ('radar-eshop', 'RadarOfertas', 'GT', 'propia', '/',                             TRUE,   0.00, 'GTQ');

INSERT INTO categorias (slug, nombre, dai_porcentaje) VALUES
    ('tecnologia',   'Tecnología',   5.00),
    ('herramientas', 'Herramientas', 10.00),
    ('linea-blanca', 'Línea Blanca', 15.00);

INSERT INTO costos_courier (nombre, tarifa_lb_usd, iva_porcentaje, tipo_cambio_gtq, activo)
VALUES ('PO Box default', 4.0000, 12.00, 7.7500, TRUE);

-- ---------------------------------------------------------------------------
-- vista de comparación (último scrape por producto+tienda)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_comparacion_actual AS
SELECT DISTINCT ON (hp.producto_id, hp.tienda_id)
    p.id AS producto_id,
    p.nombre,
    p.marca,
    p.modelo,
    p.peso_libras,
    c.slug AS categoria,
    c.dai_porcentaje,
    t.slug AS tienda,
    t.tipo AS tipo_tienda,
    hp.precio_nativo,
    hp.moneda,
    hp.envio_gratis,
    hp.costo_envio_gtq,
    hp.costo_real_gtq,
    hp.disponibilidad,
    hp.url_oferta,
    hp.scraped_at
FROM historial_precios hp
JOIN productos p ON p.id = hp.producto_id
JOIN tiendas t ON t.id = hp.tienda_id
JOIN categorias c ON c.id = p.categoria_id
WHERE p.activo AND t.activo
ORDER BY hp.producto_id, hp.tienda_id, hp.scraped_at DESC;
