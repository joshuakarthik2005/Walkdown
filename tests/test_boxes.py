"""Box proposals: merging box masks with text masks keeps text ids so verdicts are reused."""

import numpy as np

from backend.perception.boxes import box_system, merge_with_text
from backend.perception.sam import Instance


def _inst(obj: str, l: int, t: int, r: int, b: int) -> Instance:
    m = np.zeros((100, 100), bool)
    m[t:b, l:r] = True
    return Instance(object_id=obj, box=(l, t, r, b), mask=m, confidence=0.9)


def test_box_matching_a_text_instance_reuses_its_id():
    text = [_inst("3", 10, 10, 40, 40)]
    boxes = [_inst("0", 10, 10, 40, 41), _inst("1", 60, 60, 90, 90)]
    merged = dict(merge_with_text(text, boxes))
    assert "3" in merged and merged["3"] is text[0]
    new = [k for k in merged if k.startswith("b")]
    assert len(new) == 1 and merged[new[0]].box == (60, 60, 90, 90)


def test_box_enlarging_a_text_instance_becomes_a_new_candidate():
    text = [_inst("0", 10, 10, 20, 20)]
    boxes = [_inst("0", 10, 10, 60, 60)]
    merged = merge_with_text(text, boxes)
    assert [k for k, _ in merged] == ["b0"]


def test_prompt_matches_benchmark_at_640():
    assert "The image is 640x640 pixels." in box_system(640, 640)
    assert "right <= 1280" in box_system(1280, 720)
