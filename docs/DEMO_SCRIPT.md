# Demo video script (3:00) and X cut (30–45 s)

Rules for both videos:
- Show only what was built during the hackathon.
- Every on-screen number must come from `docs/IMPACT_SOURCES.md` (Verified) or `benchmark/RESULTS.md` / `PLANNER_RESULTS.md`.
- All footage and screenshots come from the builder's own recordings. **No dataset images anywhere** (DECISIONS.md, rights rule).
- Use a cached demo clip, so the run is fast and repeatable. Say once, on screen, that it is cached; the live flag exists.

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

| Time | On screen | Voice-over | Built? |
|---|---|---|---|
| 0:30–0:45 | Walkdown UI. Upload the builder's clip; set asset `UNIT2-LPG-RACK`, line service **LPG**, pressurised. Click **Run the agent**. | "I upload a 30-second walkdown clip of an LPG pipe rack and hand it to the agent." | UI, upload, asset/service form **[BUILT]** |
| 0:45–1:10 | **Agent decision flow** fills in step by step: "Tracks the clip" (SAM 3.1 video tracking, one candidate per physical defect), "Checks each finding" (Muse Spark), "senior review (Muse Wonder)" on the severe ones. Point at the per-step time/cost and "cached". | "The agent decides what to look at. SAM 3.1 tracks rust through the video; Muse Spark checks each finding, rejects look-alikes like paint or shadows, and grades severity with evidence. Severe or uncertain calls go to Muse Wonder for a second opinion." | Agent loop, tools, trace, tracking, tiered verification **[BUILT]** · SAM 3.1, Muse Spark, Muse Wonder **[META]** |
| 1:10–1:30 | **Verified defect register**: the builder's frames with severity-coloured masks; rows with type, severity, evidence, action; a **senior review** badge; the inspector's voice note under the table (tag, service, follow-up). The yellow **Decision support only** notice is visible. | "Every finding becomes a register entry with evidence. The inspector's voice note is transcribed and filed with it. Contradictory grades get flagged for a human, and every action still needs a person's approval." | Register, overlays, consistency checks, voice-note extraction, safe-use notice **[BUILT]** · Muse Voice Transcribe **[META]** |
| 1:30–1:55 | **Repair plan** Gantt: crews, shutdown windows, walkdown jobs coloured by severity among the existing backlog. Status badge reads **Optimal** (demo sized to ≤ 6 defects + 12-job backlog). Hover a job. | "It merges the new defects into the plant's backlog and schedules them with a constraint solver: crews, skills, permits, shutdown windows, and risk weighted by what the line carries. The plan is proven optimal." | CP-SAT model, risk = likelihood × consequence **[BUILT]** · OR-Tools **[LIB]** |
| 1:55–2:20 | **"Something changed on site?"**: cancel shutdown window SD1 (or take crew C1 out for 72 h), slider **ε = 0.02**, click **Replan**. The flow shows "Replans after the change"; the Gantt redraws with moved jobs dashed. | "Now the shutdown is cancelled. The agent replans: work already started stays fixed, it finds the lowest-risk plan, then moves as few jobs as possible. This slider trades stability against risk." | Two-stage replan, ε control **[BUILT]** |
| 2:20–2:25 | **"What the agent concluded"** panel: plain-language explanation citing reason codes ("waiting for shutdown window", "not enough coating crew hours"). | "And it explains why, using only the solver's own reasons. Nothing invented." | Structured explanations, prompt rules **[BUILT]** |
| 2:25–2:30 | **Copilot** box: type "Why is W03 not scheduled?"; answer cites crew hours; "from get schedule, explain plan". Then click **Inspection report (PDF)**. | "Inspectors can ask follow-up questions, answered only from the plan, and export the report and work orders." | Inspector copilot, PDF report, CMMS-style export **[BUILT]** |

Demo prerequisites (all **[BUILT]**):
1. Warm the cache for the demo clip with `python -m backend.agent.warm_cache <clip_id>`.
2. Rehearse the full flow with `python -m backend.agent.rehearse <clip_id>`.
3. Confirm the register has ≤ 6 defects, so the plan proves OPTIMAL.

## 2:30–3:00 · Results and what it unlocks

| Time | On screen | Voice-over | Source |
|---|---|---|---|
| 2:30–2:45 | Two numbers on cards (charts in RESULTS.md): **verifier keeps 95.5% of annotated corrosion, 0 malformed replies over 5,066 checks**; **CP-SAT never worse than the priority-sort baseline across 60 scenarios; median improvement 1–7.5% by regime** | "We measured it honestly. The verifier rarely drops real corrosion. The planner beats a severity-sort baseline, most in permit-constrained plants." | RESULTS.md §2; PLANNER_RESULTS.md |
| 2:45–2:52 | Card: "Assists inspectors, does not replace them." plus the measured recall line from RESULTS.md §4 (measured: SAM text prompt alone finds corrosion on 66% of test images; text + Muse Spark boxes + verification 98%, covering 84% of annotated area). | "It doesn't replace inspectors; it makes their walkdown count." | RESULTS.md §1, §4 |
| 2:52–2:56 | Flip the **Cloud / On-prem** switch. Card: "On-prem mode: the same agent and verifier on Muse Spark Open (open weights) · Built with Muse Spark Open" plus the hosted-vs-open agreement figure from RESULTS.md (fill in when measured). | "And it runs on open weights too, for plants that can't send footage to the cloud." | On-prem mode **[BUILT]** · Muse Spark Open via Baseten **[META, open weights]** |
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
