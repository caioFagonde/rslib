from __future__ import annotations

import asyncio
import math
from urllib.parse import quote, urljoin, urlsplit

import httpx

from rslib.cache import ResponseCache, canonical_hash
from rslib.catalog import PROVIDERS
from rslib.models import Search


class CatalogError(RuntimeError):
    pass


class STACClient:
    """Async STAC Item Search, bounded pagination, retries, deduplication and TTL cache.

    Cloud filtering is local, so APIs without the optional Query extension work.
    Search caps are explicit: fewer results can mean the page budget was reached.
    """

    def __init__(self, endpoint: str, *, cache: ResponseCache | None = None, transport=None):
        self.endpoint = endpoint.rstrip("/")
        self.cache, self.transport = cache, transport

    def _same_origin(self, url: str) -> None:
        target, root = urlsplit(url), urlsplit(self.endpoint)
        if (target.scheme, target.netloc) != (root.scheme, root.netloc):
            raise CatalogError("Cross-origin STAC pagination is not allowed")

    async def _request(
        self, client: httpx.AsyncClient, method: str, url: str, body: dict | None = None
    ) -> dict:
        self._same_origin(url)
        key = canonical_hash([method, url, body])
        cached = await asyncio.to_thread(self.cache.get, key) if self.cache else None
        if cached is not None:
            return cached
        for attempt in range(4):
            try:
                response = await client.request(
                    method, url, json=body if method == "POST" else None
                )
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    retry = response.headers.get("Retry-After", "")
                    await asyncio.sleep(
                        min(5, float(retry)) if retry.isdigit() else 0.25 * 2**attempt
                    )
                    continue
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise CatalogError("STAC endpoint did not return an object")
                if self.cache:
                    await asyncio.to_thread(self.cache.put, key, result)
                return result
            except httpx.TransportError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.25 * 2**attempt)
        raise CatalogError("STAC request retry budget exhausted")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            transport=self.transport,
            follow_redirects=False,
            headers={"User-Agent": "rslib/0.1 (+Earth-observation research)"},
        )

    async def collections(self) -> list[dict]:
        async with self._client() as client:
            doc = await self._request(client, "GET", self.endpoint + "/collections")
        return doc.get("collections", [])

    async def collection(self, collection: str) -> dict:
        """Read one collection, including its declared license and license links."""
        url = f"{self.endpoint}/collections/{quote(collection, safe='')}"
        async with self._client() as client:
            return await self._request(client, "GET", url)

    async def item(self, collection: str, item_id: str) -> dict:
        url = f"{self.endpoint}/collections/{quote(collection, safe='')}/items/{quote(item_id, safe='')}"
        async with self._client() as client:
            return await self._request(client, "GET", url)

    async def search(self, query: Search) -> dict:
        body = {"bbox": list(query.bbox.bounds), "collections": query.collections, "limit": 100}
        if query.datetime:
            body["datetime"] = query.datetime
        initial = dict(body)
        method, url = "POST", self.endpoint + "/search"
        features, seen_items, seen_pages = [], set(), set()
        examined = rejected = pages = 0
        truncated, reason = False, None
        async with self._client() as client:
            for _ in range(query.max_pages):
                key = canonical_hash([method, url, body])
                if key in seen_pages:
                    truncated, reason = True, "pagination_cycle"
                    break
                seen_pages.add(key)
                doc = await self._request(client, method, url, body)
                pages += 1
                items = doc.get("features")
                if not isinstance(items, list):
                    raise CatalogError("STAC search response is missing features")
                next_link = next((v for v in doc.get("links", []) if v.get("rel") == "next"), None)
                for position, feature in enumerate(items):
                    identity = (feature.get("collection"), feature.get("id"))
                    if identity in seen_items:
                        continue
                    seen_items.add(identity)
                    examined += 1
                    cloud = feature.get("properties", {}).get("eo:cloud_cover")
                    known = (
                        isinstance(cloud, (int, float))
                        and math.isfinite(cloud)
                        and 0 <= cloud <= 100
                    )
                    if query.max_cloud is not None and (not known or cloud > query.max_cloud):
                        rejected += 1
                        continue
                    features.append(feature)
                    if len(features) >= query.max_items:
                        truncated = next_link is not None or position < len(items) - 1
                        reason = "item_limit" if truncated else None
                        break
                if len(features) >= query.max_items or not next_link:
                    break
                method = next_link.get("method", "GET").upper()
                if method not in ("GET", "POST"):
                    raise CatalogError("Unsupported pagination method")
                url = urljoin(url, next_link["href"])
                self._same_origin(url)
                next_body = next_link.get("body", {})
                body = (
                    ({**initial, **next_body} if next_link.get("merge") else next_body)
                    if method == "POST"
                    else None
                )
            else:
                truncated, reason = True, "page_limit"
        features.sort(
            key=lambda f: (
                f.get("properties", {}).get("eo:cloud_cover")
                if isinstance(f.get("properties", {}).get("eo:cloud_cover"), (float, int))
                else 101,
                f.get("id", ""),
            )
        )
        return {
            "type": "FeatureCollection",
            "features": features,
            "links": [],
            "rslib": {
                "provider": query.provider,
                "query": query.model_dump(),
                "pages": pages,
                "examined": examined,
                "cloud_rejected_or_unknown": rejected,
                "returned": len(features),
                "truncated": truncated,
                "stop_reason": reason,
                "ranking": "scene cloud cover ascending within fetched results; not AOI clear coverage",
            },
        }


def client_for(provider: str, cache: ResponseCache | None = None) -> STACClient:
    return STACClient(PROVIDERS[provider], cache=cache)
