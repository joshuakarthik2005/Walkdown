# Walkdown

Walkdown is an agent for **plant and facility walkdowns**: refineries, tank farms, terminals, pump and compressor stations, power plants. A technician records a handheld video or photos of plant piping, tanks, vessels, valves and supports. Walkdown turns that into a **verified defect register** and a **risk-optimal repair plan**, and replans when something changes on site.

Entry in the Meta Global AI Developer Hackathon (Indie Developer track, theme: Push the Frontier).

> Status: work in progress, built during the hackathon building period (Oct 27 – Nov 4, 2026).

**Built with Muse Spark Open.** Walkdown's open-weights mode runs the verifier and the agent on Muse Spark Open (Muse Model License; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).

**Decision support only.** Walkdown never operates or controls plant equipment. It proposes a defect register and a repair plan; every maintenance action needs approval by a qualified person. Read [Limitations and safe use](#limitations-and-safe-use) before relying on it.

### Where it fits
- **Long cross-country pipelines** are inspected from the inside with in-line inspection tools ("pigs"). Walkdown is not a replacement for that.
- Walkdown targets **plant piping and equipment that pigs cannot reach**: short, branched, small-bore and unpiggable lines, supports, flanges and tanks. These are inspected by people walking the plant, and the findings usually end up in notes and spreadsheets.
- Footage today is **handheld**. Drone and robot footage is future work, not something Walkdown claims to handle now.

## How it works

An agent (Muse Spark with tool calling) runs the whole loop and decides what to do next:

1. **Perceive.** SAM 3.1 (Meta Model API) segments candidate corrosion on sampled frames from a text prompt ("rust"). The agent starts with a coarse pass and looks again at stretches that need it.
2. **Verify and grade.** Muse Spark looks at each candidate (a crop with the mask outlined, plus the full frame), rejects false positives, and returns a schema-validated grade: defect type, severity 1–5, confidence, evidence, recommended action. Rule-based checks flag contradictory grades for human review. Severe or uncertain grades get a second opinion from Muse Wonder. It does not make grades more accurate (label agreement 73.5% before, 72.7% after; [`benchmark/RESULTS.md`](benchmark/RESULTS.md) section 5); its job is to surface disagreements: a defect Muse Wonder disputes stays in the register, marked "needs human review".
3. **Register.** Repeat sightings are merged into one entry per defect. The asset's line service (LPG, hydrogen, crude, steam, cooling water, …) sets a consequence factor.
4. **Plan.** An OR-Tools CP-SAT model schedules repairs across crews, skills, shift hours, permits (lead times, concurrency limits) and shutdown windows. It minimises risk-weighted exposure: likelihood × consequence × hours unrepaired.
5. **Replan.** When a crew drops out, a shutdown window moves or a new defect is found, a two-stage replan keeps started work fixed, finds the lowest-risk plan, then moves as few jobs as possible within a chosen "stability vs risk" tolerance.
6. **Explain.** The agent explains the plan only through the planner's structured reasons (permit lead time, waiting for a shutdown window, crew capacity, "not enough coating crew hours in the horizon", …). It never invents reasons. Solver status and optimality gap are always shown; a FEASIBLE plan is never called optimal.

Every model turn and tool call is logged as a structured trace (timing, tokens, cost) and shown live in the web UI.

## Results

See [`benchmark/RESULTS.md`](benchmark/RESULTS.md) (perception and verification) and [`benchmark/PLANNER_RESULTS.md`](benchmark/PLANNER_RESULTS.md) (CP-SAT vs a priority-sort baseline), with all limitations stated.

## Limitations and safe use

Walkdown assists inspectors; it does not replace them. These limitations apply in both modes (Cloud: hosted Meta models; On-prem: open-weight models).

- **It misses corrosion.** On the held-out test split (1,444 annotated images; numbers in [`benchmark/RESULTS.md`](benchmark/RESULTS.md)), the SAM 3.1 text prompt alone found corrosion on 66% of images that have it and covered 37% of the annotated corrosion area. The default pipeline (text prompt + Muse Spark box proposals + Muse Spark verification) finds corrosion on 97.9% of images and covers 84% of the area, but matches only 30% of individually annotated corrosion patches as separate instances (instance recall 0.30 at IoU 0.5). A clean register is not evidence of a clean asset.
- **It flags things that are not corrosion.** Pixel precision is 0.77 for the default pipeline (0.92 for the text prompt alone): box proposals add false alarms and the verifier removes only part of them (instance precision 0.47 vs 0.38 unverified, at IoU 0.5); the false-alarm rate on clean surfaces is not measured yet (pending the author's negative footage). These precision figures are measured against the dataset's masks, which miss visible rust: in a blind human audit of 100 candidates, 84% of the candidates the dataset counts as false positives were rust (26 of 31 sure labels; [`benchmark/RESULTS.md`](benchmark/RESULTS.md) section 8). A second blind audit of 50 box-proposal candidates found only 70% of them were rust (95% CI 56–82%), against 92% of text-prompt candidates: box proposals add look-alikes. Across both audits (133 labels, reweighted to the default pipeline's candidate mix), about 91–93% of the candidates the verifier accepts are rust, and the verifier rejects about two thirds of the not-rust candidates (12–14 of 20).
- **The verifier also rejects some real rust.** Across both human audits (reweighted), it wrongly rejected about 2% of real-rust candidates at minimal effort (the live demo setting), 3% with Muse Spark Open and 7% at low effort; the intervals overlap. A rejected candidate is not shown as a defect.
- **You choose the trade-off between missed defects and false alarms.** "Detection sensitivity" shows measured operating points next to each option.

  | Option | Audited real-rust recall (n = 113) | Real clean-pipe images with a false alarm (n = 191) |
  |---|---|---|
  | High recall (default) | 97.3% (95% CI 92.5–99.1) | 12.0% (8.2–17.4) |
  | Balanced | 93.8% (87.8–97.0) | 6.8% (4.0–11.3) |
  | On-prem | 95.6% (90.1–98.1) | 2.1% (0.8–5.3) |

  The default favours recall because a missed defect is the dangerous error and every flag is reviewed by a person ([`docs/DECISIONS.md`](docs/DECISIONS.md)).
- **Severity grades are not validated for accuracy.** There is no ground truth for severity. Grades are schema-validated and consistency-checked (contradictory grades are flagged for review), and repeat grading agreement is reported, but a grade is a triage suggestion, not an engineering assessment.
- **Not a substitute for certified inspection programmes.** Walkdown does not perform or replace inspections under API 570 (piping), API 510 (pressure vessels), API 653 (tanks) or a risk-based inspection (RBI) programme, wall-thickness measurement or any regulatory requirement.
- **Human approval is required.** The plan is a proposal. Crews, permits, isolations and shutdowns are decided by the site's responsible people. The planner's consequence factors per line service are stated assumptions, not site data.
- **Scope.** Handheld visible-light footage of external surfaces. It cannot see under insulation, inside pipes or below paint.

## Built during the hackathon

All code in this repository was written during the building period. A full breakdown will be added here.

## Third-party libraries, models and datasets

### Models and services
| Component | Licence / terms | Use |
|---|---|---|
| SAM 3.1 (`sam-3.1`), Meta Model API | Meta Model API terms | Candidate segmentation |
| Muse Spark (`muse-spark-1.3`), Meta Model API | Meta Model API terms | Verification, grading, box proposals, agent tool calling |
| SAM 3.1 open weights (`facebook/sam3.1`, code `facebookresearch/sam3`) on a Modal GPU | SAM License; Modal terms | On-prem mode: candidate segmentation without a hosted model |
| Muse Wonder (`muse-wonder-1.0`), Meta Model API | Meta Model API terms | Second opinion on severe or uncertain grades; disagreements go to a person |
| Muse Spark Open (`meta-models/muse-spark-open-1026`) on Baseten | Muse Model License (Muse Spark Open, Oct 15, 2026) and its Usage Policy; Baseten Model API terms | Open-weights mode: verifier and agent; teacher for the verifier distillation |

### Libraries
| Library | Licence | Use |
|---|---|---|
| `meta-sam-parser` 0.1.0 (Meta Platforms, Inc.) | **SAM License** (Meta; see the package's `licenses/` file) | Parsing and decoding SAM 3.1 segmentation output |
| OR-Tools (CP-SAT) | Apache-2.0 | Maintenance scheduling |
| FastAPI, Uvicorn, Pydantic, python-multipart, httpx | MIT / BSD | API |
| OpenAI Python SDK | Apache-2.0 | Client for the OpenAI-compatible Meta and Baseten APIs |
| NumPy, OpenCV (opencv-python), Pillow, pycocotools | BSD / Apache-2.0 / HPND / BSD | Image handling, masks, evaluation |
| Next.js, React, TypeScript | MIT / MIT / Apache-2.0 | Web UI |

### Datasets

| Dataset | Source | Licence | How it is used |
|---|---|---|---|
| Corrosion Segmentation v1 (Roboflow Universe, workspace `computervision-adpf6`), COCO-segmentation export | https://universe.roboflow.com/computervision-adpf6/corrosion-segmentation-xybsj | **Public Domain**, as listed by the uploader on Roboflow Universe and in the export's README | Benchmark scoring only. Only the dataset's `valid` and `test` folders are used (2,050 images; `train` holds augmented copies). Near-duplicates are removed, and images with commercial-stock-style filenames are excluded, because the uploader's licence label may not cover them. File lists are in `benchmark/splits/`. Images are not redistributed here and never appear in public material (README, video, screenshots). |

All public visuals come from footage recorded by the author.

## Licence

MIT, see [LICENSE](LICENSE). Third-party licences and notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
