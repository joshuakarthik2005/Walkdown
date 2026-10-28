"""Static SVG charts for RESULTS.md and PLANNER_RESULTS.md (no plotting dependency).

Charts follow the dataviz rules used in this repo: one axis, thin marks with
rounded data ends, recessive grid, text in ink colours (never series colours),
a legend for 2+ series plus selective direct labels, categorical hues in fixed
order (validated: blue, orange, aqua), and light/dark variants inside the SVG
via prefers-color-scheme. Every chart sits next to a Markdown table with the
same numbers (the table view).

    .venv\\Scripts\\python.exe -m benchmark.charts
"""

from __future__ import annotations

import json
import statistics
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
OUT = HERE / "charts"

STYLE = """<style>
svg{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
@media (prefers-color-scheme:dark){svg{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#383835;
--s1:#3987e5;--s2:#d95926;--s3:#199e70}}
.bg{fill:var(--surface)}.t{fill:var(--ink);font-size:13px}.h{fill:var(--ink);font-size:15px;font-weight:600}
.m{fill:var(--ink2);font-size:11px}.g{stroke:var(--grid);stroke-width:1}.ax{stroke:var(--ink2);stroke-width:1}
.s1{fill:var(--s1)}.s2{fill:var(--s2)}.s3{fill:var(--s3)}.l1{stroke:var(--s1)}.l2{stroke:var(--s2)}.l3{stroke:var(--s3)}
.ring{stroke:var(--surface);stroke-width:2}
</style>"""


def svg(width: int, height: int, title: str, body: list[str], desc: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-labelledby="t d">{STYLE}<title id="t">{escape(title)}</title><desc id="d">{escape(desc)}'
            f'</desc><rect class="bg" width="{width}" height="{height}" rx="8"/>'
            f'<text class="h" x="20" y="28">{escape(title)}</text>' + "".join(body) + "</svg>")


def hbar(x0: float, y: float, w: float, h: float, cls: str) -> str:
    """Horizontal bar with a 4px rounded data end (right) anchored square at the baseline (left)."""
    if w <= 0:
        return ""
    r = min(4, w, h / 2)
    return (f'<path class="{cls}" d="M{x0},{y} h{w - r} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r} '
            f'a{r},{r} 0 0 1 -{r},{r} h-{w - r} z"/>')


def legend(x: float, y: float, items: list[tuple[str, str]]) -> list[str]:
    out = []
    for cls, label in items:
        out.append(f'<rect class="{cls}" x="{x}" y="{y - 9}" width="10" height="10" rx="2"/>'
                   f'<text class="m" x="{x + 15}" y="{y}">{escape(label)}</text>')
        x += 22 + 7 * len(label)
    return out


# ---- planner -------------------------------------------------------------------------------------------------

REGIMES = ["default", "loose", "tight_capacity", "tight_shutdown", "tight_permits"]


def _pct(new: float, old: float) -> float:
    return 100.0 * (1 - new / old) if old else 0.0


def planner_improvement() -> str:
    """Median (dot) and min-max (line) of CP-SAT risk improvement over priority sort, per regime."""
    rows = []
    for r in REGIMES:
        data = json.loads((RESULTS / f"planner_{r}.json").read_text(encoding="utf-8"))["static"]
        vals = [_pct(x["cpsat"]["objective"], x["baseline"]["objective"]) for x in data]
        rows.append((r.replace("_", " "), statistics.median(vals), min(vals), max(vals), len(vals)))
    w, left, top, row_h = 720, 150, 70, 38
    scale = (w - left - 60) / 30.0  # 0-30 %
    h = top + row_h * len(rows) + 50
    body = [f'<text class="m" x="20" y="48">Risk reduction vs severity-sort baseline, % · dot = median, line = min-max '
            f'across seeds · higher is better</text>']
    for v in range(0, 31, 5):
        x = left + v * scale
        body.append(f'<line class="g" x1="{x}" x2="{x}" y1="{top - 10}" y2="{top + row_h * len(rows)}"/>'
                    f'<text class="m" x="{x}" y="{top + row_h * len(rows) + 16}" text-anchor="middle">{v}%</text>')
    for i, (name, med, lo, hi, n) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        body.append(f'<text class="t" x="{left - 12}" y="{y + 4}" text-anchor="end">{escape(name)}</text>'
                    f'<line class="l1" x1="{left + lo * scale}" x2="{left + hi * scale}" y1="{y}" y2="{y}" '
                    f'stroke-width="2" stroke-linecap="round"/>'
                    f'<circle class="s1 ring" cx="{left + med * scale}" cy="{y}" r="5"/>'
                    f'<text class="m" x="{left + hi * scale + 8}" y="{y + 4}">{med:.1f}% (n={n})</text>')
    return svg(w, int(h), "CP-SAT vs priority sort: risk reduction by plant regime", body,
               "Median and range of risk-weighted exposure reduction per regime; CP-SAT is never worse in all 60 runs.")


def replan_moves() -> str:
    """Median jobs moved after a crew outage: CP-SAT two-stage vs baseline from scratch vs baseline patch."""
    methods = [("cpsat", "s1", "CP-SAT two-stage"), ("baseline_scratch", "s2", "Baseline re-run"),
               ("baseline_patch", "s3", "Baseline patch")]
    rows = []
    for r in REGIMES[1:]:
        data = [x for x in json.loads((RESULTS / f"planner_{r}.json").read_text(encoding="utf-8"))["replan"]
                if x["change"] == "crew_unavailable"]
        rows.append((r.replace("_", " "), [statistics.median(x[m]["moved"] for x in data) for m, _, _ in methods]))
    w, left, top, bar_h, gap = 720, 150, 78, 12, 2
    group = 3 * (bar_h + gap) + 14
    vmax = max(max(v) for _, v in rows)
    scale = (w - left - 70) / vmax
    h = top + group * len(rows) + 6
    body = [f'<text class="m" x="20" y="48">Median jobs moved when the busiest crew is out for 72 h · fewer = more '
            f'stable · 5 seeds per regime</text>'] + legend(20, 66, [(c, l) for _, c, l in methods])
    for i, (name, vals) in enumerate(rows):
        y0 = top + i * group
        body.append(f'<text class="t" x="{left - 12}" y="{y0 + 1.5 * (bar_h + gap) + 4}" text-anchor="end">'
                    f'{escape(name)}</text>')
        for j, ((_, cls, _), v) in enumerate(zip(methods, vals)):
            y = y0 + j * (bar_h + gap)
            body.append(hbar(left, y, v * scale, bar_h, cls) +
                        f'<text class="m" x="{left + v * scale + 6}" y="{y + bar_h - 2}">{v:g}</text>')
    body.append(f'<line class="ax" x1="{left}" x2="{left}" y1="{top - 4}" y2="{top + group * len(rows) - 10}"/>')
    return svg(w, int(h), "Replan stability: jobs moved after a crew outage", body,
               "CP-SAT moves fewer jobs than re-running the baseline, but more than the patch heuristic, "
               "in exchange for lower risk.")


def pareto() -> str:
    """Demo scenario: jobs moved vs exposure increase over epsilon=0, one line per change."""
    rows = json.loads((RESULTS / "replan_pareto_demo.json").read_text(encoding="utf-8"))["rows"]
    series = [("crew_unavailable", "s1", "l1", "Busiest crew out 72 h"),
              ("window_cancelled", "s2", "l2", "First shutdown cancelled")]
    w, h, left, right, top, bottom = 720, 330, 70, 40, 70, 280
    pts = {}
    for key, *_ in series:
        rs = sorted([r for r in rows if r["change"] == key], key=lambda r: r["epsilon"])
        base = rs[0]["exposure"]
        pts[key] = [(r["moved"], 100 * (r["exposure"] / base - 1), r["epsilon"]) for r in rs]
    xmax = max(p[0] for v in pts.values() for p in v) + 1
    ymax = max(6.0, max(p[1] for v in pts.values() for p in v) + 1)
    sx = lambda v: left + v / xmax * (w - left - right)  # noqa: E731
    sy = lambda v: bottom - v / ymax * (bottom - top)  # noqa: E731
    body = [f'<text class="m" x="20" y="48">Demo scenario, change at hour 48 · each point is one ε (0, 0.02, 0.05, '
            f'0.10) · lower-left is better</text>'] + legend(w - 380, 66, [(c, l) for _, c, _, l in series])
    for v in range(0, int(ymax) + 1, 2):
        body.append(f'<line class="g" x1="{left}" x2="{w - right}" y1="{sy(v)}" y2="{sy(v)}"/>'
                    f'<text class="m" x="{left - 8}" y="{sy(v) + 4}" text-anchor="end">+{v}%</text>')
    for v in range(0, int(xmax) + 1, 2):
        body.append(f'<text class="m" x="{sx(v)}" y="{bottom + 16}" text-anchor="middle">{v}</text>')
    body.append(f'<text class="m" x="{(left + w - right) / 2}" y="{bottom + 34}" text-anchor="middle">jobs moved</text>'
                f'<text class="m" x="16" y="{top - 8}">exposure vs ε = 0</text>')
    for key, cls, lcls, _ in series:
        p = pts[key]
        d = " ".join(f"{'M' if i == 0 else 'L'}{sx(x)},{sy(y)}" for i, (x, y, _) in enumerate(p))
        body.append(f'<path class="{lcls}" d="{d}" fill="none" stroke-width="2"/>')
        labels: dict[tuple, list[str]] = {}
        for x, y, e in p:
            body.append(f'<circle class="{cls} ring" cx="{sx(x)}" cy="{sy(y)}" r="5"/>')
            labels.setdefault((x, round(y, 1)), []).append(f"{e:g}")
        placed: list[tuple[float, float]] = []
        for (x, y), es in labels.items():  # coincident points share one label
            lx, ly = sx(x) + 8, sy(y) - 8
            if any(abs(ly - py) < 14 and abs(lx - px) < 90 for px, py in placed):
                ly = sy(y) + 18  # crowded: put this label under its point
            placed.append((lx, ly))
            body.append(f'<text class="m" x="{lx}" y="{ly}">ε {", ".join(es)}</text>')
    return svg(w, h, "Stability vs risk: what ε buys on the demo scenario", body,
               "Raising epsilon moves fewer jobs at a bounded increase in exposure.")


# ---- perception ----------------------------------------------------------------------------------------------

def perception() -> str:
    """Pixel precision and recall for each SAM variant (dev unless marked test)."""
    variants = []

    def add(label: str, scores: dict) -> None:
        variants.append((label, scores["pixel"]["precision"], scores["pixel"]["recall"],
                         scores["image"]["detection_rate_on_positives"]))

    add("SAM 'rust' (test)", json.loads((RESULTS / "sam_test_rust.json").read_text(encoding="utf-8"))["scores"])
    for f, label in (("sam_tiling_dev_grid1_rust.json", "SAM 'rust' (dev)"),
                     ("sam_tiling_dev_grid2_rust.json", "2×2 tiles (dev)"),
                     ("sam_tiling_dev_grid1_rust+corrosion+rust_stain.json", "3-prompt union (dev)")):
        add(label, json.loads((RESULTS / f).read_text(encoding="utf-8"))["scores"])
    box_dev = json.loads((RESULTS / "box_prompt_dev.json").read_text(encoding="utf-8"))["variants"]
    add("+ Muse Spark boxes (dev)", box_dev["text_plus_boxes"])
    test_box = RESULTS / "box_prompt_test.json"
    if test_box.exists():
        add("+ Muse Spark boxes (test)", json.loads(test_box.read_text(encoding="utf-8"))["variants"]["text_plus_boxes"])
    verified = RESULTS / "box_verify_test.json"
    if verified.exists():
        add("+ boxes + verifier (test)",
            json.loads(verified.read_text(encoding="utf-8"))["variants"]["text_plus_boxes_verified"])
    w, left, top, bar_h, gap = 720, 200, 78, 12, 2
    group = 2 * (bar_h + gap) + 14
    scale = (w - left - 120)
    h = top + group * len(variants) + 40
    body = [f'<text class="m" x="20" y="48">Pixel-level precision and recall against annotated rust · image '
            f'detection rate in brackets</text>'] + legend(20, 66, [("s1", "precision"), ("s2", "recall")])
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + v * scale
        body.append(f'<line class="g" x1="{x}" x2="{x}" y1="{top - 6}" y2="{top + group * len(variants) - 10}"/>'
                    f'<text class="m" x="{x}" y="{top + group * len(variants) + 6}" text-anchor="middle">{v:.2f}</text>')
    for i, (label, p, r, det) in enumerate(variants):
        y0 = top + i * group
        body.append(f'<text class="t" x="{left - 12}" y="{y0 + bar_h + 4}" text-anchor="end">{escape(label)}</text>')
        for j, (val, cls) in enumerate(((p, "s1"), (r, "s2"))):
            y = y0 + j * (bar_h + gap)
            body.append(hbar(left, y, val * scale, bar_h, cls) +
                        f'<text class="m" x="{left + val * scale + 6}" y="{y + bar_h - 2}">{val:.2f}'
                        f'{f"  [{100 * det:.0f}%]" if j == 1 else ""}</text>')
    return svg(w, int(h), "Finding the rust: SAM 3.1 variants", body,
               "Muse Spark box proposals fed to SAM 3.1 raise pixel recall sharply at a moderate precision cost, "
               "and verification recovers part of the precision; tiling and prompt unions do not help.")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    charts = {"planner_improvement.svg": planner_improvement, "replan_moves.svg": replan_moves,
              "replan_pareto.svg": pareto, "perception_recall.svg": perception}
    for name, fn in charts.items():
        (OUT / name).write_text(fn(), encoding="utf-8")
        print("wrote", OUT / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
