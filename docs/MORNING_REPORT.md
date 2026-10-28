# Morning report: overnight autonomous run (2026-10-28 22:46 IST onwards)

## Summary

_In progress; updated after each item._

## Spend

Baseline at the start of the run (22:46 IST):

| Provider | Used before tonight | Tonight's cap | Hard stop |
|---|---|---|---|
| Meta | ≈ $77 | +$35 | $140 |
| Baseten | ≈ $67 | +$15 | $90 |
| Modal | ≈ $3.35 (billing report: $3.20 today) | +$70 | $90 |
| Fireworks | $0 | +$45 | $90 |

**How spend is measured:**
- Meta and Baseten: `benchmark/spend.py`, which sums the local cost ledger from the start of the run.
- Modal: `modal billing report`.
- Fireworks: deployment hours × list rate, plus ledger entries.

Tonight so far: see the item log below.

## Item log

| # | Item | Status | Key result | Spend |
|---|---|---|---|---|
| 1 | Muse Image false-alarm stress test (300 synthetic look-alike images, Cloud + On-prem) | DONE | Images with a false alarm, text → text+boxes → verified. Cloud: 15% → 40% → 26% (minimal) / 22% (low) / 27% (Muse Spark Open). On-prem: 14% → 21% → 15%. Without the 4 categories a person may read as rust staining: Cloud 5% → 23% → 9% / 6% / 8%; On-prem 4% → 6% → 2%. RESULTS §10 | Meta ≈ $0.9 tonight (+$0.8 earlier), Baseten ≈ $4.8, Modal ≈ $0.1 |
| 2 | False alarms on REAL public negatives (191 clean-pipe images), every verifier | DONE | Images with a false alarm. Cloud: text 4.2% → text+boxes 31.9% → minimal 12.0% / low 6.8% / Muse Spark Open 4.2%. On-prem pipeline: 3.1% → 19.4% → 2.1%. RESULTS §9 | Meta ≈ $0.03, Baseten ≈ $0.04 (most verdicts cached) |

## Resources at zero (checked after each job)

## Decisions waiting for the builder
