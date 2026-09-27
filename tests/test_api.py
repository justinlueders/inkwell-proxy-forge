# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import base64
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from server.config import (
    API_CARD_ROUTE,
    API_CONFIG_ROUTE,
    API_HEALTH_ROUTE,
    API_IMPORT_ROUTE,
    API_SHEET_ROUTE,
    MAX_IDENTIFIER_LENGTH,
    MAX_IMPORT_LINES,
    MAX_IMPORT_TEXT_LENGTH,
    REQUEST_ID_HEADER,
)
from server.lorcast import LorcastClient
from server.main import app, get_lorcast_client
from tests.conftest import Handler, default_handler, named_card_payload, search_response

JPEG_MAGIC = b"\xff\xd8"


@pytest.fixture
def api(make_client: Callable[[Handler], LorcastClient]) -> Iterator[TestClient]:
    lorcast = make_client(default_handler)
    app.dependency_overrides[get_lorcast_client] = lambda: lorcast
    # Not used as a context manager, so the real lifespan (which calls Lorcast) does not run.
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def test_sheet_with_good_cards_and_errors(api: TestClient) -> None:
    response = api.post(
        API_SHEET_ROUTE,
        json={
            "cards": [
                {"set_code": "010", "number": "007", "quantity": 8},
                {"set_code": "10", "number": "9999", "quantity": 1},
                {"set_code": "ZZZ", "number": "1", "quantity": 1},
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["card_count"] == 8
    assert data["page_count"] == len(data["pages"]) == 2
    assert [error["reason"] for error in data["errors"]] == ["NOT_FOUND", "UNKNOWN_SET"]
    assert base64.b64decode(data["pages"][0]).startswith(JPEG_MAGIC)
    assert response.headers[REQUEST_ID_HEADER] == data["request_id"]


def test_all_cards_failing_returns_no_pages(api: TestClient) -> None:
    response = api.post(API_SHEET_ROUTE, json={"cards": [{"set_code": "10", "number": "9999"}]})
    assert response.status_code == 200
    data = response.json()
    assert data["pages"] == []
    assert data["page_count"] == 0
    assert len(data["errors"]) == 1


def test_validation_error_uses_error_response_shape(api: TestClient) -> None:
    response = api.post(API_SHEET_ROUTE, json={"cards": [{"set_code": "", "number": "1", "quantity": 0}]})
    assert response.status_code == 422
    data = response.json()
    assert set(data) == {"request_id", "message", "details"}
    assert any(detail.startswith("cards[0].quantity") for detail in data["details"])
    assert response.headers[REQUEST_ID_HEADER] == data["request_id"]


def test_empty_list_is_rejected(api: TestClient) -> None:
    assert api.post(API_SHEET_ROUTE, json={"cards": []}).status_code == 422


def test_unexpected_error_returns_generic_500(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> None:
        raise RuntimeError("secret internals")

    monkeypatch.setattr("server.main.build_sheet_entries", explode)
    response = api.post(API_SHEET_ROUTE, json={"cards": [{"set_code": "10", "number": "7"}]})
    assert response.status_code == 500
    data = response.json()
    assert "secret" not in data["message"]
    assert data["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert data["request_id"] != "-"


def test_config_and_health(api: TestClient) -> None:
    config = api.get(API_CONFIG_ROUTE).json()
    assert config["cards_per_page"] == 9
    health = api.get(API_HEALTH_ROUTE).json()
    assert health["status"] == "ok"


SEARCHABLE_CARDS = {
    "hercules": named_card_payload("Hercules", "Spectral Demigod", "11", "117"),
    "dragon fire": named_card_payload("Dragon Fire", None, "1", "130"),
}


def search_handler(request: httpx.Request) -> httpx.Response:
    query = request.url.params.get("q", "").casefold()
    matches = [card for key, card in SEARCHABLE_CARDS.items() if f'"{key}"' in query]
    return search_response(*matches)


@pytest.fixture
def import_api(make_client: Callable[[Handler], LorcastClient]) -> Iterator[TestClient]:
    lorcast = make_client(search_handler)
    app.dependency_overrides[get_lorcast_client] = lambda: lorcast
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


def test_import_resolves_cards_and_reports_issues_in_line_order(import_api: TestClient) -> None:
    text = "4 Hercules - Spectral Demigod\nnot a line\n2 Dragon Fire\n1 Missing Card\n1 dragon fire"
    response = import_api.post(API_IMPORT_ROUTE, json={"text": text})
    assert response.status_code == 200
    data = response.json()
    assert [(card["set_code"], card["number"], card["quantity"]) for card in data["cards"]] == [
        ("11", "117", 4),
        ("1", "130", 3),
    ]
    assert data["cards"][0]["name"] == "Hercules - Spectral Demigod"
    assert data["cards"][0]["inks"] == ["Amber"]
    assert [(issue["line_number"], issue["reason"]) for issue in data["issues"]] == [
        (2, "PARSE_ERROR"),
        (4, "NOT_FOUND"),
    ]
    assert data["issues"][0]["line"] == "not a line"
    assert response.headers[REQUEST_ID_HEADER] == data["request_id"]


@pytest.mark.parametrize(
    "text",
    ["", "   \n\n", "1 Dragon Fire\n" * (MAX_IMPORT_LINES + 1), "x" * (MAX_IMPORT_TEXT_LENGTH + 1)],
)
def test_import_rejects_empty_or_oversized_text(import_api: TestClient, text: str) -> None:
    response = import_api.post(API_IMPORT_ROUTE, json={"text": text})
    assert response.status_code == 422
    assert set(response.json()) == {"request_id", "message", "details"}


def test_import_upstream_outage_is_reported_per_line(make_client: Callable[[Handler], LorcastClient]) -> None:
    lorcast = make_client(lambda _: httpx.Response(503))
    app.dependency_overrides[get_lorcast_client] = lambda: lorcast
    try:
        response = TestClient(app, raise_server_exceptions=False).post(API_IMPORT_ROUTE, json={"text": "1 Dragon Fire"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["cards"] == []
    assert response.json()["issues"][0]["reason"] == "UPSTREAM_UNAVAILABLE"


def test_card_info_returns_name_and_inks(api: TestClient) -> None:
    response = api.get(API_CARD_ROUTE, params={"set_code": "p1", "number": "007"})
    assert response.status_code == 200
    data = response.json()
    assert (data["set_code"], data["number"]) == ("P1", "7")
    assert data["name"] == "Eilonwy - Princess of Llyr"
    assert data["inks"] == ["Amber"]
    assert response.headers[REQUEST_ID_HEADER] == data["request_id"]


@pytest.mark.parametrize("params", [{"set_code": "10", "number": "9999"}, {"set_code": "ZZZ", "number": "1"}])
def test_card_info_unknown_card_is_404(api: TestClient, params: dict[str, str]) -> None:
    response = api.get(API_CARD_ROUTE, params=params)
    assert response.status_code == 404
    assert set(response.json()) == {"request_id", "message", "details"}


@pytest.mark.parametrize(
    "params",
    [{"set_code": "10"}, {"set_code": " ", "number": "1"}, {"set_code": "10", "number": "1" * (MAX_IDENTIFIER_LENGTH + 1)}],
)
def test_card_info_rejects_bad_identifiers(api: TestClient, params: dict[str, str]) -> None:
    assert api.get(API_CARD_ROUTE, params=params).status_code == 422


def test_card_info_upstream_outage_is_502(make_client: Callable[[Handler], LorcastClient]) -> None:
    lorcast = make_client(lambda _: httpx.Response(503))
    app.dependency_overrides[get_lorcast_client] = lambda: lorcast
    try:
        response = TestClient(app, raise_server_exceptions=False).get(API_CARD_ROUTE, params={"set_code": "10", "number": "1"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502


def test_config_exposes_import_limits(api: TestClient) -> None:
    config = api.get(API_CONFIG_ROUTE).json()
    assert config["max_import_lines"] == MAX_IMPORT_LINES
    assert config["max_import_text_length"] == MAX_IMPORT_TEXT_LENGTH


def test_index_is_served(api: TestClient) -> None:
    response = api.get("/")
    assert response.status_code == 200
    assert "Inkwell Proxy Forge" in response.text
