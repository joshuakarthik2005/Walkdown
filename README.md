# Walkdown

Walkdown turns first-person inspection video of an energy plant (pipelines, tanks, valves) into a **verified defect register** and a **solver-optimal maintenance plan**, and replans when constraints change.

Entry in the Meta Global AI Developer Hackathon (Indie Developer track, theme: Push the Frontier).

> Status: work in progress. Built during the hackathon building period (Oct 27 – Nov 4, 2026).

## Pipeline (planned)

1. **Perceive:** SAM 3.1 (Meta Model API) segments and tracks candidate defects in video from text prompts.
2. **Verify and grade:** Muse Spark checks each candidate, rejects false positives and returns a schema-validated severity grade with evidence.
3. **Plan:** an OR-Tools CP-SAT model schedules repairs across crews, skills, permits and shutdown windows, and replans when constraints change.
4. **Agent loop:** Muse Spark with tool calling drives perception, verification, planning and replanning.

## Built during the hackathon

All code in this repository was written during the building period. A full breakdown will be added here.

## Third-party libraries, models and datasets

To be completed. Every dataset licence will be recorded here.

## Licence

MIT, see [LICENSE](LICENSE).
