# Demo video voiceover (3:00)

Target seconds in brackets. One recording per segment: `G:\walkdown-data\video\vo\VO01.wav` … `VO14.wav`.

VO01 [12] I'm Joshua, and I built Walkdown at this hackathon. Film a walk through a plant, and
Walkdown finds the corrosion, checks it, and hands a person a repair plan to approve.

VO02 [10] Corrosion costs industry about two and a half trillion dollars a year. Yet inspection
findings still end up in notes and spreadsheets, and repair plans are made by hand.

VO03 [20] Five Meta models do the work. SAM 3.1 outlines possible rust in every frame. Muse Spark
is the agent: it decides what to look at and grades every finding. Muse Wonder gives a second
opinion. Muse Voice Transcribe reads the inspector's notes. And Muse Spark Open runs on open
weights, for plants that can't use the cloud.

VO04 [13] We used about two hundred and ninety-seven dollars of free credits across Meta,
Baseten, Fireworks and Modal. Most of it went on testing and fine-tuning, and the report lists
every dollar.

VO05 [12] Here's a tank farm, from stock footage. The agent tracks rust through the video, SAM
outlines it, and Muse Spark checks every candidate. This sample replays saved model results.

VO06 [10] Every finding becomes a register entry: where it is, how bad, and why. This voice note,
from the same walkdown, flags a nearby LPG line.

VO07 [18] A person decides. Where the models disagree, I see both opinions side by side. On W09
the first check said no, and the second opinion said yes. I take the second opinion and approve.
I approve a seam stain, and reject a painted pipe edge.

VO08 [12] Approved findings join the existing backlog. A solver schedules every repair around
crews, skills, permits, shutdowns and risk. It only says optimal when it has proved it.

VO09 [15] Now a coating crew is out for three days. The agent replans. Started work stays fixed,
the rejected finding drops out, and it moves as few jobs as it can, showing exactly how much risk
that adds.

VO10 [7] Nothing happens until a person approves the plan.

VO11 [12] I can ask questions. When does crew C1 start work package one? Answers come only from
this register, this plan and the solver's own reasons.

VO12 [9] Then I export the report and work orders, with every reviewer decision.

VO13 [20] We measured it against people, not just labels. In a blind audit, the default setting
kept 110 of 113 real rust findings: 97.3 percent. But 12 percent of clean pipe images still got a
false flag, and severity grades aren't validated yet. That's why a person reviews everything.

VO14 [10] Walkdown is decision support: a person approves every repair. Try it at walkdown-zeta
dot vercel dot app. Built with Muse Spark Open.

## Number sources

| Spoken | Source | On screen |
|---|---|---|
| about two and a half trillion dollars a year | `docs/IMPACT_SOURCES.md` (NACE IMPACT, 2016) | "≈ $2.5T / year (NACE IMPACT)" |
| about $297 of free credits; Meta, Baseten, Fireworks, Modal | `docs/CREDIT_USAGE.md` summary (≈ $296.8) | |
| 110 of 113 real rust findings, 97.3% | `benchmark/RESULTS.md` §8, §16 (High recall, audited real-rust recall) | "97.3% recall · 110/113 audited" |
| 12% of clean pipe images flagged | `benchmark/RESULTS.md` §9, §16 (12.0%, 23 of 191) | "12.0% · 23/191 clean-pipe images" |
| severity grades not validated | README Limitations | |
| W09 (first check no, second opinion yes), W06, W24, crew C1, three days | the product screen in the recording | |
