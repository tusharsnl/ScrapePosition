# ShipFinder Vessel Position Tracker

Tracks the current position (latitude/longitude, speed, course, destination,
etc.) of one or more vessels on [ShipFinder](https://www.shipfinder.com/) and
appends the results to `vessel_positions.csv`, building up a position history
over time.

Runs automatically **every hour via GitHub Actions** — no local machine or
server needs to stay on. GitHub's own runners execute the script and commit
the updated CSV straight back into this repository.

## What it tracks

Currently configured (see the `Fetch vessel positions` step in
[`.github/workflows/shipfinder-hourly.yml`](.github/workflows/shipfinder-hourly.yml)):

- `WAN HAI 517` (searched by name, "Cargo ship" result selected)
- `9400186` (searched by IMO number)

To add or remove vessels, edit that step and add another
`python shipfinder_vessel_position.py "<name-or-IMO>" --headless --output vessel_positions.csv`
line.

## How it works

1. **`schedule: cron: "0 * * * *"`** triggers the workflow at the top of every
   hour (UTC). You can also trigger a run manually from the **Actions** tab
   ("Run workflow" button), since the workflow also listens for
   `workflow_dispatch`.
2. GitHub spins up a fresh Ubuntu runner, installs Python + Playwright +
   Chromium, and runs `shipfinder_vessel_position.py` once per tracked
   vessel — each run appends a row to `vessel_positions.csv`.
3. The workflow then commits and pushes the updated CSV back to this repo
   (using the built-in `GITHUB_TOKEN`, no extra secrets needed), so the data
   persists between runs even though each run's VM is thrown away afterward.

## Setting this up in your own GitHub repo

```bash
cd "ShipFinder Vessel Tracker"
git init
git add .
git commit -m "Initial commit: ShipFinder hourly vessel tracker"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

Then, in your repo on GitHub:

1. Go to **Settings → Actions → General → Workflow permissions** and select
   **"Read and write permissions"** (required so the workflow can push the
   updated CSV back to the repo).
2. Go to the **Actions** tab — you should see "Hourly ShipFinder Vessel
   Position Tracker" listed. Click **Run workflow** to trigger it manually
   and confirm it works end-to-end before waiting for the first scheduled run.
3. After that, it will run automatically every hour, and `vessel_positions.csv`
   will grow with a new row per tracked vessel each hour.

## Known limitations

- **Cron delay**: GitHub's `schedule` trigger is best-effort and can be
  delayed several minutes during periods of high platform load — it is not
  guaranteed to fire at exactly :00 every hour.
- **60-day auto-disable**: GitHub automatically disables scheduled workflows
  in a repository that has had no other activity (commits, etc.) for 60
  days. A manual re-enable (or any commit) resets this.
- **Occasional fetch failures**: ShipFinder's info panel can occasionally be
  slow to render, causing a single fetch to fail. The workflow retries each
  vessel once before giving up for that hour; a missed hour just means a
  small gap in the CSV, not a broken workflow run.
- **Data format**: latitude/longitude are stored both as ShipFinder's native
  degrees-minutes strings (e.g. `22-14.609N`) and as converted signed decimal
  degrees (e.g. `22.243483`) for easier charting/mapping.

## Running it locally (optional)

```bash
pip install -r requirements.txt
playwright install chromium
python shipfinder_vessel_position.py "WAN HAI 517" --headless --output vessel_positions.csv
```
