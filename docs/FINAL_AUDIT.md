# Final audit before the demo video (2026-11-04)

The final pre-submission check: security, the live product, code and build, numbers, credits and submission.
Every check names its proof. The fixes are in commits 1e23a96, b04ddd7, a5de2a6, d627369, 3d7c533 and the commit
that adds this file.

## Numbers and claims: one source of truth each

`results/` means `benchmark/results/`. "§n" is a section of `benchmark/RESULTS.md`.

| Claim | Where it appears | Source | Matches? | Fix |
|---|---|---|---|---|
| High recall: audited recall 97.3% (110 / 113), clean images flagged 12.0% (23 / 191) | README, RESULTS §8 §9 §11 §16, UI (picker, headline), DEMO_SCRIPT, `backend/verify/sensitivity.py` | `results/verifier_hardening_eval.json` (meta-minimal v1: tp 110, fn 3; public images_with_alarm 23 of 61 candidate images, of 191), `results/negatives_fp_public_cloud.json` (accepted 0.1204) | yes | – |
| Balanced: 93.8% (106 / 113), 6.8% (13 / 191) | README, RESULTS §11 §16, UI | `verifier_hardening_eval.json` (meta-minimal v2: tp 106; images_with_alarm 13) | yes | – (§9's low-effort 6.8% is also 13 / 191; two settings, same count) |
| On-prem: 95.6% (108 / 113), 2.1% (4 / 191) | README, RESULTS §9 §11 §16, UI | `verifier_hardening_eval.json` (baseten-low v1: tp 108); `results/negatives_fp_public_on-prem.json` (0.0209) | yes | – |
| On-prem image detection 92.4%, pixel P/R 0.78 / 0.62 | README, RESULTS §7 summary | `results/onprem_test.json` (open_text_plus_boxes_verified; RESULTS row 0.779 / 0.620) | yes | – |
| Cloud 97.9%, pixel P/R 0.77 / 0.84 (1,444 test images) | README, RESULTS §4 §7, DEMO_SCRIPT | `results/box_verify_test.json` (effort low) | yes, but the verifier ran at **low** effort | README and RESULTS labelled it "Cloud default", while the product default is minimal effort. They now say "verifier at low effort" |
| SAM 3.1 text only: 66%, pixel precision 0.92, 36% pixel recall | README, RESULTS §4 | RESULTS §4 table (65.6%, 0.92 / 0.36) from `results/box_prompt_test.json` | yes | – |
| Glimmer v2: −39% clean-pipe images with an alarm (28 → 17), recall 94.7%, not adopted; "about 2× the teacher" (17 vs 8) | README, RESULTS §14 summary, DECISIONS | RESULTS §14 v2 table, from `results/glimmer_eval.json` and `results/glimmer_train_v2.json` | yes (17/28 = −39.3%; 107/113 = 94.7%) | – |
| Glimmer v1 and Fireworks LoRA keep 99.1% (112 / 113) | README, RESULTS §14 | RESULTS §14 tables | yes | – |
| F7: 50 / 50 runs, 16 replans, median 143 s, $0.19 per run | README, RESULTS §15 | `results/f7_live_runs.json` (success 1.0, replan_runs 16, wall median 142.65 s, usd median 0.192) | yes | – |
| Audits: 100 text-prompt + 50 box-only = 150 candidates, 133 sure labels, 113 real rust | RESULTS §8, README ("133 candidates"), sensitivity.py | `results/audit_eval.json` (89 sure of 100), `results/audit_boxes_eval.json` (44 sure of 50) | yes | The sensitivity.py docstring read as if 113 = 100 + 50; reworded |
| 91–93% of accepted candidates are real rust | README | RESULTS §8 combined (precision 91.4% / 92.1% / 92.6%) | yes | – |
| 84% of dataset "false positives" are rust to a person | README, RESULTS §8 | RESULTS §8 (26 of 31 sure) | yes | – |
| 191 real negatives | README, RESULTS §9, FOOTAGE_SOURCES, UI | `results/negatives_public_manifest.json`, `negatives_fp_public_*.json` (images 191) | yes | – |
| Dev 50 / test 1,444 split | README, RESULTS §1 | `benchmark/splits/dev.txt` (50 lines), `test.txt` (1,444 lines) | yes | – |
| Muse Spark Open agrees with hosted on 93.4% of 5,066 decisions | README, RESULTS §6, DEMO_SCRIPT | RESULTS §6 (after the 92-reply retry); `results/verify_scale_test_baseten_low.json` (5,066 candidates) | yes | – |
| SAM 3 full fine-tune: negative result | README, RESULTS §18 | RESULTS §18: NaN at step ≈ 305 / ≈ 385 (bf16), matcher error at step ≈ 15 (fp32) | **no** | README said "NaN after about 300 steps at any learning rate or precision"; now "non-finite values after 15 to about 385 steps at every learning rate and precision tried" |
| CP-SAT never worse on 60 scenarios; median 5.8% (default), up to 24.9%; DEMO_SCRIPT "1–7.5% by regime" | README, PLANNER_RESULTS, DEMO_SCRIPT | `benchmark/PLANNER_RESULTS.md` table (medians 1.0–7.5, max 24.9; 60 runs) | yes | – |
| Replan moves 7 vs 13 jobs (median) | README, PLANNER_RESULTS | PLANNER_RESULTS replan table (tight_capacity, crew_unavailable) | yes | – |
| Muse Wonder: agreement 73.5% → 72.7% | README, DEMO_SCRIPT | RESULTS §5 | yes | – |
| Tank-farm demo run: 24 entries, 9 need review, 14 jobs, 22 setup hours saved, replan moves 4, gap 0.4% | DEMO_SCRIPT | Live run 2026-11-04 (run-3f22f95691), CSV export | yes | Senior reviews: DEMO_SCRIPT said 8; the current run shows 14. Updated |
| Clean-piping: 0 entries | DEMO_SCRIPT, sample card | Live run 2026-11-04: 0 entries in 16 s | yes | – |

## Deployment

| Check | Proof |
|---|---|
| No out-of-memory event | Render Events (36 events) list deploys only; Render logs over the last 2 days have no line matching "memory" |
| No restart on 11-03 between 10:20 and 10:30 | Server starts at 10:02:11 and 10:40:48; the 10:40 start is the manual redeploy (Events: "Manually triggered by you via Dashboard", 10:39) |
| Cold start | The waking notice appeared on the public site; the app was ready about 58 s after page load (curl: 53 s) |
| Auto-Deploy is on | Events show "New commit via Auto-Deploy"; every push restarts the API and clears runs. Turning it off is a hosting-settings change for the builder |
