"""Tiled SAM 3.1: segment overlapping tiles, map masks back, merge cross-tile duplicates.

Small rust patches are a small share of a full frame; cutting the frame into
an n x n grid of overlapping tiles gives SAM each region at higher effective
resolution. Each tile is one image request ($0.0025), so an n x n grid costs
n^2 per frame per prompt.

Merging: an object cut by a tile boundary appears in two tiles, and the
overlap band makes those pieces overlap. Two instances are merged (mask union,
max confidence) when, inside the region where their boxes overlap, intersection / the smaller
mask there >= ``MERGE_OVERLAP``.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

from backend.perception.sam import Instance

MERGE_OVERLAP = 0.5


def tile_boxes(width: int, height: int, grid: int, overlap: float = 0.15) -> list[tuple[int, int, int, int]]:
    """(left, top, right, bottom) of an evenly spaced grid x grid layout; neighbours overlap by ``overlap`` of a tile."""
    if grid == 1:
        return [(0, 0, width, height)]
    tw = int(np.ceil(width / (grid - (grid - 1) * overlap)))
    th = int(np.ceil(height / (grid - (grid - 1) * overlap)))
    xs = np.linspace(0, width - tw, grid).round().astype(int)
    ys = np.linspace(0, height - th, grid).round().astype(int)
    return [(int(x), int(y), int(x) + tw, int(y) + th) for y in ys for x in xs]


def merge_instances(instances: list[Instance], threshold: float = MERGE_OVERLAP) -> list[Instance]:
    """Union instances whose masks overlap by >= threshold of the smaller one (transitively)."""
    n = len(instances)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(n):
        la, ta, ra, ba = instances[a].box
        for b in range(a + 1, n):
            lb, tb, rb, bb = instances[b].box
            l, t, r, bt = max(la, lb), max(ta, tb), min(ra, rb), min(ba, bb)
            if r <= l or bt <= t:
                continue  # boxes do not touch
            # Compare only inside the boxes' common region: a long object cut by a tile edge overlaps its
            # other piece fully there, even though the overlap is small relative to the whole object.
            ma, mb = instances[a].mask[t:bt, l:r], instances[b].mask[t:bt, l:r]
            inter = int((ma & mb).sum())
            smaller = min(int(ma.sum()), int(mb.sum()))
            if smaller and inter / smaller >= threshold:
                parent[find(a)] = find(b)
    groups: dict[int, list[Instance]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(instances[i])
    merged = []
    for k, members in enumerate(groups.values()):
        mask = np.logical_or.reduce([m.mask for m in members])
        ys, xs = np.nonzero(mask)
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        conf = max((m.confidence or 0.0) for m in members)
        merged.append(Instance(object_id=str(k), box=box, mask=mask, confidence=conf, frame=members[0].frame))
    return merged


def segment_tiled(
    image: np.ndarray,
    prompts: list[str],
    grid: int,
    segment_tile: Callable[[bytes, str, tuple[int, int], int], list[Instance]],
    *,
    overlap: float = 0.15,
) -> list[Instance]:
    """Run ``segment_tile(png_bytes, prompt, (w, h), tile_index)`` on every tile and prompt; merge into full-frame instances.

    ``segment_tile`` returns tile-local instances; caching and billing are the caller's concern.
    """
    h, w = image.shape[:2]
    found: list[Instance] = []
    for t, (l, top, r, b) in enumerate(tile_boxes(w, h, grid, overlap)):
        ok, png = cv2.imencode(".png", image[top:b, l:r])
        for prompt in prompts:
            for inst in segment_tile(png.tobytes(), prompt, (r - l, b - top), t):
                full = np.zeros((h, w), bool)
                full[top:b, l:r] = inst.mask
                bl, bt, br, bb = inst.box
                found.append(Instance(object_id=inst.object_id, box=(bl + l, bt + top, br + l, bb + top), mask=full,
                                      confidence=inst.confidence))
    return merge_instances(found)
