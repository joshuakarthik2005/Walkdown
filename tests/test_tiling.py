import numpy as np

from backend.perception.sam import Instance
from backend.perception.tiling import merge_instances, segment_tiled, tile_boxes


def _inst(y0, y1, x0, x1, conf=0.6, shape=(100, 100)):
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    return Instance("0", (x0, y0, x1, y1), m, conf)


def test_tile_boxes_cover_frame_with_overlap():
    boxes = tile_boxes(640, 640, 2, 0.15)
    assert len(boxes) == 4 and boxes[0][:2] == (0, 0) and boxes[-1][2:] == (640, 640)
    assert boxes[0][2] > boxes[1][0]  # neighbours overlap
    assert len(tile_boxes(640, 640, 3)) == 9 and tile_boxes(640, 480, 1) == [(0, 0, 640, 480)]


def test_merge_joins_split_objects_and_keeps_separate_ones():
    a, b = _inst(10, 30, 10, 60), _inst(10, 30, 50, 90, conf=0.8)  # overlap 10 px wide band
    c = _inst(70, 90, 70, 90)
    merged = merge_instances([a, b, c])
    assert len(merged) == 2
    big = max(merged, key=lambda i: i.mask.sum())
    assert big.box == (10, 10, 90, 30) and big.confidence == 0.8


def test_segment_tiled_maps_tile_masks_back_to_frame():
    image = np.zeros((100, 100, 3), np.uint8)
    calls = []

    def fake(png, prompt, size, t):
        calls.append((prompt, size, t))
        w, h = size
        m = np.zeros((h, w), bool)
        m[0:5, 0:5] = True  # top-left corner of every tile
        return [Instance("0", (0, 0, 5, 5), m, 0.7)]

    out = segment_tiled(image, ["rust", "corrosion"], 2, fake)
    assert len(calls) == 8  # 4 tiles x 2 prompts
    corners = sorted(i.box[:2] for i in out)
    assert corners[0] == (0, 0) and len(out) == 4  # same spot from 2 prompts merged; 4 tile corners distinct
    assert all(i.mask.shape == (100, 100) for i in out)
