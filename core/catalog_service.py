from __future__ import annotations

from dataclasses import dataclass
import csv
from io import StringIO
import math
import socket
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
MAX_CATALOG_ROWS = 2_000
MAX_QUERY_RADIUS_DEG = 2.0
MAX_CATALOG_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_QUERY_TIMEOUT_SECONDS = 12.0


class CatalogQueryCancelled(RuntimeError):
    """Raised internally when a caller cancels an in-flight catalog transfer."""


@dataclass(frozen=True, slots=True)
class CatalogSource:
    """One bounded Gaia source returned by a cone search."""

    source_id: str
    ra_deg: float
    dec_deg: float
    g_mag: float | None = None
    bp_mag: float | None = None
    rp_mag: float | None = None


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    """Validated parameters for a remote Gaia DR3 cone search."""

    ra_deg: float
    dec_deg: float
    radius_deg: float
    max_rows: int = 500
    faint_limit_mag: float = 20.0

    def validated(self) -> "CatalogQuery":
        values = (self.ra_deg, self.dec_deg, self.radius_deg, self.faint_limit_mag)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("Catalog query values must be finite.")
        if not -90.0 <= float(self.dec_deg) <= 90.0:
            raise ValueError("Declination must be between -90 and 90 degrees.")
        if not 0.0 < float(self.radius_deg) <= MAX_QUERY_RADIUS_DEG:
            raise ValueError(
                f"Query radius must be greater than 0 and no more than {MAX_QUERY_RADIUS_DEG:g} degrees."
            )
        rows = int(self.max_rows)
        if not 1 <= rows <= MAX_CATALOG_ROWS:
            raise ValueError(f"Catalog result limit must be between 1 and {MAX_CATALOG_ROWS}.")
        if not -10.0 <= float(self.faint_limit_mag) <= 30.0:
            raise ValueError("Gaia G magnitude limit must be between -10 and 30.")
        return CatalogQuery(
            ra_deg=float(self.ra_deg) % 360.0,
            dec_deg=float(self.dec_deg),
            radius_deg=float(self.radius_deg),
            max_rows=rows,
            faint_limit_mag=float(self.faint_limit_mag),
        )


def build_gaia_adql(query: CatalogQuery) -> str:
    """Build numeric-only ADQL after validating all caller-controlled values."""

    query = query.validated()
    return (
        "SELECT TOP {rows} source_id, ra, dec, phot_g_mean_mag, "
        "phot_bp_mean_mag, phot_rp_mean_mag "
        "FROM gaiadr3.gaia_source "
        "WHERE 1 = CONTAINS("
        "POINT('ICRS', ra, dec), "
        "CIRCLE('ICRS', {ra:.10f}, {dec:.10f}, {radius:.10f})"
        ") AND phot_g_mean_mag <= {faint:.4f} "
        "ORDER BY phot_g_mean_mag ASC"
    ).format(
        rows=query.max_rows,
        ra=query.ra_deg,
        dec=query.dec_deg,
        radius=query.radius_deg,
        faint=query.faint_limit_mag,
    )


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def parse_gaia_csv(payload: bytes | str, *, max_rows: int = MAX_CATALOG_ROWS) -> list[CatalogSource]:
    """Parse a Gaia TAP CSV response with strict row, field, and coordinate limits."""

    if not 1 <= int(max_rows) <= MAX_CATALOG_ROWS:
        raise ValueError(f"Catalog result limit must be between 1 and {MAX_CATALOG_ROWS}.")
    if isinstance(payload, bytes):
        if len(payload) > MAX_CATALOG_RESPONSE_BYTES:
            raise ValueError("Gaia response exceeds the allowed download size.")
        text = payload.decode("utf-8-sig", errors="strict")
    else:
        text = payload
        if len(text.encode("utf-8")) > MAX_CATALOG_RESPONSE_BYTES:
            raise ValueError("Gaia response exceeds the allowed download size.")

    reader = csv.DictReader(StringIO(text))
    required = {"source_id", "ra", "dec"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise ValueError("Gaia response is missing required columns.")

    sources: list[CatalogSource] = []
    for row in reader:
        if len(sources) >= int(max_rows):
            break
        source_id = (row.get("source_id") or "").strip()
        if not source_id or len(source_id) > 64:
            continue
        try:
            ra_deg = float(row.get("ra") or "nan")
            dec_deg = float(row.get("dec") or "nan")
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(ra_deg) and math.isfinite(dec_deg)):
            continue
        if not -90.0 <= dec_deg <= 90.0:
            continue
        try:
            source = CatalogSource(
                source_id=source_id,
                ra_deg=ra_deg % 360.0,
                dec_deg=dec_deg,
                g_mag=_parse_optional_float(row.get("phot_g_mean_mag")),
                bp_mag=_parse_optional_float(row.get("phot_bp_mean_mag")),
                rp_mag=_parse_optional_float(row.get("phot_rp_mean_mag")),
            )
        except (TypeError, ValueError, OverflowError):
            continue
        sources.append(source)
    return sources


def query_gaia(
    query: CatalogQuery,
    *,
    timeout: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
    opener_factory: Callable[..., object] = build_opener,
    cancel_check: Callable[[], bool] | None = None,
    response_observer: Callable[[object | None], None] | None = None,
) -> list[CatalogSource]:
    """Run a bounded Gaia DR3 TAP query against the fixed HTTPS endpoint."""

    query = query.validated()
    if not math.isfinite(float(timeout)) or not 1.0 <= float(timeout) <= 60.0:
        raise ValueError("Catalog timeout must be between 1 and 60 seconds.")

    if cancel_check is not None and cancel_check():
        raise CatalogQueryCancelled("Gaia query was cancelled.")

    body = urlencode(
        {
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "QUERY": build_gaia_adql(query),
        }
    ).encode("ascii")
    request = Request(
        GAIA_TAP_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "text/csv",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "AstroView Gaia Overlay",
        },
    )
    opener = opener_factory(ProxyHandler({}))
    deadline = time.monotonic() + float(timeout)
    with opener.open(request, timeout=float(timeout)) as response:  # type: ignore[attr-defined]
        if response_observer is not None:
            response_observer(response)
        try:
            status = int(getattr(response, "status", 200))
            if status >= 400:
                raise HTTPError(
                    GAIA_TAP_URL,
                    status,
                    str(getattr(response, "reason", "")),
                    hdrs=getattr(response, "headers", {}),
                    fp=None,
                )
            content_length = getattr(response, "headers", {}).get("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError):
                    declared_length = 0
                if declared_length > MAX_CATALOG_RESPONSE_BYTES:
                    raise ValueError("Gaia response exceeds the allowed download size.")

            chunks: list[bytes] = []
            downloaded = 0
            while downloaded <= MAX_CATALOG_RESPONSE_BYTES:
                if cancel_check is not None and cancel_check():
                    raise CatalogQueryCancelled("Gaia query was cancelled.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Gaia query exceeded its total time limit.")
                _set_response_socket_timeout(response, min(1.0, remaining))
                read_size = min(64 * 1024, MAX_CATALOG_RESPONSE_BYTES + 1 - downloaded)
                try:
                    chunk = response.read(read_size)
                except (socket.timeout, TimeoutError):
                    if cancel_check is not None and cancel_check():
                        raise CatalogQueryCancelled("Gaia query was cancelled.")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Gaia query exceeded its total time limit.")
                    continue
                if not chunk:
                    break
                chunks.append(chunk)
                downloaded += len(chunk)
                if len(chunk) < read_size:
                    break
            payload = b"".join(chunks)
        finally:
            if response_observer is not None:
                response_observer(None)
    if len(payload) > MAX_CATALOG_RESPONSE_BYTES:
        raise ValueError("Gaia response exceeds the allowed download size.")
    return parse_gaia_csv(payload, max_rows=query.max_rows)


def _set_response_socket_timeout(response: object, timeout: float) -> None:
    """Best-effort short read timeout so cancellation is observed promptly."""

    candidates = []
    fp = getattr(response, "fp", None)
    if fp is not None:
        candidates.append(fp)
        raw = getattr(fp, "raw", None)
        if raw is not None:
            candidates.append(raw)
            candidates.append(getattr(raw, "_sock", None))
        candidates.append(getattr(fp, "_sock", None))
    for candidate in candidates:
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(max(0.05, float(timeout)))
                return
            except (OSError, TypeError, ValueError):
                continue
