"""FastAPI app: static UI, sheet generation endpoint, and uniform error responses."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from server.config import (
    API_CONFIG_ROUTE,
    API_HEALTH_ROUTE,
    API_SHEET_ROUTE,
    REQUEST_DELAY_SECONDS,
    REQUEST_ID_HEADER,
    REQUEST_ID_LENGTH,
    REQUEST_TIMEOUT_SECONDS,
    STATIC_DIR,
    STATIC_MOUNT_NAME,
    STATIC_MOUNT_PATH,
    USER_AGENT,
    USER_AGENT_HEADER,
)
from server.logging_config import configure_logging, get_request_id, request_id_var
from server.lorcast import CardFetchResult, LorcastClient
from server.models import (
    CardError,
    ClientConfigResponse,
    ErrorResponse,
    HealthResponse,
    SheetRequest,
    SheetResponse,
)
from server.rate_limiter import RateLimiter
from server.sheets import Placeholder, SheetEntry, render_pages_base64

configure_logging()
logger = logging.getLogger(__name__)

HTTP_SCOPE_TYPE = "http"
RESPONSE_START_MESSAGE = "http.response.start"
HEADER_ENCODING = "latin-1"
HEALTH_OK = "ok"
BODY_LOCATION = "body"
VALUE_ERROR_PREFIX = "Value error, "
MS_PER_SECOND = 1000
VALIDATION_FAILED_MESSAGE = "The card list is not valid."
INTERNAL_ERROR_MESSAGE = "Something went wrong while building the sheet. Check the server logs for this request id."


# --- Request id --------------------------------------------------------------


class RequestIdMiddleware:
    """Assign a short id to each request, expose it to logging, and return it as a header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE_TYPE:
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:REQUEST_ID_LENGTH]
        # Not reset afterwards: the 500 handler runs outside this middleware and still needs the id.
        # Each request runs in its own task, so the value cannot leak into another request.
        request_id_var.set(request_id)

        header_name = REQUEST_ID_HEADER.lower().encode(HEADER_ENCODING)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == RESPONSE_START_MESSAGE:
                headers = list(message.get("headers", []))
                if not any(name.lower() == header_name for name, _ in headers):
                    headers.append((header_name, request_id.encode(HEADER_ENCODING)))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


# --- App lifecycle -----------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    http = httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={USER_AGENT_HEADER: USER_AGENT},
        follow_redirects=True,
    )
    app.state.lorcast = LorcastClient(http, RateLimiter(REQUEST_DELAY_SECONDS))
    await app.state.lorcast.load_sets()
    logger.info("Server ready")
    try:
        yield
    finally:
        await http.aclose()
        logger.info("Server stopped")


app = FastAPI(title="Lorcana Proxy Sheet Generator", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)


def get_lorcast_client(request: Request) -> LorcastClient:
    client: LorcastClient = request.app.state.lorcast
    return client


LorcastDependency = Annotated[LorcastClient, Depends(get_lorcast_client)]


# --- Error handlers ----------------------------------------------------------


def _error_response(status: HTTPStatus, message: str, details: list[str] | None = None) -> JSONResponse:
    request_id = get_request_id()
    body = ErrorResponse(request_id=request_id, message=message, details=details or [])
    return JSONResponse(
        status_code=status,
        content=body.model_dump(),
        headers={REQUEST_ID_HEADER: request_id},
    )


def _format_location(location: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for part in location:
        if part == BODY_LOCATION:
            continue
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}" if parts else str(part))
    return "".join(parts)


def format_validation_errors(exc: RequestValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        message = str(error.get("msg", "")).removeprefix(VALUE_ERROR_PREFIX)
        location = _format_location(tuple(error.get("loc", ())))
        messages.append(f"{location}: {message}" if location else message)
    return messages


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = format_validation_errors(exc)
    logger.warning("Rejected invalid sheet request: %s", "; ".join(details))
    return _error_response(HTTPStatus.UNPROCESSABLE_ENTITY, VALIDATION_FAILED_MESSAGE, details)


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.info("HTTP %d for %s %s", exc.status_code, request.method, request.url.path)
    return _error_response(HTTPStatus(exc.status_code), str(exc.detail))


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error for %s %s", request.method, request.url.path, exc_info=exc)
    return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR, INTERNAL_ERROR_MESSAGE)


# --- Routes ------------------------------------------------------------------


def build_sheet_entries(results: list[CardFetchResult]) -> tuple[list[SheetEntry], list[CardError], int]:
    """Turn fetch results into sheet entries. Returns (entries, errors, successful card count)."""
    entries: list[SheetEntry] = []
    errors: list[CardError] = []
    card_count = 0
    for result in results:
        if result.fetched is not None:
            entries.append(SheetEntry(content=result.fetched.image, quantity=result.request.quantity))
            card_count += result.request.quantity
        elif result.error is not None:
            errors.append(result.error)
            placeholder = Placeholder(result.error.set_code, result.error.number, result.error.reason)
            entries.append(SheetEntry(content=placeholder, quantity=result.request.quantity))
    return entries, errors, card_count


@app.post(API_SHEET_ROUTE, response_model=SheetResponse)
async def create_sheet(sheet_request: SheetRequest, lorcast: LorcastDependency) -> SheetResponse:
    started = time.perf_counter()
    cards = sheet_request.merged_cards()
    logger.info(
        "Sheet requested: %d entries (%d unique), %d cards",
        len(sheet_request.cards),
        len(cards),
        sheet_request.total_cards,
    )

    if not lorcast.sets_loaded:
        await lorcast.load_sets()

    results = await lorcast.fetch_all(cards)
    entries, errors, card_count = build_sheet_entries(results)

    pages = await asyncio.to_thread(render_pages_base64, entries) if card_count else []

    elapsed_ms = (time.perf_counter() - started) * MS_PER_SECOND
    logger.info(
        "Sheet completed: %d page(s), %d card(s), %d error(s) in %.0f ms",
        len(pages),
        card_count,
        len(errors),
        elapsed_ms,
    )
    return SheetResponse(
        request_id=get_request_id(),
        pages=pages,
        card_count=card_count,
        page_count=len(pages),
        errors=errors,
    )


@app.get(API_HEALTH_ROUTE, response_model=HealthResponse)
async def health(lorcast: LorcastDependency) -> HealthResponse:
    return HealthResponse(status=HEALTH_OK, sets_loaded=lorcast.sets_loaded, set_count=lorcast.set_count)


@app.get(API_CONFIG_ROUTE, response_model=ClientConfigResponse)
async def client_config() -> ClientConfigResponse:
    return ClientConfigResponse()


app.mount(STATIC_MOUNT_PATH, StaticFiles(directory=STATIC_DIR, html=True), name=STATIC_MOUNT_NAME)
