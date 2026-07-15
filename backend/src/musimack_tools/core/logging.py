"""Minimal process logging policy for safe third-party verbosity."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure application severity and suppress HTTPX's query-bearing INFO request log."""
    logging.getLogger("musimack_tools").setLevel(settings.log_level.value)
    logging.getLogger("httpx").setLevel(logging.WARNING)
