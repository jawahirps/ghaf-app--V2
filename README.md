# Ghaf App — RCM & Clinical Platform

React + FastAPI application for:

- Login tracking (auth + audit trail in `login_logs`)
- Clinical profile setup (`clinical_profiles`)
- Triggering the DHA XML Sync pipeline (DHA Shafafiya / eClaimLink `ClaimSubmission` & `RemittanceAdvice` XML)
- An **Analytics & Financial Insights** tab embedding Metabase dashboards for payer breakdowns, collections, AR aging, and denial trends

## Project structure

```
ghaf-app/
  backend/                FastAPI app
    app/
      models.py            SQLAlchemy models (facilities, users, login_logs,
                            clinical_profiles, claims, remittances, raw_xml_store, fetch_log, ...)
      schemas.py            Pydantic request/response models
      database.py           SQLAlchemy engine/session
      security.py           JWT auth, password hashing, role checks
      config.py             Settings (.env) + Metabase dashboard ID map
      seed.py               First-run seed (default facility + admin user)
      main.py               FastAPI app entrypoint
      routers/
        auth.py             /api/auth — login, /me, login_logs, user mgmt
        clinical_profiles.py /api/clinical-profiles — CRUD
        dha_sync.py         /api/dha-sync — upload XML, trigger pipeline, history
        analytics.py        /api/analytics — KPI summary + Metabase embed URLs
      services/
        dhpo_parser.py      Streaming DHA/DHPO XML parser (ClaimSubmission/RemittanceAdvice)
        fetch_service.py     DHASyncService — live eClaimLink (DHPO) fetch + parse orchestration
        metabase.py          Signed Metabase embed URL generator
    scripts/
      run_dha_sync.py        Standalone/cron worker — runs DHASyncService.run_sync_pipeline(...)
    requirements.txt
    .env.example
  frontend/                React (Vite + Tailwind)
    src/
      pages/
        Login.jsx
        Dashboard.jsx
        ClinicalProfiles.jsx
        DhaSync.jsx
        Analytics.jsx       "Analytics & Financial Insights" — Metabase embeds
        LoginActivity.jsx
      components/
        Layout.jsx, Sidebar.jsx, ProtectedRoute.jsx, MetabaseEmbed.jsx
      context/AuthContext.jsx
      api/client.js
```

## Backend setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL, JWT_SECRET_KEY, METABASE_* as needed
uvicorn app.main:app --reload --port 8000
```

On first run, the app creates SQLite tables (or your configured Postgres DB)
and seeds:

- A demo facility (`GHAF-001`)
- An admin user: `admin@ghafapp.local` / `ChangeMe123!` — **change this immediately**

API docs: http://localhost:8000/docs

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api/*` to `http://localhost:8000`.

## DHA XML Sync pipeline

1. **DHA XML Sync** view → upload a `ClaimSubmission` or `RemittanceAdvice`
   XML file (DHA Shafafiya / eClaimLink schema). This stages a row in
   `raw_xml_store` with `parse_status = "pending"`.
2. Click **Trigger DHA XML Sync** (`POST /api/dha-sync/trigger`). This runs
   `DHPOXmlParser.run_pending()`, which streams each pending file with
   `lxml.iterparse`, upserts normalized `claims` / `remittances` rows
   (with nested diagnoses, activities, observations, and remittance activity
   detail), and records a `fetch_log` entry.
3. Quarantined files (parse errors) and run history are visible in the same
   view.

### Live eClaimLink (DHPO) fetch

The **3. Live eClaimLink Fetch** panel calls `POST /api/dha-sync/fetch` with
a `facility_id`, `date_from`, and `date_to`. This is handled by
`DHASyncService.run_sync_pipeline()` (`backend/app/services/fetch_service.py`),
which:

1. Looks up the facility's eClaimLink credentials
   (`Facility.eclaimlink_username` / `Facility.credential_key` /
   `Facility.dhpo_provider_id`).
2. Calls `_fetch_transactions(...)` for `ClaimSubmission` and
   `RemittanceAdvice` over the given date range, staging any returned XML in
   `raw_xml_store` (`parse_status = "pending"`).
3. Runs `DHPOXmlParser.run_pending()` over everything pending (newly fetched
   plus any manually uploaded files) and finalizes a `fetch_log` row with
   fetch/parse/error counts and an overall `success` / `partial` / `failed`
   status.

**`_fetch_transactions` is a scaffold** — the DHPO/eClaimLink portal exposes
a per-facility SOAP service (WSDL). Implement the real `SearchTransactions` /
`DownloadTransaction` calls there (e.g. with `zeep`), using
`facility.eclaimlink_username` and `facility.credential_key`. Until then, the
endpoint returns 0 fetched records but still parses anything already staged,
so manual upload + trigger continues to work.

#### Standalone / cron worker

For scheduled (e.g. nightly) pulls without going through the API:

```bash
cd backend
python scripts/run_dha_sync.py --facility-id 1 --from 2026-04-16 --to 2026-04-23
```

This uses the same `DHASyncService.run_sync_pipeline(...)` and reads
`DATABASE_URL` from `backend/.env`.

## Analytics & Financial Insights (Metabase Embeds)

The Analytics tab renders Metabase dashboards inside `<iframe>`s using
**signed static embedding**:

1. In Metabase: **Admin > Settings > Embedding** → enable embedding and copy
   the **Embedding secret key** into `METABASE_SECRET_KEY` in `backend/.env`.
   Set `METABASE_SITE_URL` to your Metabase base URL.
2. Build dashboards for: financial overview, payer breakdown, collections,
   AR aging, denials. For each, open the dashboard → **Sharing** → enable
   embedding, and note its dashboard ID.
3. Update the `METABASE_DASHBOARDS` mapping in `backend/app/config.py` with
   those dashboard IDs.
4. (Recommended) Add a `facility_id` field filter to each dashboard's
   underlying questions — the backend passes the current user's
   `facility_id` as an embed parameter for row-level scoping.

Until `METABASE_SECRET_KEY` is set, the Analytics tab shows a placeholder
message per dashboard instead of failing the whole page.

## Default roles

`admin`, `billing_manager`, `clinician`, `staff` — enforced via
`require_roles(...)` dependencies (e.g. only `admin`/`billing_manager` can
upload XML, trigger sync, or view login activity; only `admin` can manage
users or delete clinical profiles).
