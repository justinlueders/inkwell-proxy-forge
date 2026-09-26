"""Application-wide constants. No other module should contain literal URLs, sizes, delays, or limits."""

import os
from pathlib import Path
from typing import Final

# --- Paths -------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
STATIC_DIR: Final[Path] = PROJECT_ROOT / "static"

# --- Lorcast API -------------------------------------------------------------

LORCAST_API_BASE: Final[str] = "https://api.lorcast.com/v0"
SETS_ENDPOINT: Final[str] = "/sets"
CARD_ENDPOINT: Final[str] = "/cards/{set_code}/{number}"
SEARCH_ENDPOINT: Final[str] = "/cards/search"
SEARCH_QUERY_PARAM: Final[str] = "q"
EXACT_NAME_QUERY: Final[str] = '!name:"{name}"'
VERSION_QUERY: Final[str] = 'v:"{version}"'
FUZZY_TERM_QUERY: Final[str] = '"{text}"'
NAME_VERSION_SEPARATOR: Final[str] = " - "
USER_AGENT: Final[str] = "LorcanaProxySheetGenerator/1.0"
USER_AGENT_HEADER: Final[str] = "User-Agent"

# --- App routes --------------------------------------------------------------

API_SHEET_ROUTE: Final[str] = "/api/sheet"
API_HEALTH_ROUTE: Final[str] = "/api/health"
API_CONFIG_ROUTE: Final[str] = "/api/config"
API_IMPORT_ROUTE: Final[str] = "/api/import"
STATIC_MOUNT_PATH: Final[str] = "/"
STATIC_MOUNT_NAME: Final[str] = "static"
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

# --- Network -----------------------------------------------------------------

REQUEST_DELAY_SECONDS: Final[float] = 0.075
REQUEST_TIMEOUT_SECONDS: Final[float] = 15.0
MAX_RETRIES: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[float] = 0.5
MAX_RETRY_AFTER_SECONDS: Final[float] = 10.0
MAX_IMAGE_BYTES: Final[int] = 5 * 1024 * 1024
MAX_JSON_BYTES: Final[int] = 2 * 1024 * 1024
HTTP_SERVER_ERROR_MIN: Final[int] = 500
HTTP_SERVER_ERROR_MAX: Final[int] = 599

# --- Print layout ------------------------------------------------------------

PRINT_DPI: Final[int] = 300
PAGE_WIDTH_IN: Final[float] = 8.5
PAGE_HEIGHT_IN: Final[float] = 11.0
CARD_WIDTH_IN: Final[float] = 2.5
CARD_HEIGHT_IN: Final[float] = 3.5
GRID_COLUMNS: Final[int] = 3
GRID_ROWS: Final[int] = 3
# Cutting gaps between cards. Letter paper has 1 in of spare width but only 0.5 in of spare
# height, so the vertical gap is kept small to leave a printable top and bottom margin.
CARD_GAP_X_IN: Final[float] = 0.125
CARD_GAP_Y_IN: Final[float] = 0.0625
CROP_MARK_LENGTH_IN: Final[float] = 0.2
CROP_MARK_GAP_IN: Final[float] = 0.03
CROP_MARK_WIDTH_PX: Final[int] = 2
JPEG_QUALITY: Final[int] = 90
PLACEHOLDER_FONT_SIZE_PX: Final[int] = 44
PLACEHOLDER_BORDER_WIDTH_PX: Final[int] = 4
PLACEHOLDER_LINE_SPACING_PX: Final[int] = 18

RgbColor = tuple[int, int, int]
PAGE_BACKGROUND: Final[RgbColor] = (255, 255, 255)
CROP_MARK_COLOR: Final[RgbColor] = (0, 0, 0)
PLACEHOLDER_FILL: Final[RgbColor] = (225, 225, 225)
PLACEHOLDER_BORDER: Final[RgbColor] = (120, 120, 120)
PLACEHOLDER_TEXT_COLOR: Final[RgbColor] = (40, 40, 40)

# --- Request limits ----------------------------------------------------------

MIN_QUANTITY: Final[int] = 1
MAX_QUANTITY: Final[int] = 20
MAX_ENTRIES_PER_REQUEST: Final[int] = 60
MAX_TOTAL_CARDS: Final[int] = 90
MAX_IDENTIFIER_LENGTH: Final[int] = 16
MAX_IMPORT_LINES: Final[int] = 100
MAX_IMPORT_TEXT_LENGTH: Final[int] = 10_000

# --- Logging -----------------------------------------------------------------

LOG_LEVEL_ENV_VAR: Final[str] = "LOG_LEVEL"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
LOG_LEVEL: Final[str] = os.environ.get(LOG_LEVEL_ENV_VAR, DEFAULT_LOG_LEVEL).upper()
LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
REQUEST_ID_LENGTH: Final[int] = 12
NO_REQUEST_ID: Final[str] = "-"


def inches_to_px(inches: float) -> int:
    """Convert a physical length to pixels at the print resolution."""
    return round(inches * PRINT_DPI)


# --- Derived pixel sizes -----------------------------------------------------

PAGE_WIDTH_PX: Final[int] = inches_to_px(PAGE_WIDTH_IN)
PAGE_HEIGHT_PX: Final[int] = inches_to_px(PAGE_HEIGHT_IN)
CARD_WIDTH_PX: Final[int] = inches_to_px(CARD_WIDTH_IN)
CARD_HEIGHT_PX: Final[int] = inches_to_px(CARD_HEIGHT_IN)
CARD_GAP_X_PX: Final[int] = inches_to_px(CARD_GAP_X_IN)
CARD_GAP_Y_PX: Final[int] = inches_to_px(CARD_GAP_Y_IN)
GRID_WIDTH_PX: Final[int] = CARD_WIDTH_PX * GRID_COLUMNS + CARD_GAP_X_PX * (GRID_COLUMNS - 1)
GRID_HEIGHT_PX: Final[int] = CARD_HEIGHT_PX * GRID_ROWS + CARD_GAP_Y_PX * (GRID_ROWS - 1)
GRID_LEFT_PX: Final[int] = (PAGE_WIDTH_PX - GRID_WIDTH_PX) // 2
GRID_TOP_PX: Final[int] = (PAGE_HEIGHT_PX - GRID_HEIGHT_PX) // 2
CARDS_PER_PAGE: Final[int] = GRID_COLUMNS * GRID_ROWS
CROP_MARK_LENGTH_PX: Final[int] = inches_to_px(CROP_MARK_LENGTH_IN)
CROP_MARK_GAP_PX: Final[int] = inches_to_px(CROP_MARK_GAP_IN)


def _validate_layout() -> None:
    if GRID_WIDTH_PX > PAGE_WIDTH_PX or GRID_HEIGHT_PX > PAGE_HEIGHT_PX:
        raise ValueError(
            f"Card grid {GRID_WIDTH_PX}x{GRID_HEIGHT_PX}px does not fit on the "
            f"{PAGE_WIDTH_PX}x{PAGE_HEIGHT_PX}px page"
        )
    if MAX_TOTAL_CARDS < MAX_QUANTITY:
        raise ValueError("MAX_TOTAL_CARDS must be at least MAX_QUANTITY")


_validate_layout()
