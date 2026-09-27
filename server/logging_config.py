# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Logging setup with a per-request correlation id on every record."""

import logging
from contextvars import ContextVar

from server.config import LOG_FORMAT, LOG_LEVEL, NO_REQUEST_ID

request_id_var: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)

_configured = False


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def get_request_id() -> str:
    return request_id_var.get()


def configure_logging() -> None:
    """Configure the root logger once. Safe to call repeatedly."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(LOG_LEVEL)

    # httpx logs every request at INFO; our client logs its own requests at DEBUG.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Pillow logs every plugin import at DEBUG.
    logging.getLogger("PIL").setLevel(logging.INFO)

    _configured = True
