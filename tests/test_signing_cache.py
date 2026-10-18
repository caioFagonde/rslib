"""Container-scoped signing reduces remote requests without persisting credentials."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from rslib import raster


@pytest.fixture(autouse=True)
def empty_tokens():
    raster._SAS_TOKENS.clear()
    yield
    raster._SAS_TOKENS.clear()


def token(number=1, minutes=10):
    return {
        "token": f"sig=memory-only-{number}",
        "msft:expiry": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
    }


def test_shared_container_single_request_thread_safety_expiry_and_invalidation():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=token(len(calls)))

    root = "https://landsateuwest.blob.core.windows.net/landsat-c2/scene/"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            urls = list(
                pool.map(
                    lambda i: raster.sign_planetary_asset(root + f"B{i}.tif", client=client),
                    range(6),
                )
            )
        assert len(calls) == 1 and all(url.endswith("?sig=memory-only-1") for url in urls)
        assert calls[0].endswith("/token/landsateuwest/landsat-c2")
        endpoint = raster._container_endpoint(root)
        raster._SAS_TOKENS[endpoint] = ("old", datetime.now(UTC).timestamp() + 20)
        assert raster.sign_planetary_asset(root + "B7.tif", client=client).endswith("memory-only-2")
        raster.invalidate_planetary_asset(root + "B1.tif")
        assert raster.sign_planetary_asset(root + "B8.tif", client=client).endswith("memory-only-3")
        other = root.replace("/landsat-c2/", "/other-container/")
        raster.sign_planetary_asset(other + "red.tif", client=client)
        assert len(calls) == 4


def test_retry_after_date_and_long_cooldown(monkeypatch):
    delays = []
    monkeypatch.setattr(raster.time, "sleep", delays.append)
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            retry = format_datetime(datetime.now(UTC) + timedelta(seconds=7), usegmt=True)
            return httpx.Response(429, headers={"Retry-After": retry})
        return httpx.Response(200, json=token())

    href = "https://account.blob.core.windows.net/container/red.tif"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        raster.sign_planetary_asset(href, client=client)
    assert len(calls) == 2 and len(delays) == 1 and 5 < delays[0] <= 7
    raster._SAS_TOKENS.clear()
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "120"})
            )
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        raster.sign_planetary_asset(href, client=client)
    assert len(delays) == 1


@pytest.mark.parametrize(
    "document", [token(minutes=-1), {"token": "x"}, {"token": "x", "msft:expiry": "tomorrow"}]
)
def test_invalid_token_not_cached(document):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=document))
    ) as client:
        with pytest.raises(httpx.DecodingError):
            raster.sign_planetary_asset(
                "https://account.blob.core.windows.net/container/a.tif", client=client
            )
    assert not raster._SAS_TOKENS
