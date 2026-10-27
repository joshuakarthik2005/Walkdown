import numpy as np
import pytest

from benchmark.seg_metrics import ImageResult, Prediction, evaluate, iou_matrix, match
from benchmark.splits import load_split, make_splits, save_splits


def _box(y0, y1, x0, x1, shape=(20, 20)) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def test_iou_matrix_values():
    a, b = _box(0, 10, 0, 10), _box(0, 10, 5, 15)
    ious = iou_matrix([a, b], [a])
    assert ious.shape == (2, 1)
    assert ious[0, 0] == pytest.approx(1.0)
    assert ious[1, 0] == pytest.approx(50 / 150)


def test_greedy_matching_is_one_to_one_and_score_ordered():
    gt = [_box(0, 10, 0, 10)]
    preds = [Prediction(_box(0, 10, 0, 9), score=0.4), Prediction(_box(0, 10, 0, 10), score=0.9)]
    tp, fp, fn, ious = match(ImageResult("i", gt, preds))
    assert (tp, fp, fn) == (1, 1, 0)
    assert ious == [pytest.approx(1.0)]  # the higher-scored, exact prediction wins


def test_low_iou_is_not_a_match():
    tp, fp, fn, _ = match(ImageResult("i", [_box(0, 10, 0, 10)], [Prediction(_box(0, 10, 7, 17))]))
    assert (tp, fp, fn) == (0, 1, 1)


def test_evaluate_reports_negatives_separately():
    images = [
        ImageResult("pos", [_box(0, 10, 0, 10)], [Prediction(_box(0, 10, 0, 10))]),
        ImageResult("neg_clean", [], []),
        ImageResult("neg_fp", [], [Prediction(_box(5, 8, 5, 8)), Prediction(_box(0, 2, 0, 2))]),
    ]
    m = evaluate(images)
    assert (m.tp, m.fp, m.fn) == (1, 2, 0)
    assert m.precision == pytest.approx(1 / 3) and m.recall == 1.0
    assert m.f1 == pytest.approx(0.5)
    assert (m.n_positive_images, m.n_negative_images) == (1, 2)
    assert m.negative_images_with_fp == 1 and m.fp_on_negatives == 2
    assert m.negative_fp_rate == 0.5


def test_empty_everything():
    m = evaluate([ImageResult("n", [], [])])
    assert (m.precision, m.recall, m.f1) == (0.0, 0.0, 0.0)


def test_splits_disjoint_stratified_and_reproducible(tmp_path):
    pos = [f"p{i}" for i in range(800)]
    neg = [f"n{i}" for i in range(200)]
    s = make_splits(pos, neg, dev_size=50, test_size=900)
    assert len(s.dev) == 50 and len(s.test) == 900
    assert not set(s.dev) & set(s.test)
    assert s.dev_negatives == 10 and s.test_negatives == 180  # 20% negatives in both
    assert make_splits(list(reversed(pos)), neg, dev_size=50, test_size=900) == s
    save_splits(s, tmp_path)
    assert load_split("dev", tmp_path) == s.dev and load_split("test", tmp_path) == s.test


def test_splits_reject_overlap_and_oversize():
    with pytest.raises(ValueError):
        make_splits(["a"], ["a"], dev_size=1, test_size=0)
    with pytest.raises(ValueError):
        make_splits(["a", "b"], [], dev_size=2, test_size=1)
