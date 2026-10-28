"""On-prem SAM: Modal RLE records become the same Instance objects as hosted SAM."""

import numpy as np
from pycocotools import mask as mask_utils

from backend.perception.sam_open import to_instances


def _record(mask: np.ndarray, obj: int, frame: int = 0) -> dict:
    rle = mask_utils.encode(np.asfortranarray(mask.astype(np.uint8)))
    rle["counts"] = rle["counts"].decode()
    return dict(frame=frame, obj_id=obj, score=0.8, box_xyxy=[0, 0, 1, 1], rle=rle)


def test_rle_records_decode_to_instances():
    m = np.zeros((40, 60), bool)
    m[5:15, 10:30] = True
    insts = to_instances([_record(m, 3, frame=7), _record(np.zeros((40, 60), bool), 4)])
    assert len(insts) == 1  # empty masks are dropped
    i = insts[0]
    assert i.object_id == "3" and i.frame == 7 and i.box == (10, 5, 30, 15) and i.area == 200
    assert to_instances([_record(m, 3, frame=7)], frame=0)[0].frame == 0
