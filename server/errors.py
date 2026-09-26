"""Typed failures for fetching a card. Each maps to one CardErrorReason."""

from typing import ClassVar

from server.models import CardErrorReason


class LorcastError(Exception):
    reason: ClassVar[CardErrorReason] = CardErrorReason.UPSTREAM_UNAVAILABLE

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CardNotFoundError(LorcastError):
    reason = CardErrorReason.NOT_FOUND


class UnknownSetError(LorcastError):
    reason = CardErrorReason.UNKNOWN_SET


class InvalidResponseError(LorcastError):
    reason = CardErrorReason.INVALID_RESPONSE


class ImageUnavailableError(LorcastError):
    reason = CardErrorReason.NO_IMAGE


class ImageDownloadError(LorcastError):
    reason = CardErrorReason.IMAGE_DOWNLOAD_FAILED


class ImageDecodeError(LorcastError):
    reason = CardErrorReason.IMAGE_DECODE_FAILED


class UpstreamUnavailableError(LorcastError):
    reason = CardErrorReason.UPSTREAM_UNAVAILABLE


class UpstreamStatusError(LorcastError):
    """Non-retryable, non-success HTTP status from Lorcast."""

    reason = CardErrorReason.UPSTREAM_UNAVAILABLE

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"Lorcast returned HTTP {status_code} for {url}")
        self.status_code = status_code


class ResponseTooLargeError(LorcastError):
    reason = CardErrorReason.INVALID_RESPONSE
