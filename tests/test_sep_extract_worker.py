from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astroview.app.sep_extract_worker import SEPExtractWorker, _subprocess_entry
from astroview.core.contracts import ROISelection
from astroview.core.sep_service import SEPParameters


class _FakeConn:
    def __init__(self) -> None:
        self.messages: list[tuple[str, object]] = []
        self.closed = False

    def send(self, payload: tuple[str, object]) -> None:
        self.messages.append(payload)

    def close(self) -> None:
        self.closed = True


class TestSEPExtractWorker(unittest.TestCase):
    def test_share_array_preserves_values_in_shared_memory(self) -> None:
        data = np.arange(12, dtype=np.int16).reshape(3, 4)

        block, spec = SEPExtractWorker._share_array(data)
        try:
            reopened = np.ndarray(
                tuple(spec["shape"]),
                dtype=np.dtype(spec["dtype"]),
                buffer=block.buf,
            ).copy()
        finally:
            SEPExtractWorker._cleanup_shared_memory(block)

        self.assertEqual(np.dtype(spec["dtype"]), np.float32)
        np.testing.assert_array_equal(reopened, data.astype(np.float32))

    def test_subprocess_entry_reads_shared_memory_and_posts_result(self) -> None:
        data = np.arange(9, dtype=np.float32).reshape(3, 3)
        block, spec = SEPExtractWorker._share_array(data)
        conn = _FakeConn()
        captured: dict[str, object] = {}

        def fake_run_extraction(array, params_dict, **kwargs):
            captured["array"] = np.asarray(array).copy()
            captured["params"] = params_dict
            captured["kwargs"] = kwargs
            return {"count": 7}

        try:
            with patch("astroview.core.sep_subprocess.run_extraction", side_effect=fake_run_extraction):
                _subprocess_entry(
                    spec,
                    {"thresh": 3.0},
                    conn,
                    estimate_only=True,
                    estimate_threshold=15.0,
                )
        finally:
            SEPExtractWorker._cleanup_shared_memory(block)

        np.testing.assert_array_equal(captured["array"], data)
        self.assertEqual(captured["params"], {"thresh": 3.0})
        self.assertEqual(
            captured["kwargs"],
            {"estimate_only": True, "estimate_threshold": 15.0},
        )
        self.assertEqual(conn.messages, [("ok", {"count": 7})])
        self.assertTrue(conn.closed)

    def test_cancel_terminates_live_subprocess(self) -> None:
        worker = SEPExtractWorker(
            request_id=1,
            data_subarray=np.zeros((2, 2), dtype=np.float32),
            roi=ROISelection(x0=0, y0=0, width=2, height=2),
            params=SEPParameters(),
        )
        process = Mock()
        process.is_alive.return_value = True
        worker._process = process

        worker.cancel()

        self.assertTrue(worker._cancelled)
        process.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
