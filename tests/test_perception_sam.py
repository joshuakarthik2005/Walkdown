from pathlib import Path

import numpy as np

from backend.clients.cost import CostLedger, CostEntry, muse_cost, sam_image_cost, sam_video_cost
from backend.perception.sam import parse_output

FIXTURE = Path(__file__).parent / "fixtures" / "sam_image.txt"


def test_parse_image_fixture_into_full_frame_masks():
    instances = parse_output(FIXTURE.read_text(encoding="utf-8"), 640, 480)
    assert len(instances) == 2  # two drawn patches
    for inst in instances:
        left, top, right, bottom = inst.box
        assert inst.mask.shape == (480, 640) and inst.mask.dtype == bool
        assert inst.area > 1000
        ys, xs = np.nonzero(inst.mask)
        assert xs.min() >= left and xs.max() < right and ys.min() >= top and ys.max() < bottom
        assert 0.0 <= inst.confidence <= 1.0
    # the drawn patches are centred at (200, 200) and (430, 320)
    centres = sorted((float(np.nonzero(i.mask)[1].mean()), float(np.nonzero(i.mask)[0].mean())) for i in instances)
    assert abs(centres[0][0] - 200) < 15 and abs(centres[1][0] - 430) < 15


def test_empty_output_is_no_match():
    assert parse_output("", 640, 480) == []


def test_costs():
    assert sam_image_cost(50) == 0.125
    assert sam_video_cost(10) == sam_video_cost(50) == 0.01
    assert abs(sam_video_cost(100) - 0.02) < 1e-12
    assert abs(muse_cost(1_000_000, 0) - 1.25) < 1e-9
    assert abs(muse_cost(1_000_000, 1_000_000, cached_tokens=1_000_000) - (0.15 + 4.25)) < 1e-9
    ledger = CostLedger()
    ledger.add(CostEntry(job="a", model="sam-3.1", usd=0.0025, images=1))
    ledger.add(CostEntry(job="b", model="sam-3.1", usd=0.01, frames=50))
    assert ledger.total() == 0.0125 and ledger.summary("a")["images"] == 1
