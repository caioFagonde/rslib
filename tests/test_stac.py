import asyncio

import httpx
import pytest

from rslib.cache import ResponseCache
from rslib.models import BBox, Search
from rslib.stac import CatalogError, STACClient


def query(**kwargs):
    return Search(bbox=BBox(west=-45, south=-23, east=-44, north=-22), **kwargs)


def item(id, cloud):
    return {"id": id, "collection": "test", "properties": {"eo:cloud_cover": cloud}}


def test_pagination_post_merge_deduplication_cloud_and_cache(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "features": [item("a", 70), item("b", 10)],
                    "links": [
                        {
                            "rel": "next",
                            "href": "./search",
                            "method": "POST",
                            "merge": True,
                            "body": {"token": "abc"},
                        }
                    ],
                },
            )
        assert b'"token":"abc"' in request.content
        assert b'"bbox"' in request.content
        return httpx.Response(
            200, json={"features": [item("b", 10), item("c", 5), item("d", None)], "links": []}
        )

    client = STACClient(
        "https://catalog.test",
        cache=ResponseCache(tmp_path / "cache.sqlite"),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.search(query(max_cloud=20)))
    assert [f["id"] for f in result["features"]] == ["c", "b"]
    assert result["rslib"]["examined"] == 4
    assert result["rslib"]["cloud_rejected_or_unknown"] == 2
    assert not result["rslib"]["truncated"]
    assert asyncio.run(client.search(query(max_cloud=20))) == result
    assert len(requests) == 2


def test_get_pagination_budget_and_no_cloud_filter():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "features": [item(str(request.url), None)],
                "links": [{"rel": "next", "href": "https://catalog.test/search?page=2"}],
            },
        )

    result = asyncio.run(
        STACClient("https://catalog.test", transport=httpx.MockTransport(handler)).search(
            query(max_cloud=None, max_pages=1)
        )
    )
    assert result["rslib"]["returned"] == 1
    assert result["rslib"]["stop_reason"] == "page_limit"


def test_pagination_cycle_stops():
    def handler(request):
        return httpx.Response(
            200, json={"features": [], "links": [{"rel": "next", "href": "/search"}]}
        )

    result = asyncio.run(
        STACClient("https://catalog.test", transport=httpx.MockTransport(handler)).search(query())
    )
    assert result["rslib"]["stop_reason"] == "pagination_cycle"


def test_cross_origin_pagination_is_rejected():
    def handler(request):
        return httpx.Response(
            200,
            json={"features": [], "links": [{"rel": "next", "href": "http://localhost/private"}]},
        )

    with pytest.raises(CatalogError, match="Cross-origin"):
        asyncio.run(
            STACClient("https://catalog.test", transport=httpx.MockTransport(handler)).search(
                query()
            )
        )


def test_item_cap_and_cloud_unknown():
    def handler(request):
        return httpx.Response(
            200, json={"features": [item("a", None), item("b", 0), item("c", 5)], "links": []}
        )

    result = asyncio.run(
        STACClient("https://catalog.test", transport=httpx.MockTransport(handler)).search(
            query(max_items=1)
        )
    )
    assert result["features"][0]["id"] == "b"
    assert result["rslib"]["truncated"]


def test_aoi_dates_validate_early():
    assert (
        query(datetime="2026-06-01/2026-08-01").datetime
        == "2026-06-01T00:00:00Z/2026-08-01T23:59:59.999999Z"
    )
    with pytest.raises(ValueError):
        query(datetime="2026-09-01/2026-01-01")
    with pytest.raises(ValueError):
        BBox(west=170, south=0, east=-170, north=10)
    with pytest.raises(ValueError):
        BBox(west=float("nan"), south=0, east=10, north=10)
