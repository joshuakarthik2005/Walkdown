# Footage and public image sources

The builder's own footage and voice note take priority. Everything below is a fallback in case there is not enough builder footage. It is **stock demonstration footage**, and is labelled that way wherever it appears (demo video, README).

Files are kept on `G:\walkdown-data\` only. They are never committed, so the repo does not redistribute them. Licences were read on 2026-10-28.

## Stock demonstration clips (Pexels)

**Pexels License** (https://www.pexels.com/license/):
- Free to use, including commercially, and modification is allowed. Attribution is optional; we give it anyway.
- No standalone redistribution or sale of unaltered copies.
- Must not imply endorsement, or show identifiable people in a bad light.

| File | Clip | Author | URL | Use |
|---|---|---|---|---|
| `pexels_11662354.mp4` | Close-up of an old fuel transfer valve (on a tank) | Matthias Groeneveld | https://www.pexels.com/video/close-up-of-an-old-fuel-transfer-valve-11662354/ | Rust on valve and tank shell |
| `pexels_5571839.mp4` | Water dripping on welded metal pipes | Monsieur Sylvain | https://www.pexels.com/video/water-dripping-on-welded-metal-pipes-5571839/ | Rust staining at welds |
| `pexels_35069362.mp4` | Industrial facility with large metallic cylinder (vertical) | Diego Castro Calderon | https://www.pexels.com/video/industrial-facility-with-large-metallic-cylinder-35069362/ | Corroded vessel surface |
| `pexels_35596447.mp4` | Industrial power plant pipes and chimneys (vertical) | Mumtaz Niazi | https://www.pexels.com/video/industrial-power-plant-pipes-and-chimneys-35596447/ | Tank farm and pipe rack, light rust |
| `pexels_34633267.mp4` | Rusty pipeline in overgrown garden | Sergei Starostin | https://www.pexels.com/video/rusty-pipeline-in-overgrown-garden-34633267/ | Heavily rusted pipe (not a plant) |
| `pexels_30243437.mp4` | Industrial pipelines and valves system | Salim Da | https://www.pexels.com/video/industrial-pipelines-and-valves-system-30243437/ | Clean, painted plant piping: a false-alarm check |

Downloaded but **not used:**
- Too weak (garden pump, drum in grass, distant refinery aerial): 3696034, 2674784, 9339478 (`https://www.pexels.com/video/<id>/`).
- **Excluded:** 18359147 shows a destroyed military vehicle with war-related graffiti. War and political content is banned for this hackathon. The file was moved to `footage_stock/excluded/`.

Pixabay and Coverr were searched too:
- Pixabay had a few industrial valve clips (Content License: free use and modification, no standalone redistribution), but downloads need a signed-in account.
- Coverr had no industrial pipe clips.

## Public negatives (non-corroded metal), for the false-positive test only

| Source | Licence | Author / attribution | Downloaded | Kept |
|---|---|---|---|---|
| Roboflow Universe `corrosion-detection-sd/non-corroded-pipe` v1, class "Non-Corroded" | CC BY 4.0 (Roboflow API) | "Corrosion Detection SD" workspace, https://universe.roboflow.com/corrosion-detection-sd/non-corroded-pipe | 268 files (107 source images) | 70 |
| Roboflow Universe `corrosion-detection-sd/corrosion-detection-1` v1, class "Non-Corroded-1" | CC BY 4.0 (Roboflow API) | same workspace, https://universe.roboflow.com/corrosion-detection-sd/corrosion-detection-1 | 306 files (124 source images) | 121 |

- **Dedup.** 191 unique images in total. One file per Roboflow source name removes the augmented train copies. A dHash (≤ 40 bits, under 8 flips/rotations) then removes images shared by both projects. Script: `benchmark/download_negatives.py`; manifest: `benchmark/results/negatives_public_manifest.json`.
- **Caveat.** Some images carry stock-photo watermarks. The CC BY 4.0 listing may not reflect the rights of the original photographers. Like the main dataset, these images are therefore used **only for scoring**: never in public material, and never for training.
- **Other sources searched:**
  - Hugging Face: corrosion sets only, no clean-metal class.
  - Roboflow "No Rust" (96 images, CC BY 4.0): no exportable version.
  - Kaggle: no rust/no-rust set found, and no Kaggle API key.
  - University repositories: no non-corroded pipe class with a clear licence.

**Used in the repo:** one downscaled frame of `pexels_35069362.mp4` (Diego Castro Calderon), with Walkdown's mask overlay, is in `docs/images/false_alarm_perforated_grille.jpg` and illustrates a false-alarm limitation in the README. It is credited there; this is a modified use within a larger work, not standalone redistribution (Pexels License).
