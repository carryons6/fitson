from __future__ import annotations


_EXACT_KEYWORD_DOCS: dict[str, str] = {
    "BITPIX": "Bits per pixel for the primary data array.",
    "BSCALE": "Linear scaling factor applied to stored pixel values.",
    "BZERO": "Zero-point offset applied to stored pixel values.",
    "DATE-OBS": "Observation start date and time.",
    "END": "Logical end of the FITS header block.",
    "EQUINOX": "Reference equinox for celestial coordinates.",
    "EXPTIME": "Exposure time for the observation, usually in seconds.",
    "FILTER": "Optical filter used for the exposure.",
    "GAIN": "Detector gain, typically electrons per ADU.",
    "INSTRUME": "Instrument or camera used to acquire the data.",
    "NAXIS": "Number of data axes in the image.",
    "OBJECT": "Target name or field identifier.",
    "RDNOISE": "Detector read noise, usually in electrons.",
    "SIMPLE": "Marks the file as conforming to the FITS standard.",
    "TELESCOP": "Telescope used to acquire the data.",
}

_PREFIX_KEYWORD_DOCS: tuple[tuple[str, str], ...] = (
    ("CDELT", "Coordinate increment per pixel along an axis."),
    ("CRPIX", "Reference pixel coordinate for an axis."),
    ("CRVAL", "World-coordinate value at the reference pixel."),
    ("CTYPE", "Coordinate type and projection for an axis."),
    ("NAXIS", "Length of a data axis in pixels."),
)


def describe_keyword(key: str) -> str | None:
    """Return a short description for a standard FITS keyword."""

    normalized = key.strip().upper()
    if not normalized:
        return None
    if normalized in _EXACT_KEYWORD_DOCS:
        return _EXACT_KEYWORD_DOCS[normalized]
    for prefix, description in _PREFIX_KEYWORD_DOCS:
        if normalized.startswith(prefix):
            return description
    return None


__all__ = ["describe_keyword"]
