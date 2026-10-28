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
| 3 | FLUX.1-schnell training negatives + SAM candidates | DONE | 1,009 images (688 train / 321 tune, seeded split). Two fixes, both found by visual checks: (a) FLUX ignores "no rust" in the prompt and drew rusty metal, so prompts never mention rust (first 30 images set aside); (b) SAM "rust" masks on FLUX images landed on rust traces FLUX adds at seams and ladders, so candidates are now masks of the look-alike object itself ("orange arrow", "copper tube", "wooden plank", ...), true negatives by construction (first harvest set aside). Look-alike categories that render as rust (stains, drips, smudges, mud, dirt smears, wet patches) are excluded. Result: 2,890 look-alike candidates on 903 images; a 12-mask spot check shows all on look-alikes | Modal ≈ $1.0 (FLUX $0.72 + $0.13, SAM $0.23) |
| 4 | Verifier hardening (v2 prompt: look-alike checklist + texture evidence) | DONE: **not adopted** (v1 stays) | Hosted minimal: false-alarm candidates on real negatives 41 → 21 (−49%), Muse Image 281 → 178 (−37%), but audited real-rust recall 97.3% → 93.8% (−3.5 points, over the 3-point limit). Muse Spark Open: 12 → 10, recall −4.4 points. FLUX-tune gave no tuning signal (both prompts rejected all 188). RESULTS §11 | Meta ≈ $2.3, Baseten ≈ $2.3 |
| 6 | Box proposals on the 500-image On-prem test subset, with verification | **SKIPPED** (cost rule) | Real cost is ≈ $0.06/image, not ≈ $0.024. On-prem uses open-weights masks, so the cached Baseten verdicts (made on hosted masks) cannot be reused and every merged candidate (~5.6/image) needs verifying. 500 images ≈ $30, more than 50% over the $12 estimate and over tonight's Baseten cap. Decision for the morning | $0 |
| 7c | Muse Spark Open: Fireworks serverless vs Baseten (100 test candidates) | DONE | 97.0% same decisions, severity 72.7% exact / 99.0% ±1, invalid 1 vs 0, latency 28 s vs 11 s, cost $0.0090 vs $0.0083 per candidate. RESULTS §6 | Fireworks ≈ $0.95 |
| 7a | Fireworks zero-shot Glimmer baseline (on-demand deployment) | **BLOCKED** | Fireworks: HTTP 400 "payment method is required" for on-demand deployments (serverless works on credits). Per the rules, Fireworks deployment jobs stopped; confirmed no deployments exist; $0 billed. Glimmer zero-shot and tuned evaluation moved to Modal (batched, same inputs) | $0 |
| 5 | Glimmer stage 3 training (Modal H100, QLoRA r=16) | DONE | 1,654 balanced examples (827 teacher accepts; 86 real + 741 FLUX-train look-alike rejections), 2 epochs completed in 76 min, 884 tokens/s, loss 1.64 → 0.39. Adapter in the private Modal volume (never published). App stopped, 0 containers | Modal ≈ $5.04 (cap $15) |
| 8 | Stock demo clips through the pipeline (6 Pexels clips, Cloud) | DONE | valve-tank: 11 entries, 2 jobs, OPTIMAL; vessel: 11 / 1 / OPTIMAL; tank-farm: 17 / 2 / OPTIMAL; rusty-pipe: 12 / 3; welded-pipes: 16 jobs FEASIBLE 4% on the first run; **clean piping: 0 entries** (no false alarm). Recommended: valve-tank + clean-piping (+ vessel as backup). Notes in DEMO_SCRIPT. Masks not yet checked by eye; repeat runs are not fully cached (the agent picks new frames) | Meta ≈ $2.4 |

## Resources at zero (checked after each job)

## Decisions waiting for the builder

- **Fireworks on-demand deployments need a payment method on the account** (HTTP 400). Add one if you want the Fireworks Glimmer evaluation or serving; serverless inference works without it.
- **Item 6 (On-prem box proposals on the test split):** ≈ $0.06/image with verification. Options: a 100-image subset (≈ $6), or proposals without verification on 500 images (≈ $6, unverified perception metrics only).
- **Verifier false alarms vs recall.** v2 prompt (−49% false alarms, −3.5 points recall) or Cloud at low effort (§9: 12.0% → 6.8% of clean images) or keep minimal. All are measured; the rule kept v1 + minimal.
