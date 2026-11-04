# Deploying the public demo (Render free + Vercel Hobby)

The public demo runs the API in demo mode (`DEMO_MODE=true`, backend/api/demo.py) on a Render free web service, and
the Next.js UI on Vercel Hobby. Neither plan needs a credit card. **If either asks for one, stop:** the builder has no
hosting budget.

## What runs where

| Part | Host | Notes |
|---|---|---|
| API (FastAPI, one worker) | Render free web service, Docker (`Dockerfile`, `render.yaml`) | 512 MB RAM, 0.1 CPU. Sleeps after 15 min without traffic, takes about a minute to wake. Ephemeral disk. |
| Sample frames, cached results, finished examples | Private Hugging Face dataset `joshuakarthik2005/walkdown-demo-bundle` | Downloaded at container start with `HF_TOKEN` (backend/api/bundle.py). Never in the public repo or image. No stock videos. |
| UI | Vercel Hobby, root `frontend/` | `NEXT_PUBLIC_API_URL` points at the Render URL. |

Because the disk is ephemeral, runs and today's spend total reset whenever the service restarts or sleeps; the
examples reload from the bundle at every start. The spend cap is therefore per process lifetime as well as per day.

## Memory (measured 2026-11-03)

The judge path was: startup, open the tank-farm example, a cached sample run, a replan, a copilot question, PDF and
CSV exports, then 10 more example loads.

| Build | Where | Peak RSS |
|---|---|---|
| Before (all CP-SAT workers, full-frame masks) | Windows, DEMO_MODE | 512 MB |
| 2 solver workers | Windows | 345 MB |
| + bit-packed masks, repacked examples, 12 runs held | Windows | 311 MB |
| Same, Docker image | Linux container, `--memory 512m --cpus 0.1` | 324 MB (VmHWM) |

After streaming uploads to disk and rejecting oversized bodies early, a 50 MB upload peaks at 155 MB. Before that
change it peaked at 426 MB. The final judge path peaked at 326 MB in the container with 13 runs held. Voice notes
are capped at 10 MB in demo mode.

The demo holds at most `DEMO_MAX_RUNS` (20) runs, about 7 MB each. In the container at 0.1 CPU, a cached tank-farm
sample run took 93 s (24 entries, plan OPTIMAL).

## Builder steps

### 1. Private Hugging Face dataset (the data bundle)

1. On huggingface.co (signed in as `joshuakarthik2005`), open **New → Dataset**.
2. Name: `walkdown-demo-bundle`. Visibility: **Private**. Click **Create dataset**.
3. Open **Files and versions → Add file → Upload files**. Drop `G:\walkdown-data\deploy\walkdown-demo-bundle.tar.gz`
   (18 MB) and click **Commit changes to main**. The current bundle (HF commit b24b31e, 2026-11-04, 1,714 files) also
   holds the Balanced (v2) verdicts for the tank-farm and valve-tank samples, so neither sensitivity setting calls the
   verifier in the demo.
4. Create a read token for Render: open **Settings → Access Tokens → Create new token → Fine-grained**.
   - Name it `render-walkdown`.
   - Under **Repositories permissions**, select `datasets/joshuakarthik2005/walkdown-demo-bundle` and tick
     **Read access to contents of selected repos**.
   - Click **Create token** and copy it. You paste it only into Render.

### 2. Render (API)

1. On render.com, choose **Get Started → GitHub**. Sign in with GitHub. Skip any plan or card prompt; if a card is
   required, stop.
2. Open **New → Web Service → Public Git Repository**. Paste `https://github.com/joshuakarthik2005/Walkdown` and click
   **Connect**.
3. Set the fields:
   - Name: `walkdown-api`
   - Language: **Docker**
   - Branch: `main`
   - Region: **Singapore**
   - Instance type: **Free**
4. Under **Environment Variables**, add each of these:

   | Key | Value |
   |---|---|
   | `DEMO_MODE` | `true` |
   | `WALKDOWN_DATA_DIR` | `/data` |
   | `DEMO_DAILY_CAP_USD` | `5` |
   | `WALKDOWN_SOLVER_WORKERS` | `2` |
   | `DEMO_BUNDLE_REPO` | `joshuakarthik2005/walkdown-demo-bundle` |
   | `HF_TOKEN` | the fine-grained token from step 1 |
   | `MODEL_API_KEY` | the Meta key from your `.env` |
   | `BASETEN_API_KEY` | the Baseten key from your `.env`. Optional: On-prem runs are off in demo mode. |
   | `CORS_ORIGINS` | leave empty for now; filled in at step 3.5 |

5. Under **Advanced**, set **Health Check Path** to `/health` and **Auto-Deploy** to **No**.
6. Click **Deploy Web Service**. The first build takes about 5 minutes.
7. When the log shows `bundle: unpacked walkdown-demo-bundle.tar.gz` and `Application startup complete`, copy the
   service URL (`https://walkdown-api-XXXX.onrender.com`). Opening `<url>/health` shows `"demo_mode":true`.

### 3. Vercel (UI)

1. On vercel.com, choose **Sign Up → Hobby → Continue with GitHub**. If a card is asked for, stop.
2. Open **Add New… → Project**, and **Import** `joshuakarthik2005/Walkdown`. Grant access to that repository only.
3. Under **Root Directory**, click **Edit** and choose `frontend`. Framework Preset: **Next.js** (detected).
4. Under **Environment Variables**, add `NEXT_PUBLIC_API_URL` set to the Render URL from step 2.7, with no trailing
   slash. Click **Deploy**.
5. Copy the production domain (`https://walkdown-XXXX.vercel.app`). In Render, open **walkdown-api → Environment**,
   set `CORS_ORIGINS` to that domain, then click **Save, rebuild and deploy**.

Send Claude the two URLs. Claude then runs the smoke test and puts the public URL in the README and the UI.

## Smoke test (public URL)

Run each check in a clean browser window, and again at phone width:

- the waking notice, after the service has been idle for 15 minutes;
- sample cards with thumbnails and credits;
- all three finished examples;
- a cached sample run;
- a replan;
- a copilot question;
- PDF and CSV exports;
- an On-prem run, which should return 403 with a note;
- an upload over the limit (413), and a voice note in the wrong format (400);
- the spend-cap message, checked locally with `DEMO_DAILY_CAP_USD=0`.

## Rebuilding the bundle

After rebuilding the examples (`python -m backend.api.examples`):

1. Copy the clips, examples and `runs/decoded_masks` into a folder.
2. Run `WALKDOWN_DATA_DIR=<that folder> python -m backend.api.bundle pack <out>.tar.gz`.
3. Upload the tarball to the dataset, replacing the old file.
4. In Render, run **Manual Deploy → Restart service**.

To test the container locally without Hugging Face, mount the tarball and set `DEMO_BUNDLE_PATH`:

    docker build -t walkdown-api .
    docker run --memory 512m --cpus 0.1 -p 8002:10000 --env-file .env -e DEMO_BUNDLE_PATH=/b.tar.gz \
      -v <tarball>:/b.tar.gz:ro walkdown-api
