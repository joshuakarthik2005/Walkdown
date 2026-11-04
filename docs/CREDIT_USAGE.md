# Credit usage report (as of 2026-11-04)

Every free credit pool Walkdown used, what it was spent on and what it produced. Each figure names its source:

- **dashboard (2026-11-01)**: the provider's billing page, read by the builder on 2026-11-01 (also in `docs/COST_LOG.md`).
- **CLI (2026-11-04)**: `modal billing summary` / `modal billing report`, run during the final audit.
- **ledger**: Walkdown's own cost ledgers, written from each call's `usage` at official list prices
  (`G:/walkdown-data/runs/cost_ledger.jsonl`, one ledger per clip, the F7 journal, the demo spend-guard files).
  A ledger figure is an estimate. Where a dashboard figure exists, the dashboard wins.
- **UNVERIFIED**: no dashboard reading for today. The builder chose to use the 2026-11-01 snapshot instead of new
  dashboard readings.

## Summary

| Pool | Granted | Used | Remaining | % used (target 80%) | Source of "used" |
|---|---|---|---|---|---|
| Meta Model API | $150.00 | $105.54 on 2026-11-01; ≈ $106.7 today | $44.46 on 2026-11-01; ≈ $43.3 today | 70.4% (≈ 71% today) | dashboard (2026-11-01); today = dashboard + ledger, UNVERIFIED |
| Baseten (Muse Spark Open) | $100.00 | ≈ $73.64 | ≈ $26.36 | ≈ 74% | ledger (no billing access for the hackathon key; API answers 403) |
| Fireworks | $100.00 | ≈ $83.16 | ≈ $16.84 | ≈ 83% | ledger + Glimmer job logs (no billing API: 404) |
| Modal | $100 hackathon credit + $30/month free credit | $32.14 metered in October (covered: credits $32.06 + egress allowance $0.08); $0.28 in November (storage, covered by free storage) | $127.94 balance on 2026-11-01 | 24.7% of the $130 available in October | CLI (2026-11-04); balance from dashboard (2026-11-01) |
| Hugging Face | free account | $0 | – | – | free plan (private dataset for the demo bundle) |
| Render | free web service | $0 | – | – | free plan, no card on file |
| Vercel | Hobby | $0 | – | – | Hobby plan, no card on file |

**Total free credit used across the four paid pools: ≈ $294.5** (Meta $105.54 dashboard + Baseten ≈ $73.64 +
Fireworks ≈ $83.16 + Modal $32.14).

- **Meta ($105.54):** every Cloud number in the README. That covers the 1,444-image test split end to end, the human
  audits, the public-negatives and Muse Image stress tests, the Muse Wonder study, 50 live agent runs, and every demo
  and example run.
- **Baseten (≈ $73.64):** the open-weights verifier on all 5,066 test candidates (93.4% agreement with hosted). It
  also paid for the On-prem false-alarm test (2.1%) and the Muse Spark Open teacher labels for the Glimmer
  distillation.
- **Fireworks (≈ $83.16):** the full 1,444-image On-prem benchmark (92.4% image detection, pixel P/R 0.78/0.62),
  the host comparison, and the Glimmer LoRA evaluation (training was free under a promotion).
- **Modal ($32.14):** SAM 3.1 open weights for On-prem mode, the FLUX look-alike negatives, both Glimmer QLoRA runs,
  and the SAM 3 fine-tune attempt (a negative result).

Below 80%: Meta (70%), Baseten (74%) and Modal (25%). The budget rule was "target $50–70 of Meta, hard stop $120", so
the remaining Meta credit was kept as a buffer for the public demo (daily cap $5) rather than spent to reach a quota.

## Meta Model API, by purpose (ledger, list prices)

| Dates (IST) | Purpose | Models | Amount | What it produced |
|---|---|---|---|---|
| 10-27 | Development, smoke tests, SAM prompt dry runs ("corrosion", "corroded metal") | muse-spark-1.3, sam-3.1 | $0.30 | Request formats checked; prompt choice (RESULTS §1) |
| 10-27 | SAM 3.1 text prompt on dev 50 + test 1,444 | sam-3.1 | $3.74 | RESULTS §1 (66% image detection) |
| 10-27 | Recall experiment: tiling and prompt unions (dev) | sam-3.1 | $0.63 | RESULTS §3 (negative result) |
| 10-27 – 10-28 | Verifier at scale: 5,066 text candidates, 5,385 box candidates, dev studies, 100-candidate audit verdicts | muse-spark-1.3 | $45.57 | RESULTS §2, §4, §8 |
| 10-27 – 10-29 | Box proposals + SAM box prompts (dev design, test run, incl. the run before the clamp fix) | muse-spark-1.3, sam-3.1 | $10.58 | RESULTS §4 (97.9% image detection) |
| 10-28 | Muse Wonder senior review on 528 escalated candidates | muse-wonder-1.0 | $8.32 | RESULTS §5 (no accuracy gain; kept as a second opinion) |
| 10-28 | False alarms on 191 public negatives (Cloud, every verifier) | sam-3.1, muse-spark-1.3 | $7.06 | RESULTS §9 (12.0% / 6.8%) |
| 10-28 | Muse Image look-alike stress set, evaluation only (300 images) | muse-image-1.0 | $3.00 | RESULTS §10 |
| 10-29 | Verifier hardening v1/v2 prompts | muse-spark-1.3 | $2.60 | RESULTS §11; the Balanced setting (93.8% / 6.8%) |
| 10-29 | Medium reasoning effort study | muse-spark-1.3 | $9.13 | RESULTS §12 (did not pay off) |
| 10-29 – 10-31 | F7: 50 live end-to-end agent runs | muse-spark-1.3, sam-3.1, muse-wonder-1.0 | $10.70 | RESULTS §15 (50/50; found the video-tracking bug) |
| 10-27 – 11-02 | Other agent runs: dev clip, stock-clip trials, demo cache, finished examples, voice note, UI checks | all of the above, muse-voice-transcribe-1.0 | $4.34 | Demo clips, examples, RESULTS §19 |
| **10-27 – 11-02** | **Ledger total** | | **$105.91** | |
| 11-03 | Deploy memory probes and public smoke test | muse-spark-1.3 (cached perception) | ≈ $0.37 | docs/DEPLOY.md |
| 11-04 | Final audit: 6 live demo runs (samples, own photos, own video, Balanced), a replan, copilot questions, a voice note | Meta | ≈ $0.62 | This audit |
| | Public demo traffic from visitors | Meta | not separable | The demo spend-guard caps it at $5 per day |

**Reconciliation.** The ledger through 11-02 is $105.91; the dashboard read $105.54 on 2026-11-01. About $0.2 of the
ledger's 11-01/11-02 lines came after the dashboard reading. That leaves **≈ $0.2 unattributed**, ledger above
dashboard. It is most likely list-price rounding and cached-token pricing in the ledger estimate. An earlier
COST_LOG note put the ledger ≈ $4.5 above the dashboard, but that figure included hand-added COST_LOG lines
that are also in the ledger; the per-call ledger is the cleaner figure.

## Baseten (Muse Spark Open), by purpose (ledger)

| Dates | Purpose | Amount | What it produced |
|---|---|---|---|
| 10-27 – 10-28 | Open-weights verifier on all 5,066 test candidates (incl. the dev dry runs and the 92-reply retry) | ≈ $47.55 | RESULTS §6 (93.4% agreement) |
| 10-28 | Teacher labels: 1,309 open-weights candidates on the clean train pool | ≈ $10.95 | Glimmer distillation data (RESULTS §14) |
| 10-28 | False alarms on 191 public negatives, On-prem (box proposals + verifier) and the all-verifier run | $11.57 | RESULTS §9 (2.1%) |
| 10-28 | On-prem box proposals, dev check (50 images) | $0.60 | RESULTS §7 |
| 10-28 | On-prem agent runs on the dev clip (F2) | $0.63 | RESULTS §7, On-prem mode |
| 10-29 | Verifier hardening v2 with Muse Spark Open | $2.35 | RESULTS §11 |
| | **Ledger total** | **$73.64** | |

COST_LOG's hand total was ≈ $75.4. It adds about $1.0 for the box-only audit fill and ≈ $0.7 of F2 and agent
estimates that partly overlap the ledger. **Unattributed: up to ≈ $1.8** (no Baseten dashboard to settle it).

## Fireworks, by purpose (ledger and job logs)

| Dates | Purpose | Amount | What it produced |
|---|---|---|---|
| 10-29 | Muse Spark Open on a second host: 100 test candidates | $0.90 | RESULTS §6 (host comparison) |
| 10-29 – 10-31 | On-prem full test split: box proposals ($17.11) and verification ($64.26) on 1,444 images | $81.37 | RESULTS §7 (92.4%, pixel P/R 0.78 / 0.62) |
| 10-29 | On-demand deployment probe (refused: a payment method is required) | $0.00 | Decision: no Fireworks deployments |
| 10-31 | Glimmer LoRA, Serverless Training: training $0 (promotion); evaluation sampling on 318 rows | $0.89 | RESULTS §14 (99.1% audited recall) |
| | **Total** | **$83.16** | |

## Modal, by app (CLI billing report, 2026-10-05 to 2026-11-05)

| Dates | App | Amount | What it produced |
|---|---|---|---|
| 10-28 | walkdown-sam31: SAM 3.1 open weights (probes incl. a crash loop, teacher masks, negatives, F2) | $2.46 | On-prem perception; teacher labels |
| 10-29 | walkdown-sam31: On-prem test-split SAM calls | $1.05 | RESULTS §7 |
| 10-28 | walkdown-flux: FLUX.1-schnell look-alike negatives | $1.04 | Training negatives (Glimmer, SAM 3 attempt) |
| 10-28 | walkdown-glimmer: weights to volume, Glimmer v1 QLoRA training and evaluation, the orphaned H100 | $13.16 | RESULTS §14 (v1) |
| 10-31 | walkdown-glimmer: Glimmer v2 training and evaluation, plus the cancelled first attempt | $12.34 | RESULTS §14 (v2: −39% clean-pipe alarms, 94.7% recall, not adopted) |
| 10-31 | walkdown-sam3ft: SAM 3 base evaluation and 9 fine-tune attempts (non-finite values) | $2.09 | RESULTS §18 (negative result) |
| | Network egress | $0.08 | – |
| | **October metered** | **$32.14** | Covered by credits ($32.06) and the egress allowance ($0.08) |
| 11-01 – 11-04 | Volume storage | $0.28 | Covered by free storage |

The local Modal ledger has only $2.53, because GPU training jobs were not ledgered per call. The CLI billing report is
the source here; there is **no unattributed Modal spend**.

## Failed or wasted spend, and what it led to

| Pool | What | Amount | Lesson / safeguard |
|---|---|---|---|
| Modal | Orphaned H100: the local memory guard killed the client during model load; the remote GPU ran 21:06–21:09 IST until stopped | ≈ $0.2 | Every GPU job runs `modal run --detach` with a hard timeout; apps and containers are checked after every job |
| Modal | Crash loop on a missing dependency (`psutil`, 13 container starts) | $0.06 | A CPU import check before any GPU run |
| Modal | SAM 3 full fine-tune: 9 attempts, all ended in non-finite values | $2.09 | Stopped at 9 attempts under a $25 cap; reported as a negative result; SAM 3.1 kept |
| Modal | Glimmer v2 first attempt, cancelled when the guard killed the local client | ≈ $1.7 | Long jobs are spawned on the deployed app, not tied to a local client |
| Baseten | 55 images run at max_tokens 8,000, set aside and redone at 4,000 so all candidates share one setting | $3.84 | One token setting per benchmark; retries only for invalid replies |
| Meta | Medium-effort study: no gain over minimal/low | $9.13 | Verification stays at minimal (High recall) |
| Meta | Box-proposal run before the box clamp fix | part of $10.58 (not separable) | Boxes are clamped to the image before SAM |
| Meta | A finished-example build with a broken clip loader | $0.03 | Example round-trip test (`tests/test_demo.py`) |
| Meta | F7: 4 runs paid a crashing `track_video` call again on every run | < $0.05 | Bug fixed with a test; found because F7 ran live |
| Fireworks | Deployment probe | $0.00 | Refused without a card; no deployments used |
