"""Client for the Lorcast API: set lookup, rate-limited fetches, retries, and typed failures."""

import asyncio
import io
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from urllib.parse import quote

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from server.config import (
    CARD_ENDPOINT,
    EXACT_NAME_QUERY,
    FUZZY_TERM_QUERY,
    NAME_VERSION_SEPARATOR,
    SEARCH_ENDPOINT,
    SEARCH_QUERY_PARAM,
    VERSION_QUERY,
    HTTP_SERVER_ERROR_MAX,
    HTTP_SERVER_ERROR_MIN,
    LORCAST_API_BASE,
    MAX_IMAGE_BYTES,
    MAX_JSON_BYTES,
    MAX_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    RETRY_BACKOFF_SECONDS,
    SETS_ENDPOINT,
)
from server.errors import (
    CardNotFoundError,
    ImageDecodeError,
    ImageDownloadError,
    ImageUnavailableError,
    InvalidResponseError,
    LorcastError,
    ResponseTooLargeError,
    UnknownSetError,
    UpstreamStatusError,
    UpstreamUnavailableError,
)
from server.models import CardError, CardErrorReason, CardRequest, ImageSize, LorcastCard, SetsResponse
from server.normalization import card_name_key, normalize_card_text, set_code_key
from server.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], Awaitable[None]]

RETRY_AFTER_HEADER = "Retry-After"
CONTENT_LENGTH_HEADER = "Content-Length"
SEARCH_RESULTS_KEY = "results"
MS_PER_SECOND = 1000
_PATH_SAFE_CHARS = ""


@dataclass(frozen=True)
class FetchedCard:
    card: LorcastCard
    image: Image.Image


@dataclass(frozen=True)
class CardFetchResult:
    request: CardRequest
    fetched: FetchedCard | None = None
    error: CardError | None = None


@dataclass(frozen=True)
class _RetrySignal:
    reason: str
    retry_after_seconds: float | None = None


def to_card_error(request: CardRequest, error: LorcastError) -> CardError:
    return CardError(set_code=request.set_code, number=request.number, reason=error.reason, detail=error.detail)


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP date) into seconds, capped at MAX_RETRY_AFTER_SECONDS."""
    if not value:
        return None
    value = value.strip()
    seconds: float | None
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            logger.warning("Ignoring unparseable %s header: %r", RETRY_AFTER_HEADER, value)
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = (retry_at - (now or datetime.now(UTC))).total_seconds()
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


def build_exact_query(name: str, version: str | None) -> str:
    query = EXACT_NAME_QUERY.format(name=normalize_card_text(name))
    if version:
        query = f"{query} {VERSION_QUERY.format(version=normalize_card_text(version))}"
    return query


def _text_key(text: str) -> str:
    return normalize_card_text(text).casefold()


def _full_name_key(card: LorcastCard) -> str:
    full_name = f"{card.name}{NAME_VERSION_SEPARATOR}{card.version}" if card.version else card.name
    return _text_key(full_name)


def _is_transient_status(status_code: int) -> bool:
    return status_code == HTTPStatus.TOO_MANY_REQUESTS or HTTP_SERVER_ERROR_MIN <= status_code <= HTTP_SERVER_ERROR_MAX


def _decode_image(data: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.copy()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageDecodeError(f"Could not decode card image: {exc}") from exc


class LorcastClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        limiter: RateLimiter,
        *,
        base_url: str = LORCAST_API_BASE,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._set_codes: dict[str, str] = {}
        self._sets_lock = asyncio.Lock()

    # --- Sets ----------------------------------------------------------------

    @property
    def sets_loaded(self) -> bool:
        return bool(self._set_codes)

    @property
    def set_count(self) -> int:
        return len(self._set_codes)

    async def load_sets(self) -> bool:
        """Load the set list. Returns False (and logs) on failure instead of raising."""
        async with self._sets_lock:
            if self.sets_loaded:
                return True
            url = f"{self._base_url}{SETS_ENDPOINT}"
            try:
                body = await self._get(url, max_bytes=MAX_JSON_BYTES)
                sets = SetsResponse.model_validate_json(body)
            except LorcastError as exc:
                logger.warning("Could not load Lorcast set list: %s", exc.detail)
                return False
            except ValidationError as exc:
                logger.warning("Lorcast set list had an unexpected shape: %s", exc)
                return False
            self._set_codes = {set_code_key(item.code): item.code for item in sets.results}
            logger.info("Loaded %d Lorcast sets", len(self._set_codes))
            return True

    def resolve_set_code(self, set_code: str) -> str:
        """Map user input to Lorcast's canonical (case-sensitive) set code."""
        if not self.sets_loaded:
            return set_code
        canonical = self._set_codes.get(set_code_key(set_code))
        if canonical is None:
            raise UnknownSetError(f"Set '{set_code}' does not exist on Lorcast")
        return canonical

    # --- Cards ---------------------------------------------------------------

    async def fetch_card(self, set_code: str, number: str) -> LorcastCard:
        canonical_set = self.resolve_set_code(set_code)
        path = CARD_ENDPOINT.format(
            set_code=quote(canonical_set, safe=_PATH_SAFE_CHARS),
            number=quote(number, safe=_PATH_SAFE_CHARS),
        )
        url = f"{self._base_url}{path}"
        try:
            body = await self._get(url, max_bytes=MAX_JSON_BYTES)
        except UpstreamStatusError as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                raise CardNotFoundError(f"No card {number} in set {canonical_set}") from exc
            raise
        except ResponseTooLargeError as exc:
            raise InvalidResponseError(exc.detail) from exc
        try:
            return LorcastCard.model_validate_json(body)
        except ValidationError as exc:
            raise InvalidResponseError(f"Unexpected card data from Lorcast: {exc.error_count()} validation error(s)") from exc

    async def search_card(self, name: str, version: str | None) -> LorcastCard:
        """Find the standard printing of a card by exact name and version.

        Lorcast's `v:` term is fuzzy, so results are filtered to an exact (case-insensitive) match.
        A second, full-name search covers names or versions that themselves contain the separator.
        """
        wanted = card_name_key(name, version)
        primary = await self._search(build_exact_query(name, version))
        match = next((card for card in primary if card_name_key(card.name, card.version) == wanted), None)
        if match is not None:
            return match

        if version is not None:
            full_name = f"{name}{NAME_VERSION_SEPARATOR}{version}"
            fallback = await self._search(FUZZY_TERM_QUERY.format(text=normalize_card_text(full_name)))
            full_matches = [card for card in fallback if _full_name_key(card) == _text_key(full_name)]
            if len(full_matches) == 1:
                return full_matches[0]

        display = f"{name}{NAME_VERSION_SEPARATOR}{version}" if version else name
        if version is None and any(
            card.version and card_name_key(card.name, None) == wanted for card in primary
        ):
            example = next(card.display_name for card in primary if card.version)
            raise CardNotFoundError(
                f"'{display}' needs a version, for example '{example}'"
            )
        raise CardNotFoundError(f"No card named '{display}' on Lorcast")

    async def _search(self, query: str) -> list[LorcastCard]:
        url = str(httpx.URL(f"{self._base_url}{SEARCH_ENDPOINT}", params={SEARCH_QUERY_PARAM: query}))
        try:
            body = await self._get(url, max_bytes=MAX_JSON_BYTES)
        except ResponseTooLargeError as exc:
            raise InvalidResponseError(exc.detail) from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise InvalidResponseError(f"Lorcast search returned invalid JSON: {exc}") from exc
        results = payload.get(SEARCH_RESULTS_KEY) if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise InvalidResponseError("Lorcast search response has no results list")

        cards: list[LorcastCard] = []
        for item in results:
            try:
                cards.append(LorcastCard.model_validate(item))
            except ValidationError as exc:
                logger.warning("Skipping malformed search result for %r: %d error(s)", query, exc.error_count())
        logger.debug("Search %r returned %d result(s)", query, len(cards))
        return cards

    async def fetch_image(self, card: LorcastCard, size: ImageSize = ImageSize.LARGE) -> Image.Image:
        url = card.image_url(size)
        if url is None:
            raise ImageUnavailableError(f"Lorcast has no {size.value} image for {card.display_name}")
        try:
            data = await self._get(str(url), max_bytes=MAX_IMAGE_BYTES)
        except (UpstreamStatusError, UpstreamUnavailableError, ResponseTooLargeError) as exc:
            raise ImageDownloadError(f"Image download failed: {exc.detail}") from exc
        return await asyncio.to_thread(_decode_image, data)

    async def fetch_card_with_image(self, request: CardRequest) -> FetchedCard:
        card = await self.fetch_card(request.set_code, request.number)
        image = await self.fetch_image(card)
        return FetchedCard(card=card, image=image)

    async def fetch_all(self, requests: Sequence[CardRequest]) -> list[CardFetchResult]:
        """Fetch cards one at a time. A failure for one card never stops the others."""
        results: list[CardFetchResult] = []
        for request in requests:
            try:
                fetched = await self.fetch_card_with_image(request)
            except LorcastError as exc:
                logger.warning(
                    "Card %s/%s failed: %s (%s)", request.set_code, request.number, exc.reason, exc.detail
                )
                results.append(CardFetchResult(request=request, error=to_card_error(request, exc)))
            except Exception:
                logger.exception("Unexpected error fetching card %s/%s", request.set_code, request.number)
                results.append(
                    CardFetchResult(
                        request=request,
                        error=CardError(
                            set_code=request.set_code,
                            number=request.number,
                            reason=CardErrorReason.UPSTREAM_UNAVAILABLE,
                            detail="Unexpected error while fetching this card",
                        ),
                    )
                )
            else:
                logger.debug("Fetched %s/%s: %s", request.set_code, request.number, fetched.card.display_name)
                results.append(CardFetchResult(request=request, fetched=fetched))
        return results

    # --- HTTP ----------------------------------------------------------------

    async def _get(self, url: str, *, max_bytes: int) -> bytes:
        """GET with the global rate limit, bounded retries on transient failures, and a size cap."""
        total_attempts = MAX_RETRIES + 1
        last_reason = ""
        for attempt in range(1, total_attempts + 1):
            outcome = await self._attempt(url, max_bytes)
            if isinstance(outcome, bytes):
                return outcome
            last_reason = outcome.reason
            if attempt == total_attempts:
                break
            delay = outcome.retry_after_seconds
            if delay is None:
                delay = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Retrying %s after %s (attempt %d of %d, waiting %.2fs)",
                url,
                outcome.reason,
                attempt,
                total_attempts,
                delay,
            )
            await self._sleep(delay)
        raise UpstreamUnavailableError(f"Lorcast unavailable after {total_attempts} attempts: {last_reason}")

    async def _attempt(self, url: str, max_bytes: int) -> bytes | _RetrySignal:
        await self._limiter.acquire()
        started = time.perf_counter()
        try:
            async with self._http.stream("GET", url) as response:
                elapsed_ms = (time.perf_counter() - started) * MS_PER_SECOND
                logger.debug("GET %s -> %d (%.0f ms)", url, response.status_code, elapsed_ms)
                if _is_transient_status(response.status_code):
                    retry_after = None
                    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                        retry_after = parse_retry_after(response.headers.get(RETRY_AFTER_HEADER))
                    return _RetrySignal(f"HTTP {response.status_code}", retry_after)
                if not response.is_success:
                    raise UpstreamStatusError(response.status_code, url)
                return await self._read_limited(response, url, max_bytes)
        except httpx.TimeoutException as exc:
            return _RetrySignal(f"timeout ({type(exc).__name__})")
        except httpx.TransportError as exc:
            return _RetrySignal(f"connection error ({type(exc).__name__}: {exc})")

    @staticmethod
    async def _read_limited(response: httpx.Response, url: str, max_bytes: int) -> bytes:
        declared = response.headers.get(CONTENT_LENGTH_HEADER)
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            raise ResponseTooLargeError(f"Response from {url} is {declared} bytes; limit is {max_bytes}")
        chunks: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise ResponseTooLargeError(f"Response from {url} exceeded {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
