# Walkdown: build brief for Claude Code

This file is the standing brief for building **Walkdown**, an entry in the **Meta Global AI Developer Hackathon** (Cerebral Valley, Oct 26 – Nov 4, 2026). Read all of it before doing anything, and re-read the "Rules" and "Reporting" sections at the start of every session.

---

## 1. Who and what

- **Builder:** Joshua Karthik Ashok, solo entrant, GitHub `joshuakarthik2005`.
- **Track:** Indie Developer.
- **Theme:** Push the Frontier (energy: "unlock a better way to understand and control a physical system").
- **Machine:** Windows (Command Prompt), project folder `C:\Users\DELL\Documents\walkdown`. Check the Python version first (`python --version`); target Python 3.10+.
- **Repo:** https://github.com/joshuakarthik2005/Walkdown (already created, **public**, currently **empty**, no commits). Note the capital **W** in `Walkdown`. Remote URL: `https://github.com/joshuakarthik2005/Walkdown.git`.

### The product, in one line
Walkdown turns first-person inspection video of an energy plant (pipelines, tanks, valves) into a **verified defect register** and a **solver-optimal maintenance plan**, and replans when constraints change.

### The pipeline
1. **Perceive:** SAM 3.1 (Meta Model API, model `sam-3.1`) segments and tracks candidate defects in images and video from text prompts: corrosion, rust, leak stain, damaged insulation.
2. **Verify and grade:** Muse Spark (`muse-spark-1.3`) looks at each candidate on its cropped frame, rejects false positives, and returns a severity grade as schema-validated JSON (structured output), with the evidence it used (mask area, location, visual cues). Rule-based consistency checks flag contradictory grades for human review.
3. **Plan:** an OR-Tools CP-SAT model schedules repairs across crews, skills, permits, shutdown windows and risk. Muse Spark explains the plan in plain language and replans when a constraint changes (a crew becomes unavailable, a shutdown window moves, a new defect is found).
4. **Agent loop:** steps 1–3 run as a multi-step agent (Muse Spark with tool calling) that decides what to inspect next, calls the tools, verifies, plans and replans. This is the core of the product and targets the "Best Agentic Use-Case" bonus.

### What Walkdown is NOT
- Not "SAM finds rust". "Simple image analyzers" are a banned anti-project. Verification, grading, the optimizer and the agent loop are what make it a product.
- Not a dashboard. "Dashboards as the main feature" are banned. The web UI only shows the agent's results.
- **Not Streamlit.** Streamlit apps are a banned anti-project. Use a React or Next.js front end with a Python FastAPI back end.

---

## 2. Rules (breaking these risks disqualification)

1. **New work only.** Everything must be built during the building period (Oct 27 – Nov 4, 2026). Don't copy code from any earlier project (RouteX, HPCL tools or others). Write everything fresh.
2. **Public repo:** `github.com/joshuakarthik2005/Walkdown`. It already exists and is public. It must stay public and must open in a logged-out browser. Don't create another repo and don't rename this one.
3. **Commit small and often** with clear messages, and **push after every task**, so the public git history proves the work was done during the event. Default branch: `main`.
4. **Original contributions must be clearly identifiable.** The README must say exactly what was built during the hackathon and which third-party libraries, models and datasets are used.
5. **Only use code, data and assets you have rights to.** Record every dataset's licence in the README. Check licences before downloading.
6. **Secrets:**
   - API keys live **only** in `.env` in the project root. Variables: `MODEL_API_KEY` (Meta) and `BASETEN_API_KEY` (Baseten, may not be present yet).
   - Create `.gitignore` containing `.env` **before the first commit**. Verify with `git status` that `.env` is never staged.
   - Never print, log, echo or commit a key. Never put a key in a report. Load keys with `python-dotenv`.
   - Provide `.env.example` with placeholder values only.
7. **Ask before any irreversible action:** force-pushing, rewriting git history, deleting files or branches, changing repo settings or visibility, or spending more than $5 of API credit in one run. State what you'll do and wait for "yes". Normal commits and pushes to `main` don't need approval, **but before every push run `git status` and confirm `.env` is not staged.**
8. **If a secret is ever committed:** stop immediately, don't push (or if already pushed, report it at once). The key must be revoked on dev.meta.ai or Baseten, and history cleaned only with the builder's approval.

---

## 3. Models, APIs and credits

### Meta Model API ($150 free credits, active)
- Base URL `https://api.meta.ai/v1`, auth `Bearer $MODEL_API_KEY`. Works with the OpenAI Python SDK: `OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])`. The SDK does **not** read `MODEL_API_KEY` automatically; pass it explicitly.
- A test call to `muse-spark-1.3` through the Responses API has already succeeded on this account.
- **Don't guess request formats.** Before writing code for SAM 3.1, image input, video input, structured output or tool calling, read the official docs and copy their format:
  - https://dev.meta.ai/docs/media-segmentation and https://dev.meta.ai/docs/sam/segmenting (SAM 3.1)
  - https://dev.meta.ai/docs/image-understanding and https://dev.meta.ai/docs/video-understanding
  - https://dev.meta.ai/docs/structured-output, https://dev.meta.ai/docs/tool-calling, https://dev.meta.ai/docs/reasoning
  - https://dev.meta.ai/docs/pricing-rate-limits
  - Cookbook: https://github.com/meta-models/meta-model-cookbook
- Official prices:
  - `muse-spark-1.3`: $1.25 per 1M input tokens, $0.15 cached, $4.25 per 1M output
  - `sam-3.1`: $2.50 per 1,000 images; video $0.20 per 1,000 frames, minimum 50 frames per request
  - `muse-voice-transcribe-1.0`: $0.18 per hour
- The account is in free-credit mode, where content may be used for product improvement. **Send only public dataset images or footage you have rights to.** No confidential or personal data.
- The billing page shows the account as "restricted" (card not verified), but calls still work. If a call starts failing with a payment or restriction error, stop and report it.

### Baseten ($100 + 2M TPM, approved)
- Model: **`meta-models/muse-spark-open-1026`**. Use this name, not the one in Baseten's docs.
- OpenAI-compatible. Take the base URL from Baseten's docs or the approval email; don't assume it.
- Use: batch verification for the benchmark, and a comparison of hosted Muse Spark against open-weight Muse Spark Open (accuracy, latency, cost per verified defect).

### Pending (don't depend on these)
- Modal $100 (GPUs for a LoRA fine-tune of SAM 3.1), Fireworks $25 (distilling the verifier into Muse Glimmer). Stretch goals only, and only if the credits arrive.

### Budget rules
- Target total Meta spend: **$50–70**, with a hard stop at **$120**.
- **Run every expensive job as a 50-item dry run first.** Measure the real cost per item from the `usage` fields, extrapolate, report, and ask before scaling up.
- Use **low or medium reasoning effort** for verification calls. Reasoning tokens are billed as output and add up fast.
- Use prompt caching for the fixed system prompt and schema.
- Keep a running cost log in `docs/COST_LOG.md`: date, job, items, tokens, estimated $.

---

## 4. Judging, prizes and submission (from the kickoff slides and participant guide)

### Judging
- **Stage 1, pass or fail:** does it fit a theme, and did it reasonably use Meta Model API and/or Meta open-weight models during the hackathon?
- **Stage 2, rubric, 0–10 per criterion.** Kickoff slide weights (the written guide says "equally weighted"; plan for the slide):
  | Criterion | Weight | What judges look for |
  |---|---|---|
  | Impact | **30%** | Real-world potential, who benefits, fit with the problem statement |
  | Use of Meta AI tooling | 25% | Creative use beyond a basic integration |
  | Demo | 25% | A working demo that holds up, and a demo video worth watching |
  | Technical depth | 20% | Sound, refined engineering with real craft |
- **Stage 3:** top 5 per track; judges watch the demo videos live on Nov 9 and rank them with the same rubric. **The video decides the final.**

### Prizes
- Indie track ($400K): 1st $150K, 2nd $100K, 3rd $75K, 4th $50K, 5th $25K.
- Bonus prizes ($50K):
  - **Most Viral ($20K):** post the demo on X and submit the link. Most likes, reposts and comments by Nov 8, 11:59 PM ET.
  - **Best Build on Meta Open Weights ($10K):** Muse Glimmer or Muse Spark Open, on your own hardware or a partner's. The infra partner verifies it. (Baseten Muse Spark Open counts if it's genuinely part of the product.)
  - **Community Vote ($10K):** public gallery, one vote per verified account. Announced Nov 16.
  - **Best Agentic Use-Case ($5K):** scored on autonomy, effectiveness and practical usefulness. **Primary bonus target.**
  - Best Creative Build ($5K): Muse Image or Muse Wonder. Not a target.

### Submission (due Nov 4, 9:00 PM ET = Nov 5, 7:30 AM IST; late entries are rejected)
1. Submit on the Cerebral Valley platform: cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
2. **A 3-minute demo video** showing only what was built during the hackathon.
3. **A public GitHub repo** that opens in a logged-out browser.
4. A working live product. Judges look at the video, the code and the live product.
- Internal target: **feature freeze on Nov 2, video recorded by Nov 3, submitted by Nov 4 IST daytime.**

### Banned anti-projects (avoid any resemblance)
AI medical advice, basic RAG apps, simple image analyzers, Streamlit apps, dashboards as the main feature, "AI for Education" chatbots, AI job screeners, AI nutrition coaches, personality analyzers, sports analyzers or coaches, anything political or war-related.

### How to score on each criterion
- **Impact (30%):** find **real, cited** figures on industrial corrosion costs, inspection effort, and incidents caused by missed corrosion in oil, gas and energy. **Never invent a number.** Every figure in the README, UI or video needs a source URL in `docs/IMPACT_SOURCES.md`. If a figure can't be sourced, leave it out.
- **Use of Meta tooling (25%):** SAM 3.1 video tracking, Muse Spark vision with structured output and tool calling, the agent loop, Muse Spark Open on Baseten, and optionally Muse Voice Transcribe for technician voice notes.
- **Demo (25%):** the product must run end to end on a fresh clip without errors. Build a reliable demo path early.
- **Technical depth (20%):** a sound CP-SAT model, a verification layer, an honest benchmark with baselines, tests, and clean code.

---

## 5. Build plan

Times are IST. Each phase ends with a **checkpoint report** (section 6), after which you wait for "go".

### Phase 0: setup (Oct 27)
- Check Python, Node and git are installed, and that git can push to GitHub (`gh auth status` if `gh` exists; otherwise Git Credential Manager prompts on first push).
- The project folder already holds `.env` (keys) and this `CLAUDE.md`. **Don't open, print or modify `.env`;** only confirm it exists and that `python-dotenv` can load the variable names.
- Connect the local folder to the existing empty repo, in this order:
  1. `git init -b main`
  2. Create `.gitignore` first (`.env`, `.env.*` except `.env.example`, `__pycache__/`, `.venv/`, `node_modules/`, `.next/`, `data/raw/`, `*.mp4`, `*.mov`, large media, `.DS_Store`).
  3. `git add .gitignore` and check that `git status` doesn't list `.env` as staged or untracked-to-add.
  4. Add `.env.example`, `README.md` stub, MIT `LICENSE`, and `CLAUDE.md`.
  5. `git remote add origin https://github.com/joshuakarthik2005/Walkdown.git`
  6. First commit, then `git push -u origin main`.
  7. Open https://github.com/joshuakarthik2005/Walkdown and confirm `.env` is **not** there.
- Python virtual environment, `requirements.txt` (openai, python-dotenv, ortools, fastapi, uvicorn, pydantic, numpy, opencv-python, pillow, pycocotools, pytest).
- Folder layout:
  ```
  walkdown/
  ├── backend/
  │   ├── perception/   # SAM 3.1 client, video frame sampling, tracking
  │   ├── verify/       # Muse Spark verification, JSON schema, consistency checks
  │   ├── planner/      # CP-SAT maintenance scheduler
  │   ├── agent/        # agent loop with tool calling
  │   ├── clients/      # Meta and Baseten API clients, cost tracking
  │   └── api/          # FastAPI routes
  ├── frontend/         # Next.js app
  ├── benchmark/        # dataset loader, metrics, run scripts, results
  ├── docs/             # PROGRESS.md, COST_LOG.md, IMPACT_SOURCES.md, DECISIONS.md
  └── tests/
  ```
- Smoke test reading `MODEL_API_KEY` from `.env` with one tiny `muse-spark-1.3` call. Print only the reply and token usage, never the key.
- Commit and push the scaffold and the smoke test.

### Phase 1: CP-SAT maintenance planner (Oct 27–28), no API needed
- Inputs: defects (id, asset, severity 1–5, failure risk, estimated repair hours, required skill, needs-shutdown flag), crews (skills, shift hours), shutdown windows, permits, a horizon in days.
- Decisions: which defects get fixed, by which crew, when.
- Constraints: crew capacity per shift, skill match, shutdown-only jobs inside shutdown windows, permit lead times, no overlap per crew.
- Objective: minimise risk-weighted exposure (risk × days left unrepaired), plus a penalty for unscheduled critical defects.
- Replanning: re-solve with changed constraints, keeping already-started work fixed.
- Baseline: a simple priority sort by severity, to compare against.
- Tests, plus a synthetic scenario generator for demos and the benchmark.

### Phase 2: data and evaluation (Oct 28)
- Pick a public corrosion segmentation dataset with a clear licence. Candidate: Roboflow Universe "corrosion-segmentation-xybsj" (about 16k images, listed as public domain). **Confirm the licence and download terms first**; Roboflow may need an account or API key. If so, stop and ask the builder.
- Make a fixed, seeded test split of 1,000–2,000 images. Don't run the API on the full dataset.
- Metrics: mask IoU, precision, recall and F1 at instance level, using pycocotools where possible.
- Collect a few short, rights-cleared demo clips of industrial piping or tanks. Prefer CC-licensed footage, or footage the builder records. Note the licences.

### Phase 3: SAM 3.1 perception (Oct 29)
- Read the SAM docs first. Implement image and video segmentation from text prompts, returning boxes, masks and scores.
- Video: sample frames sensibly. Bill a minimum of 50 frames per request and batch accordingly.
- **50-image dry run**, then report cost and quality before scaling.

### Phase 4: verification and grading (Oct 30)
- Pydantic or JSON schema for the grade: `is_defect`, `defect_type`, `severity` 1–5, `confidence`, `evidence`, `recommended_action`.
- Muse Spark (structured output, low or medium reasoning) checks each SAM candidate on its crop with surrounding context.
- Consistency checks, for example severity 5 with confidence below 0.5, or a "leak" on a non-pressurised asset; flag these for human review.
- Same verifier running on Baseten Muse Spark Open, for comparison.

### Phase 5: agent loop and API (Oct 31)
- Muse Spark with tool calling: `segment_frames`, `verify_candidate`, `build_register`, `plan_maintenance`, `replan(change)`, `explain_plan`.
- The agent decides what to inspect next and stops when done. Log every tool call so the demo can show the agent's reasoning trail.
- FastAPI endpoints for uploading a clip, running the agent, fetching the register and plan, and posting a constraint change.

### Phase 6: front end (Nov 1)
- Next.js. Flow: upload a walkdown clip, watch the agent work (live tool-call trail), see the verified defect register with masks drawn on frames, the maintenance schedule (Gantt), and a "change a constraint" control that triggers a replan.
- The UI shows the agent's work; it is not the product. Keep it clean and fast.

### Phase 7: benchmark (Nov 2)
- Compare SAM 3.1 alone, SAM + Muse Spark verification, and SAM + Muse Spark Open verification: IoU, precision, recall, F1, cost and latency per image.
- Compare CP-SAT against the priority-sort baseline on synthetic scenarios: risk-weighted backlog cleared, critical defects left unscheduled.
- Report results honestly, including negative results. Write them to `benchmark/RESULTS.md` with charts.
- **Feature freeze at the end of Nov 2.**

### Phase 8: submission materials (Nov 3)
- README: problem (with cited impact figures), what it does, architecture diagram, how Meta models are used, benchmark results, how to run it, licences, and a **"Built during the hackathon"** section.
- 3-minute demo video script: about 30 s problem and impact, 2 min live end-to-end run including a replan, 30 s results and what it unlocks. Show only hackathon-built features.
- A 30–45 s cut for X (Most Viral bonus).
- Check the repo opens in a logged-out browser.

### Phase 9: buffer and submit (Nov 4)
- Fixes only. The builder submits on the Cerebral Valley platform.

### Stretch goals (only if the core is done by Nov 1 and the credits have arrived)
- Muse Voice Transcribe: technician voice notes attached to defects.
- Modal: LoRA fine-tune SAM 3.1 with hard-negative prompts.
- Fireworks: distil the verifier into Muse Glimmer (Best Open Weights bonus).

---

## 6. Reporting (mandatory)

### After every task (each bullet in a phase), print a short report:
```
=== TASK REPORT ===
Task: <name>
Status: DONE | PARTIAL | BLOCKED
What I did: <2-4 lines>
Files changed: <list>
Commands run and results: <key commands, pass/fail>
Tests: <passed/failed/none>
API usage this task: <tokens, estimated $> | none
Running API total: <$ so far>
Commit: <hash + message> | not committed
Issues / risks: <or none>
Next: <next task>
===================
```

### At the end of each phase, print a checkpoint report and **wait for "go"**:
```
=== CHECKPOINT: Phase N ===
Summary: <what now works, in plain words>
Demo-able now: <what could be shown>
Rubric impact: Impact / Meta tooling / Demo / Technical depth: <one line each>
Rule check: new-work-only OK? secrets never committed? licences recorded?
Spend: Meta $<x> of $150 | Baseten $<y> of $100
Schedule: on track / behind by <n> hours, and why
Decisions needed from the builder: <list>
Plan for next phase: <bullets>
===========================
```

### Also keep these files up to date:
- `docs/PROGRESS.md`: append every task report.
- `docs/COST_LOG.md`: every API job.
- `docs/DECISIONS.md`: every design choice and why.
- `docs/IMPACT_SOURCES.md`: every cited figure with its URL.

### Stop and ask immediately if:
- An API call fails with a payment, quota, restriction or auth error.
- A job would cost more than $5, or the total would pass $120.
- A dataset licence is unclear, or a download needs an account.
- You're about to create, push or make anything public, or delete anything.
- You're unsure whether something counts as new work.
- You're behind schedule by more than half a day.

---

## 7. Quality bar
- Correctness over speed. Don't claim something works until it has run.
- No invented numbers, results or citations. If unverified, say so.
- Handle API errors with retries and backoff, and respect rate limits.
- Type hints, docstrings on public functions, and pytest for the planner, schema validation and metrics.
- Keep the demo path reliable: cache results for the demo clip so the live demo never depends on a slow or failing call.