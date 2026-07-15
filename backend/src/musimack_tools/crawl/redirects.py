"""Redirect classification and target normalization."""

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.fetching import FetchFailureCode
from musimack_tools.domain.urls import NormalizedUrl, UrlNormalizationError

REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class RedirectTargetError(Exception):
    """A redirect response whose Location cannot be followed safely."""

    def __init__(self, code: FetchFailureCode, explanation: str) -> None:
        super().__init__(explanation)
        self.code = code
        self.explanation = explanation


def is_redirect_status(status_code: int) -> bool:
    """Return whether a status participates in this batch's redirect policy."""
    return status_code in REDIRECT_STATUS_CODES


def normalize_redirect_target(current: NormalizedUrl, location: str | None) -> NormalizedUrl:
    """Resolve and normalize one Location value against its current response URL."""
    if location is None or not location.strip():
        raise RedirectTargetError(
            FetchFailureCode.REDIRECT_MISSING_LOCATION,
            "The redirect response did not provide a usable Location header",
        )
    try:
        return normalize_url(location, base=current)
    except UrlNormalizationError as error:
        raise RedirectTargetError(
            FetchFailureCode.REDIRECT_INVALID_LOCATION,
            "The redirect Location is invalid or unsupported",
        ) from error
