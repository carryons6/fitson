"""Helpers for constructing partial display/session states in UI tests."""
from astroview.app.frame_session import FrameSession
from astroview.core.fits_data import FITSData


def set_session_field(window, field, values):
    values = list(values)
    if field == 'data':
        window._session = FrameSession(values)
        return
    # A few canvas-only tests intentionally supply an image without FITS data.
    while len(window._session) < len(values):
        window._session.append(FITSData())
    if len(values) != len(window._session):
        raise ValueError('Test fixture cache count must match its frame count.')
    for frame, value in zip(window._session, values):
        setattr(frame, field, value)
