CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS rslib;
CREATE TABLE IF NOT EXISTS rslib.items (
    collection text NOT NULL,
    id text NOT NULL,
    captured_at timestamptz,
    cloud_cover double precision CHECK (cloud_cover BETWEEN 0 AND 100),
    geom geometry(Geometry, 4326) NOT NULL,
    document jsonb NOT NULL,
    PRIMARY KEY (collection, id)
);
CREATE INDEX IF NOT EXISTS items_geom_gix ON rslib.items USING gist (geom);
CREATE INDEX IF NOT EXISTS items_captured_idx ON rslib.items (captured_at DESC);
CREATE INDEX IF NOT EXISTS items_document_idx ON rslib.items USING gin (document jsonb_path_ops);
