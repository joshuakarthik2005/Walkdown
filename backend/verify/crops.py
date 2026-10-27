"""Verifier inputs: a tight crop with the mask outlined, and a small full-frame thumbnail."""

from __future__ import annotations

import base64

import cv2
import numpy as np

OUTLINE_BGR = (255, 255, 0)  # cyan: rare in rust and paint, easy to describe in the prompt


def _png_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("could not encode image")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def candidate_crop(image: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int], *,
                   margin: float = 0.3, min_side: int = 64, out_side: int = 448) -> np.ndarray:
    """Crop around the box (plus ``margin`` of its size each side), outline the mask, resize to ``out_side``."""
    h, w = mask.shape
    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    pad_x = max(int(bw * margin), (min_side - bw) // 2, 8)
    pad_y = max(int(bh * margin), (min_side - bh) // 2, 8)
    x0, y0 = max(0, left - pad_x), max(0, top - pad_y)
    x1, y1 = min(w, right + pad_x), min(h, bottom + pad_y)
    crop = image[y0:y1, x0:x1].copy()
    contours, _ = cv2.findContours(mask[y0:y1, x0:x1].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    scale = out_side / max(crop.shape[:2])
    crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)),
                      interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    contours = [(c * scale).astype(np.int32) for c in contours]
    cv2.drawContours(crop, contours, -1, OUTLINE_BGR, 2)
    return crop


def context_thumbnail(image: np.ndarray, box: tuple[int, int, int, int], side: int = 256) -> np.ndarray:
    """Whole frame, scaled to ``side`` on the long edge, with the candidate box drawn."""
    scale = side / max(image.shape[:2])
    thumb = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA)
    l, t, r, b = (round(v * scale) for v in box)
    cv2.rectangle(thumb, (l, t), (max(l + 1, r - 1), max(t + 1, b - 1)), OUTLINE_BGR, 2)
    return thumb


def verifier_images(image: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int]) -> tuple[str, str]:
    """Data URLs for (crop with outline, context thumbnail)."""
    return _png_data_url(candidate_crop(image, mask, box)), _png_data_url(context_thumbnail(image, box))
