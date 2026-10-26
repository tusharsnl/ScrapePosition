# ShipFinder Vessel Position Tracker

This repository scrapes the vessels currently assigned to active orders in
OrangeTechShippingWeb, sends each new position to the website over HTTPS, and
keeps a CSV history in this repository. It uses the existing GitHub Actions
runner; it does not require a separate Azure job, container registry, or direct
GitHub-to-SQL connection.

## Workflow

The `Vessel Position Tracker` workflow runs every two hours (UTC), or manually
from the GitHub **Actions** tab. It:

1. Calls `GET <VESSEL_SYNC_API_URL>?action=vessels` with the
   `X-Vessel-Sync-Key` header to get the distinct vessels that still need
   tracking.
2. Scrapes each returned vessel using `shipfinder_vessel_position.py`, retrying
   once and reporting any vessel that still fails.
3. POSTs only rows appended during that run to the website endpoint. The
   website inserts the positions into `dbo.Mst_VesselPositionData` and updates
   order arrival tracking. The order map already reads the position table.
4. Commits the updated CSV using the repository's built-in Actions token.

Orders are considered active until `DeliverStatus` is `Delivered`. The website
stops requesting a vessel for an order after two observations, at least 90
minutes apart and within 10 nautical miles of the destination. A vessel
assigned to another active order that still needs tracking remains on the
requested list.

## Configure GitHub Actions

In the scraper repository's **Settings → Secrets and variables → Actions**:

1. Add repository variable `VESSEL_SYNC_API_URL`, set to the HTTPS endpoint,
   for example `https://YOUR-APP.azurewebsites.net/VesselPositionSync.ashx`.
2. Add repository secret `VESSEL_SYNC_API_KEY`. Its value must exactly match
   the App Service application setting `VesselSyncApiKey`.
3. Under **Settings → Actions → General → Workflow permissions**, allow read
   and write access so the workflow can commit `vessel_positions.csv`.
4. Run **Actions → Vessel Position Tracker → Run workflow** and inspect the
   logs. The workflow fails if it cannot sync with the site or if a vessel
   still fails after its retry.

Only `shipfinder-hourly.yml` has a scheduled trigger. The duplicate `main.yml`
and the schedule-test workflow have manual dispatch only, to prevent duplicate
scrapes and unnecessary Actions usage.

## Website and database prerequisites

In Azure App Service, enable **HTTPS Only** and add application setting
`VesselSyncApiKey` with a long random value. Store the same value only as the
GitHub Actions secret above; do not put it in source control or in the CSV.
The site also needs its existing SQL connection setting named `con` and access
to the database tables.

Apply these migrations to the website's Azure SQL database if they have not
already been applied:

- `Database/Migrations/20261020_AddVesselPositionData.sql`
- `Database/Migrations/20261025_AddCustomerOrderVesselTracking.sql`

The endpoint uses the website's existing SQL connection configuration; the
GitHub runner never receives database credentials or connects to SQL directly.

## Run locally

Install Python 3.12 and the scraper dependencies:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set `VESSEL_SYNC_API_URL` and `VESSEL_SYNC_API_KEY` in the local process
environment without committing them, then run:

```powershell
python sync_vessel_positions.py vessels
python shipfinder_vessel_position.py "WAN HAI 517" --headless --output vessel_positions.csv
```

The CSV contains a historical record of scraped positions. The site database
is the data source used by the order map; committing the CSV alone does not
update the website.

## Limitations

- GitHub scheduled workflows are best-effort, run in UTC, and can be delayed.
- Scheduled workflows may be disabled after prolonged repository inactivity.
- ShipFinder can change its site or selectors; review workflow logs if scraping
  starts failing.
