from __future__ import annotations

import json


class PostGISCatalog:
    """Optional persistent, spatially indexed STAC metadata. No raster blobs in PostgreSQL."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def ingest(self, features: list[dict]) -> int:
        import psycopg

        with psycopg.connect(self.dsn) as db, db.cursor() as cur:
            for feature in features:
                if feature.get("geometry") is None:
                    raise ValueError("Cannot index a feature without geometry")
                cur.execute(
                    """
                    INSERT INTO rslib.items(collection, id, captured_at, cloud_cover, geom, document)
                    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s::jsonb)
                    ON CONFLICT (collection,id) DO UPDATE SET captured_at=EXCLUDED.captured_at,
                    cloud_cover=EXCLUDED.cloud_cover, geom=EXCLUDED.geom, document=EXCLUDED.document
                    """,
                    (
                        feature.get("collection", "unknown"),
                        feature["id"],
                        feature.get("properties", {}).get("datetime"),
                        feature.get("properties", {}).get("eo:cloud_cover"),
                        json.dumps(feature["geometry"]),
                        json.dumps(feature),
                    ),
                )
        return len(features)

    def search(self, bbox: tuple[float, float, float, float], limit: int = 100) -> list[dict]:
        import psycopg

        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be 1–1000")
        with psycopg.connect(self.dsn) as db, db.cursor() as cur:
            cur.execute(
                """SELECT document FROM rslib.items
                WHERE ST_Intersects(geom, ST_MakeEnvelope(%s,%s,%s,%s,4326))
                ORDER BY captured_at DESC NULLS LAST LIMIT %s""",
                (*bbox, limit),
            )
            return [row[0] for row in cur.fetchall()]
