from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
import json
import re
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from PySide6.QtCore import QObject, Signal, Slot

from .. import APP_RELEASES_API_URL, APP_RELEASES_URL, APP_TAGS_API_URL
from ..diagnostics import log_current_exception


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateCheckResult:
    """Outcome of an update check against the configured upstream source."""

    status: str
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    detail: str = ""


def normalize_version(version: str) -> str:
    """Normalize tags such as `v1.2.3` into plain dotted versions."""

    return version.strip().lstrip("vV")


def version_key(version: str) -> tuple[int, ...]:
    """Return a sortable integer tuple from a version-like string."""

    parts = re.findall(r"\d+", normalize_version(version))
    if not parts:
        raise ValueError(f"Unsupported version string: {version!r}")
    return tuple(int(part) for part in parts)


def compare_versions(left: str, right: str) -> int:
    """Compare two dotted versions, returning -1/0/1."""

    left_key = version_key(left)
    right_key = version_key(right)
    width = max(len(left_key), len(right_key))
    left_padded = left_key + (0,) * (width - len(left_key))
    right_padded = right_key + (0,) * (width - len(right_key))
    if left_padded < right_padded:
        return -1
    if left_padded > right_padded:
        return 1
    return 0


def build_release_url(tag_name: str) -> str:
    """Return the GitHub release/tag page for a given tag."""

    return f"{APP_RELEASES_URL}/tag/{tag_name}"


def fetch_json(url: str) -> Any:
    """Fetch one JSON payload from the update source with proxies disabled."""

    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AstroView Update Checker",
        },
    )
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        payload = response.read()
        status = getattr(response, "status", 200)
        reason = getattr(response, "reason", "")
        if status >= 400:
            raise HTTPError(url, status, reason, hdrs=getattr(response, "headers", {}), fp=None)
        return json.loads(payload.decode("utf-8"))


def fetch_latest_version_info() -> tuple[str | None, str | None]:
    """Fetch the latest published version, falling back from releases to tags."""

    try:
        release_payload = fetch_json(APP_RELEASES_API_URL)
    except HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        tag_name = release_payload.get("tag_name")
        if tag_name:
            release_url = release_payload.get("html_url") or build_release_url(tag_name)
            return normalize_version(tag_name), release_url

    tags_payload = fetch_json(APP_TAGS_API_URL)
    if isinstance(tags_payload, list) and tags_payload:
        tag_name = tags_payload[0].get("name")
        if tag_name:
            return normalize_version(tag_name), build_release_url(tag_name)
    return None, APP_RELEASES_URL


class UpdateCheckWorker(QObject):
    """Background worker that checks GitHub for a newer published version."""

    finished = Signal()
    result_ready = Signal(object)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = normalize_version(current_version)

    @Slot()
    def run(self) -> None:
        try:
            latest_version, release_url = fetch_latest_version_info()
            if latest_version is None:
                result = UpdateCheckResult(
                    status="unavailable",
                    current_version=self.current_version,
                    release_url=release_url,
                    detail=self.tr("No published release or tag information is available yet."),
                )
            elif compare_versions(self.current_version, latest_version) < 0:
                result = UpdateCheckResult(
                    status="update_available",
                    current_version=self.current_version,
                    latest_version=latest_version,
                    release_url=release_url,
                    detail=self.tr("A newer version ({version}) is available.").format(
                        version=latest_version
                    ),
                )
            else:
                result = UpdateCheckResult(
                    status="up_to_date",
                    current_version=self.current_version,
                    latest_version=latest_version,
                    release_url=release_url,
                    detail=self.tr("You are running the latest version ({version}).").format(
                        version=self.current_version
                    ),
                )
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
            log_current_exception(__name__, "Update check failed")
            result = UpdateCheckResult(
                status="error",
                current_version=self.current_version,
                detail=str(exc),
                release_url=APP_RELEASES_URL,
            )

        self.result_ready.emit(result)
        self.finished.emit()
