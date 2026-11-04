# Demo video script (3:00) and X cut (30–45 s)

Rules for both videos:
- Show only what was built during the hackathon.
- Every on-screen number must come from `docs/IMPACT_SOURCES.md` (Verified) or `benchmark/RESULTS.md` / `PLANNER_RESULTS.md`.
- Footage and screenshots come from the builder's own recordings. If those are not enough, use the checked stock clips (below), captioned **"stock demonstration footage"**. **No dataset images anywhere** (DECISIONS.md, rights rule).
- Use a cached demo clip, so the run is fast and repeatable. Say once, on screen, that it is cached; the live flag exists.
  - The three demo clips use a **fixed frame grid** (`fixed_sampling` in each clip's `clip.json`), so the agent segments the same frames on every run and the register is identical between runs (checked: three tank-farm runs, identical 24-entry register).
  - All timings below were measured on 2026-11-01 from a fresh start of backend and frontend, in Cloud mode, cached.

Legend: **[BUILT]** = built during the hackathon (Oct 27 – Nov 4, 2026). **[META]** = a Meta model called through the API (third-party, used, not built). **[LIB]** = an open-source library used.

---

## 0:00–0:30 · Problem and impact

| Time | On screen | Voice-over (approx.) | Source |
|---|---|---|---|
| 0:00–0:08 | Builder's own footage: walking past corroded plant piping, a tank base, a valve. Title: "Walkdown" | "Every day, technicians walk plants (refineries, tank farms, terminals, power plants) looking for corrosion." | builder footage |
| 0:08–0:20 | Text card: **"Corrosion costs an estimated US$2.5 trillion a year, about 3.4% of global GDP"** · "15–35% of that is avoidable with existing practice" | "Corrosion is one of the most expensive problems in industry, and much of it is avoidable." | NACE IMPACT 2016, p.3 (V1, V2) |
| 0:20–0:30 | Text card: "Chevron Richmond, 2012: a corroded pipe ruptured; 19 workers endangered, more than 15,000 residents sought medical attention" | "And when it's missed, people get hurt. Today the findings live in notes and spreadsheets, and the plan is made by hand." | CSB release, Jan 2015 (V4) |

Do not add other numbers in this section. C1–C5 in IMPACT_SOURCES are not verified.

## 0:30–2:30 · Live run (the agent is the product)

### Before recording (about 5 min)

1. Start the API: `.venv\Scripts\python -m uvicorn backend.api.app:app --port 8000` (ready in about 2 s).
2. Start the UI as a production build (no dev badge): `cd frontend && npm run build && npm run start`, then open http://localhost:3000. Optionally start the API with `DEMO_MODE=true` to show the public-demo behaviour (cached samples, On-prem runs off).
   - Record on localhost. The public demo (https://walkdown-zeta.vercel.app/, docs/DEPLOY.md) runs on a free 0.1-CPU server, where a run takes about a minute and the individual-defect plan reaches a larger gap within the time limit.
3. Do one full rehearsal of the click path below on `stock-tank-farm`, so every cache is warm, then open http://localhost:3000/?sample=stock-tank-farm.
4. Keep `G:\walkdown-data\footage\voice_note_01.m4a` ready for the file dialog (the upload also takes WAV and mp3). Its transcript and fields are cached, so attaching it costs nothing and takes under a second.

### Click path with measured timings

Real time is what the screen shows. Two waits (the run and the replan) are long for a 3-minute video: record them in real time and speed them up in the edit, with a small "sped up" caption.

| Video time | Click / action | Real time | What appears (measured on the rehearsal run) | Voice-over (approx.) | Built? |
|---|---|---|---|---|---|
| 0:30–0:38 | The landing page shows **Try a sample walkdown**; the **Tank farm pipe rack** card is selected (its credit line reads "Stock footage: Mumtaz Niazi / Pexels"). Point at the headline **Audited recall 97.3%** and at **Detection sensitivity: High recall (default) · recall 97.3% · clean images flagged 12.0%**. Leave **Cloud** selected. Click **Run the agent**. | 5 s | Caption: "stock demonstration footage". | "Here's a walkdown of a tank farm. I hand it to the agent." | UI, sensitivity setting **[BUILT]** |
| 0:38–1:00 | Watch **The agent** flow fill in. | 51–56 s (show at ≈ 2.5×) | "Tracks the clip" (SAM 3.1 video), "Looks at the clip" (24 frames, text + boxes), "Checks each finding" ×3 (Muse Spark; 14 senior reviews by Muse Wonder on the 2026-11-04 check), "Writes the defect register: 24 entries, 9 need review", "Plans the repairs" (≈ 30 s, the slow step), "Reads the planner's reasons". Header: run cost ≈ $0.04. | "The agent decides what to look at. SAM 3.1 tracks rust through the video and Muse Spark proposes boxes it missed. Muse Spark checks every finding, rejects look-alikes and grades severity with evidence. Severe or uncertain calls get a second opinion from Muse Wonder; where they disagree, a human decides." | Agent loop, tools, trace **[BUILT]** · SAM 3.1, Muse Spark, Muse Wonder **[META]** |
| 1:00–1:20 | Scroll to **Verified defect register**: frames with masks, rows with type, severity, evidence, action; point at a **second opinion** badge and a **disputed: needs human review** row. Click **Attach a voice note (WAV, m4a, mp3)** and pick `voice_note_01.m4a`. | under 1 s for the note | 24 entries on STOCK-TANK-FARM, crude service; 18 candidates rejected as false positives. The **Inspector note** appears under the table: 12 s, tag P-401, LPG service, "coating damage near the flange", follow-up "check for corrosion under insulation". | "Every finding becomes a register entry with its evidence. The inspector adds a voice note from their phone: a note from the same walkdown, on a nearby LPG line. Muse Voice Transcribe and Muse Spark turn it into a tag, a service and a follow-up." | Register, overlays, voice-note extraction **[BUILT]** · Muse Voice Transcribe **[META]** |
| 1:20–1:40 | Scroll to **Repair plan the agent produced**. Click **Individual defects**, then **Grouped jobs (used)**. Hover a package bar. | instant | Grouped: **OPTIMAL, gap 0.0%**, 14 jobs, 22 setup hours saved. Individual: **FEASIBLE** with a gap (16–18% on the rehearsal runs; it varies with the 30 s time limit), 36 jobs. The reason line says why grouped was used. | "It merges the new defects into the plant's backlog and schedules them with a constraint solver: crews, permits, shutdown windows, risk weighted by what the line carries. Grouping nearby defects saves 22 setup hours, at a risk cost it shows instead of hiding. It only says optimal when the solver proved it." | CP-SAT model, adaptive work packages **[BUILT]** · OR-Tools **[LIB]** |
| 1:40–2:05 | Panel **Something changed on site?**: Change = **Crew becomes unavailable**, current hour **24**, crew **C1 · coating, insulation**, **72** hours, slider **ε = 0.02**. Click **Replan**. | 40 s (show at ≈ 3×) | Flow adds "Replans after the change: OPTIMAL, 14 scheduled, 0 unscheduled, 4 moved". Header: "risk: OPTIMAL, stability: OPTIMAL", gap 0.4%. | "A coating crew is out for three days. The agent replans: started work stays fixed, it finds the lowest-risk plan, then moves as few jobs as possible. The 0.4% is the risk it accepts to keep the plan stable, inside the 2% this slider allows." | Two-stage replan, ε control **[BUILT]** |
| 2:05–2:15 | Point at **What the agent concluded · after change 1**. | – | "C1 unavailable hours 24–96 forced replan…", WP1 and WP2 with their delay reasons (outside_shift, crew_unavailable), moved jobs D05, D08, WP1, WP2. | "And it explains why, using only the solver's own reasons." | Structured explanations **[BUILT]** |
| 2:15–2:25 | **Ask about the register or plan**: type "Why is W09 waiting?", press Enter. | 7–10 s (show at ≈ 2×) | "W09 … is repaired as part of group WP2 … scheduled with Crew A from hour 106 … waiting because: outside shift, crew unavailable (hours 24–96), deferred by optimiser … plan status OPTIMAL with gap 0.0038", with the tools it used listed. | "Inspectors can ask follow-up questions, answered only from the register and the plan." | Inspector copilot **[BUILT]** |
| 2:25–2:30 | Click **Inspection report (PDF)**. | 1.7 s | A 3-page PDF report; the work orders (CSV, JSON) are next to it. | "And export the report and work orders for approval." | PDF, CMMS-style export **[BUILT]** |

**False-alarm beat** (optional; use in 2:30–2:45 or cut): click **Choose another walkdown**, pick the **Clean painted piping** card, **Run the agent**. 10–14 s, ≈ $0.006: "Found no corrosion … 0 candidates, register empty". Voice-over: "On clean painted piping, the register stays empty." Do not claim a rate from this: the measured rate is in RESULTS §9 (12.0% of clean-pipe images flagged at High recall).

**Instant fallback:** if a live run misbehaves while recording, click **or open the finished example (instant)** under the Run button: it loads the recorded tank-farm run with the voice note and the crew-out replan already done (`?example=tank-farm`).

**Backup clip:** `stock-valve-tank` (the **Valve at a tank bottom** card), same click path; 50–52 s per run, 21 entries. Use it only if tank-farm fails; its lichen and worn-paint flags are questionable, so present them as "needs human review" examples.

**Measured cost of one full rehearsal** (run + voice note + replan + copilot + PDF): ≈ $0.06 of Meta credit.

Demo prerequisites (all **[BUILT]**):
1. Warm the cache for a new clip with `python -m backend.agent.warm_cache <clip_id>`; the three demo clips are already warm.
2. Rehearse the full flow with `python -m backend.agent.rehearse <clip_id>`.
3. Check the overlays by eye: `G:/walkdown-data/demo_checks/NOTES.md`.

## 2:30–3:00 · Results and what it unlocks

| Time | On screen | Voice-over | Source |
|---|---|---|---|
| 2:30–2:45 | Two cards: **"In a blind human audit, 91–93% of what the verifier accepts is real rust; at the default setting it keeps 97% of real rust"** (n = 133 and 113); **"CP-SAT is never worse than a severity-sort baseline across 60 scenarios; median improvement 1–7.5% by regime"** | "We measured it honestly, against human labels. The default favours not missing rust; a Balanced setting halves false alarms on clean pipe, at a small recall cost." | RESULTS.md §8; DECISIONS (sensitivity); PLANNER_RESULTS.md |
| 2:45–2:52 | Card: "Assists inspectors, does not replace them." plus the measured recall line from RESULTS.md §4 (measured: SAM text prompt alone finds corrosion on 66% of test images; text + Muse Spark boxes + verification at low effort 98%, covering 84% of annotated area). | "It doesn't replace inspectors; it makes their walkdown count." | RESULTS.md §1, §4 |
| 2:52–2:56 | Flip the **Cloud / On-prem** switch. Card: "On-prem mode: the same agent, box proposals and verifier on Muse Spark Open, SAM 3.1 open weights · Built with Muse Spark Open · same decision as hosted Muse Spark on 93.4% of 5,066 checks · flags 2.1% of clean-pipe images". | "And it runs on open weights too, for plants that can't send footage to the cloud." | On-prem mode **[BUILT]** · Muse Spark Open via Baseten **[META, open weights]** |
| 2:56–3:00 | Card: "Walkdown · plant walkdowns → verified register → optimal plan · github.com/joshuakarthik2005/Walkdown" | "Walkdown." | |

Placeholders marked "fill in" must be replaced with measured numbers before recording; drop the line if the number is not measured.

Never say "replaces inspection", "detects all corrosion", or anything about drones or robots working today, or about cross-country pipelines (those use in-line inspection).

---

## X cut (30–45 s)

1. **0–5 s:** builder footage, walking a pipe rack. Caption: "A plant walkdown, filmed on a phone."
2. **5–15 s:** UI time-lapse of the agent decision flow filling in. Caption: "An AI agent finds the rust, checks every finding…"
3. **15–25 s:** register frames with masks, then the Gantt, badge **Optimal**. Caption: "…and schedules the repairs, proven optimal."
4. **25–38 s:** cancel the shutdown → Replan → moved jobs → the explanation line. Caption: "Shutdown cancelled? It replans and explains why."
5. **38–45 s:** card: "Walkdown · built on SAM 3.1, Muse Spark, Muse Wonder and Muse Spark Open (Meta) · Built with Muse Spark Open · decision support, human approval required · #MetaHackathon · repo link".

Same rules: no dataset images, numbers only from verified sources, nothing claimed beyond what's shown.

**Wording rule for Muse Wonder (builder decision, 2026-10-28):** describe it as a second opinion that surfaces disagreements to a human. Never say it improves accuracy: on the test split, label agreement was 73.5% before and 72.7% after the review (benchmark/RESULTS.md section 5).

## Stock demonstration footage fallback (overnight item 8, 2026-10-29)

Use these only if the builder's own footage is not enough. On screen and in the README they are labelled **"stock demonstration footage"** (Pexels; authors and licence in `docs/FOOTAGE_SOURCES.md`). Clips are downscaled to 1,280 px and cut to ≤ 20 s, stored on G: as Walkdown clips, and run with the agent in Cloud mode at minimal effort (`benchmark/stock_clips.py`, `benchmark/results/stock_clips.json`).

| Clip id | Content | Register entries | Walkdown jobs | Plan | First run / repeat run cost |
|---|---|---|---|---|---|
| `stock-valve-tank` | Old fuel-transfer valve under a tank | 11 | 2 | OPTIMAL | $0.24 / $0.16 |
| `stock-vessel` | Corroded horizontal vessel shell (vertical video) | 11 | 1 | OPTIMAL | $0.24 / $0.02 |
| `stock-tank-farm` | Tank farm with pipe rack (vertical video) | 17 | 2 | OPTIMAL | $0.39 / $0.23 |
| `stock-rusty-pipe` | Heavily rusted outdoor pipe (not a plant) | 12 / 8 | 3 / 2 | OPTIMAL | $0.11 / $0.03 |
| `stock-welded-pipes` | Welded pipes with rust staining | 16 / 18 | 16 / 2 | FEASIBLE (gap 4%) / OPTIMAL | $0.35 / $0.19 |
| `stock-clean-piping` | Clean painted plant piping | **0** | 0 | – | $0.12 / $0.04 |

**Final choice (builder, 2026-10-29):** main clip **`stock-tank-farm`**; false-alarm beat **`stock-clean-piping`**; **`stock-valve-tank` only as backup**. `stock-vessel` is not used in the video; one of its frames illustrates the grille false alarm in the README Limitations.

**Visual mask check (2026-10-29; overlays and notes in `G:/walkdown-data/demo_checks/`) changed the recommendation:**
- **`stock-tank-farm` is now the main clip.** Light rust staining on tank seams, a rusty platform and a ladder; mostly plausible masks.
- **`stock-clean-piping`** stays as the false-alarm beat (0 detections).
- **`stock-vessel` is dropped.** Its large masks sit on dusty perforated grille panels, which are false alarms.
- **`stock-valve-tank`** is usable only as the "disputed, needs human review" example: the lichen and worn-paint flags are questionable.
- `stock-rusty-pipe` flags a galvanised bucket.

**Original recommendation (before the visual check):**
1. **`stock-valve-tank`** as the main walkdown: a real plant object, a readable register, 2 jobs and a provably optimal plan.
2. **`stock-clean-piping`** as the false-alarm beat: "on clean painted piping, the register stays empty". The same piping is a false-alarm risk in RESULTS §9, so verify it again before recording.
3. **`stock-vessel`** as a backup: a single job, and the repeat run is almost fully cached ($0.02).

**Caveats:**
- **Repeat runs are now stable.** Since 2026-11-01 the demo clips use a fixed frame grid, so the register does not change between runs (the earlier caveat about different sampling rates no longer applies). The 17-entry figures above were measured before that change; the current tank-farm register has 24 entries.
- **The individual plan's gap varies between runs** (16–18% on the rehearsal runs), because it stops at the 30 s time limit. Do not voice its exact gap; the grouped plan is proven optimal every time.
- **Check the masks before recording.** These numbers are pipeline output with no human check: each register entry needs a look on the overlay.
