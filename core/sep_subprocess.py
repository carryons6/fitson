from __future__ import annotations

from typing import Any

import numpy as np


def run_extraction(
    data: np.ndarray,
    params: dict[str, Any],
    *,
    estimate_only: bool = False,
    estimate_threshold: float | None = None,
) -> dict[str, Any]:
    """Run SEP background + extraction in the current process.

    Called in a worker subprocess from :class:`SEPExtractWorker` so the main
    application stays responsive during long `sep.extract` runs (sep does not
    release the GIL).

    When ``estimate_only`` is True, uses ``estimate_threshold`` (sigma) instead
    of the configured threshold, skips segmentation-map generation, and returns
    only the detected object count. Used for a fast pre-pass to warn before
    running the full extraction when the image is crowded.
    """

    import sep

    if data.dtype not in (np.float32, np.float64):
        data = np.ascontiguousarray(data, dtype=np.float32)
    elif not data.flags["C_CONTIGUOUS"]:
        data = np.ascontiguousarray(data)

    bw = max(1, int(params["bkg_box_size"]))
    fw = max(1, int(params["bkg_filter_size"]))
    bkg = sep.Background(data, bw=bw, bh=bw, fw=fw, fh=fw)
    data_sub = data - bkg

    if estimate_only:
        thresh = float(estimate_threshold if estimate_threshold is not None else params["thresh"])
        objects = sep.extract(
            data_sub,
            thresh=thresh,
            err=bkg.globalrms,
            minarea=params["minarea"],
            deblend_nthresh=params["deblend_nthresh"],
            deblend_cont=params["deblend_cont"],
            clean=params["clean"],
            clean_param=params["clean_param"],
            segmentation_map=False,
        )
        return {"count": int(len(objects))}

    objects, segmentation_map = sep.extract(
        data_sub,
        thresh=params["thresh"],
        err=bkg.globalrms,
        minarea=params["minarea"],
        deblend_nthresh=params["deblend_nthresh"],
        deblend_cont=params["deblend_cont"],
        clean=params["clean"],
        clean_param=params["clean_param"],
        segmentation_map=True,
    )

    objects_dict = {name: np.asarray(objects[name]) for name in objects.dtype.names}
    return {
        "objects": objects_dict,
        "segmentation_map": segmentation_map,
        "background_rms": float(bkg.globalrms),
    }
