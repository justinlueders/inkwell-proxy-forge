import base64
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from server.config import API_CONFIG_ROUTE, API_HEALTH_ROUTE, API_SHEET_ROUTE, REQUEST_ID_HEADER
from server.lorcast import LorcastClient
from server.main import app, get_lorcast_client
from tests.conftest import Handler, default_handler

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


def test_index_is_served(api: TestClient) -> None:
    response = api.get("/")
    assert response.status_code == 200
    assert "Inkwell Proxy Forge" in response.text
