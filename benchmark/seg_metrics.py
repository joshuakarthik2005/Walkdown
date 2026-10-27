"""Instance-level segmentation metrics for the perception and verification benchmark.

Masks are boolean numpy arrays of shape (H, W). Mask IoU uses pycocotools RLE.
Predictions are matched to ground truth one-to-one, greedily by descending
score, at an IoU threshold (0.5 by default): a prediction is a true positive
if it matches an unmatched ground-truth instance at or above the threshold.

Negative images (no ground-truth instances) matter most for the verifier,
whose job is to reject false positives, so image-level false-positive rates
on negatives are reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pycocotools import mask as mask_utils


@dataclass
class Prediction:
    """One predicted instance."""

    mask: np.ndarray
    score: float = 1.0


@dataclass
class ImageResult:
    """Ground truth and predictions for one image."""

    image_id: str
    gt_masks: list[np.ndarray]
    predictions: list[Prediction] = field(default_factory=list)


def _rle(masks: list[np.ndarray]) -> list[dict]:
    return mask_utils.encode(np.asfortranarray(np.stack(masks).transpose(1, 2, 0).astype(np.uint8)))


def iou_matrix(pred_masks: list[np.ndarray], gt_masks: list[np.ndarray]) -> np.ndarray:
    """IoU between every prediction (rows) and ground-truth instance (columns)."""
    if not pred_masks or not gt_masks:
        return np.zeros((len(pred_masks), len(gt_masks)))
    return np.asarray(mask_utils.iou(_rle(pred_masks), _rle(gt_masks), [0] * len(gt_masks)))


def match(image: ImageResult, iou_threshold: float = 0.5) -> tuple[int, int, int, list[float]]:
    """Greedy one-to-one matching. Returns (tp, fp, fn, IoUs of matched pairs)."""
    order = sorted(range(len(image.predictions)), key=lambda i: -image.predictions[i].score)
    preds = [image.predictions[i].mask for i in order]
    ious = iou_matrix(preds, image.gt_masks)
    used: set[int] = set()
    matched = []
    for p in range(len(preds)):
        best, best_iou = None, iou_threshold
        for g in range(len(image.gt_masks)):
            if g not in used and ious[p, g] >= best_iou:
                best, best_iou = g, ious[p, g]
        if best is not None:
            used.add(best)
            matched.append(float(ious[p, best]))
    tp = len(matched)
    return tp, len(preds) - tp, len(image.gt_masks) - tp, matched


@dataclass
class Metrics:
    """Aggregate instance and image-level metrics."""

    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    mean_matched_iou: float
    n_images: int
    n_positive_images: int
    n_negative_images: int
    negative_images_with_fp: int
    fp_on_negatives: int

    @property
    def negative_fp_rate(self) -> float:
        """Share of negative images with at least one false positive (lower is better)."""
        return self.negative_images_with_fp / self.n_negative_images if self.n_negative_images else 0.0


def evaluate(images: list[ImageResult], iou_threshold: float = 0.5) -> Metrics:
    """Instance-level precision, recall and F1 at an IoU threshold, plus negative-image FP stats."""
    tp = fp = fn = 0
    ious: list[float] = []
    neg = neg_with_fp = fp_neg = 0
    for img in images:
        t, f, n, m = match(img, iou_threshold)
        tp, fp, fn = tp + t, fp + f, fn + n
        ious += m
        if not img.gt_masks:
            neg += 1
            fp_neg += f
            neg_with_fp += f > 0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Metrics(
        tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1,
        mean_matched_iou=float(np.mean(ious)) if ious else 0.0,
        n_images=len(images), n_positive_images=len(images) - neg, n_negative_images=neg,
        negative_images_with_fp=neg_with_fp, fp_on_negatives=fp_neg,
    )
