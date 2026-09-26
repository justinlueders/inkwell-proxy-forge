from collections.abc import Callable

import httpx
import pytest

from server.config import MAX_RETRIES, MAX_RETRY_AFTER_SECONDS, RETRY_BACKOFF_SECONDS
from server.errors import (
    CardNotFoundError,
    ImageDecodeError,
    ImageDownloadError,
    ImageUnavailableError,
    InvalidResponseError,
    UnknownSetError,
    UpstreamStatusError,
    UpstreamUnavailableError,
)
from server.lorcast import LorcastClient, parse_retry_after
from server.models import CardErrorReason, CardRequest
from tests.conftest import IMAGE_HOST, SETS_PAYLOAD, Handler, card_payload, default_handler, make_image_bytes

MakeClient = Callable[[Handler], LorcastClient]


async def test_fetch_card_with_image_success(make_client: MakeClient) -> None:
    client = make_client(default_handler)
    fetched = await client.fetch_card_with_image(CardRequest(set_code="10", number="7"))
    assert fetched.card.name == "Eilonwy"
    assert fetched.image.size == (674, 940)


async def test_set_codes_resolve_case_insensitively(make_client: MakeClient) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return default_handler(request)

    client = make_client(handler)
    assert await client.load_sets()
    await client.fetch_card("p1", "1")
    assert seen[-1].endswith("/cards/P1/1")


async def test_unknown_set_makes_no_card_request(make_client: MakeClient) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return default_handler(request)

    client = make_client(handler)
    await client.load_sets()
    with pytest.raises(UnknownSetError):
        await client.fetch_card("ZZZ", "1")
    assert not any("/cards/" in path for path in seen)


async def test_set_list_failure_falls_back_to_pass_through(make_client: MakeClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sets"):
            return httpx.Response(500)
        return default_handler(request)

    client = make_client(handler)
    assert await client.load_sets() is False
    assert not client.sets_loaded
    assert client.resolve_set_code("zzz") == "zzz"


async def test_path_values_are_encoded(make_client: MakeClient) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(404)

    client = make_client(handler)
    with pytest.raises(CardNotFoundError):
        await client.fetch_card("10", "1/../x?y#z")
    assert seen[-1].endswith("/cards/10/1%2F..%2Fx%3Fy%23z")


async def test_404_maps_to_not_found(make_client: MakeClient) -> None:
    client = make_client(default_handler)
    with pytest.raises(CardNotFoundError) as info:
        await client.fetch_card("10", "9999")
    assert info.value.reason is CardErrorReason.NOT_FOUND


async def test_429_with_retry_after_retries_then_succeeds(make_client: MakeClient, sleeps: list[float]) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/cards/" in request.url.path:
            calls["count"] += 1
            if calls["count"] == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
        return default_handler(request)

    client = make_client(handler)
    card = await client.fetch_card("10", "7")
    assert card.collector_number == "7"
    assert calls["count"] == 2
    assert sleeps == [2.0]


async def test_persistent_5xx_maps_to_upstream_unavailable(make_client: MakeClient, sleeps: list[float]) -> None:
    client = make_client(lambda request: httpx.Response(503))
    with pytest.raises(UpstreamUnavailableError):
        await client.fetch_card("10", "7")
    assert sleeps == [RETRY_BACKOFF_SECONDS * (2**attempt) for attempt in range(MAX_RETRIES)]


async def test_timeouts_are_retried(make_client: MakeClient) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return default_handler(request)

    client = make_client(handler)
    await client.fetch_card("10", "7")
    assert calls["count"] == 2


async def test_non_retryable_4xx_is_not_retried(make_client: MakeClient, sleeps: list[float]) -> None:
    client = make_client(lambda request: httpx.Response(400))
    with pytest.raises(UpstreamStatusError):
        await client.fetch_card("10", "7")
    assert sleeps == []


async def test_bad_json_maps_to_invalid_response(make_client: MakeClient) -> None:
    client = make_client(lambda request: httpx.Response(200, content=b"not json"))
    with pytest.raises(InvalidResponseError) as info:
        await client.fetch_card("10", "7")
    assert info.value.reason is CardErrorReason.INVALID_RESPONSE


async def test_missing_large_image_maps_to_no_image(make_client: MakeClient) -> None:
    client = make_client(lambda request: httpx.Response(200, json=card_payload(image=None)))
    with pytest.raises(ImageUnavailableError) as info:
        await client.fetch_card_with_image(CardRequest(set_code="10", number="7"))
    assert info.value.reason is CardErrorReason.NO_IMAGE


async def test_corrupt_image_maps_to_decode_failed(make_client: MakeClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(IMAGE_HOST):
            return httpx.Response(200, content=b"definitely not an image")
        return default_handler(request)

    client = make_client(handler)
    with pytest.raises(ImageDecodeError) as info:
        await client.fetch_card_with_image(CardRequest(set_code="10", number="7"))
    assert info.value.reason is CardErrorReason.IMAGE_DECODE_FAILED


async def test_oversized_image_maps_to_download_failed(make_client: MakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("server.lorcast.MAX_IMAGE_BYTES", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(IMAGE_HOST):
            return httpx.Response(200, content=make_image_bytes())
        return default_handler(request)

    client = make_client(handler)
    with pytest.raises(ImageDownloadError):
        await client.fetch_card_with_image(CardRequest(set_code="10", number="7"))


async def test_fetch_all_isolates_failures(make_client: MakeClient) -> None:
    client = make_client(default_handler)
    await client.load_sets()
    results = await client.fetch_all(
        [
            CardRequest(set_code="10", number="7"),
            CardRequest(set_code="10", number="9999"),
            CardRequest(set_code="ZZZ", number="1"),
            CardRequest(set_code="p1", number="1"),
        ]
    )
    assert [r.error.reason if r.error else None for r in results] == [
        None,
        CardErrorReason.NOT_FOUND,
        CardErrorReason.UNKNOWN_SET,
        None,
    ]


async def test_fetch_all_contains_unexpected_errors(make_client: MakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(default_handler)

    async def explode(_: CardRequest) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "fetch_card_with_image", explode)
    [result] = await client.fetch_all([CardRequest(set_code="10", number="7")])
    assert result.error is not None
    assert result.error.reason is CardErrorReason.UPSTREAM_UNAVAILABLE


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("3", 3.0),
        ("-5", 0.0),
        ("9999", MAX_RETRY_AFTER_SECONDS),
        ("garbage", None),
    ],
)
def test_parse_retry_after(header: str | None, expected: float | None) -> None:
    assert parse_retry_after(header) == expected


def test_sets_payload_fixture_is_valid() -> None:
    assert {item["code"] for item in SETS_PAYLOAD["results"]} == {"10", "P1"}
