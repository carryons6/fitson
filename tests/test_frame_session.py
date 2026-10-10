from __future__ import annotations

import unittest
import weakref

import numpy as np

from astroview.app.frame_session import FrameSession
from astroview.core.fits_data import FITSData


class TestFrameSession(unittest.TestCase):
    def test_append_creates_complete_independent_frame_state(self) -> None:
        session = FrameSession()
        first, second = FITSData(path="a.fits"), FITSData(path="b.fits")
        session.append(first, preview_dimension=1024, sample_step=4)
        session.append(second)
        session[0].dirty = False
        self.assertEqual(session.datasets, (first, second))
        self.assertFalse(session[0].dirty)
        self.assertTrue(session[1].dirty)
        self.assertIsNone(session[1].background)
        self.assertEqual(session[1].sample_step, 1)

    def test_invalidation_keeps_display_until_replacement_without_touching_data(self) -> None:
        data = FITSData(data=np.ones((3, 5)))
        session = FrameSession([data, FITSData()])
        image = object()
        session[0].image = image
        session[0].preview_dimension = 2048
        session[0].dirty = False
        session[0].background = FITSData(data=np.zeros((3, 5)))
        session[0].residual = FITSData(data=np.ones((3, 5)))
        session[1].dirty = False
        affected = session.invalidate_backgrounds([0, 0, -1, 99])
        session.invalidate_renders(affected)
        self.assertEqual(affected, [0])
        self.assertIs(session[0].data, data)
        self.assertIs(session[0].image, image)
        self.assertTrue(session[0].dirty)
        self.assertEqual(session[0].preview_dimension, 0)
        self.assertIsNone(session[0].background)
        self.assertIsNone(session[0].residual)
        self.assertFalse(session[1].dirty)

    def test_clear_releases_arrays_and_resets_selection(self) -> None:
        pixels = np.ones((4, 4))
        reference = weakref.ref(pixels)
        session = FrameSession([FITSData(data=pixels), FITSData()])
        session.current_index = 1
        del pixels
        session.clear()
        self.assertEqual(len(session), 0)
        self.assertEqual(session.current_index, 0)
        self.assertIsNone(reference())

    def test_worker_snapshot_is_unchanged_when_more_frames_are_loaded(self) -> None:
        first = FITSData()
        session = FrameSession([first])
        snapshot = session.datasets
        session.append(FITSData())
        self.assertEqual(snapshot, (first,))
        self.assertEqual(len(session), 2)
