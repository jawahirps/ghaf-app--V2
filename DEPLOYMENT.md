# Ghaf App — Deployment Guide (Windows Server)

This guide covers deploying Ghaf App (FastAPI backend + React/Vite
frontend) on **Windows Server** (2019/2022) using IIS as the web
front door, a Windows Service for the FastAPI/Uvicorn backend, and
Task Scheduler for the DHA XML Sync worker.

---

## 1. Architecture overview

| Component | Tech | Hosted as |
|---|---|---|
| Backend API | FastAPI + SQLAlchemy + Uvicorn | Windows Service (NSSM), bound to `127.0.0.1:8000` |
| Database | PostgreSQL for Windows (recommended) or SQLite | Local service or remote instance |
| Frontend | React + Vite, built to static assets | IIS website (static files) |
| Reverse proxy | IIS + Application Request Routing (ARR) + URL Rewrite | Proxies `/api/*` to `127.0.0.1:8000` |
| Analytics | Metabase (separate service, signed embeds) | Optional — its own Windows Service or VM |
| Worker | `scripts/run_dha_sync.py` | Windows Task Scheduler job |

IIS serves the built React app as static files on port 443 (HTTPS) and
reverse-proxies any request under `/api/` to the FastAPI backend running
locally on port 8000. This keeps everything on one origin, so
`CORS_ORIGINS` can be left to the app's own domain (or even omitted).

---

## 2. Prerequisites

- Windows Server 2019 or 2022 with administrator access
- [Python 3.11+ for Windows](https://www.python.org/downloads/windows/)
  (check "Add python.exe to PATH" during install)
- [Node.js 18+ LTS for Windows](https://nodejs.org/) (for building the
  frontend)
- [PostgreSQL for Windows](https://www.postgresql.org/download/windows/)
  (or use SQLite for small/single-facility deployments)
- IIS enabled with:
  - **Application Request Routing (ARR)** and **URL Rewrite** modules
    (install via the [IIS download page](https://www.iis.net/downloads))
- [NSSM](https://nssm.cc/) (Non-Sucking Service Manager) — runs the
  FastAPI app as a Windows Service
- A TLS certificate for your domain (internal CA, Let's Encrypt via
  `win-acme`, or a purchased cert) bound in IIS
- A Metabase instance, if using the Analytics & Financial Insights tab

---

## 3. Get the application files onto the server

Copy the `ghaf-app/` project folder to the server, e.g.:

```
C:\inetpub\ghaf-app\
  backend\
  frontend\
```

(All paths below assume this location — adjust as needed.)

---

## 4. Configure environment variables

Copy `backend\.env.example` to `backend\.env` and edit it with Notepad
or your editor of choice:

```ini
ENVIRONMENT=production

# Use Postgres in production (Windows-hosted instance)
DATABASE_URL=postgresql+psycopg2://ghaf:STRONG_PASSWORD@localhost:5432/ghaf_app

JWT_SECRET_KEY=<generate a long random value>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Same-origin via IIS reverse proxy — leave as your public site URL
CORS_ORIGINS=https://app.ghafservices.com

# Metabase static embedding (Analytics & Financial Insights tab)
METABASE_SITE_URL=https://metabase.ghafservices.com
METABASE_SECRET_KEY=<embedding secret from Metabase Admin > Settings > Embedding>
METABASE_TOKEN_EXPIRY_SECONDS=600
```

To generate `JWT_SECRET_KEY` in PowerShell:

```powershell
-join ((48..57) + (97..102) | Get-Random -Count 64 | % {[char]$_})
```

Or, in a Python prompt: `import secrets; print(secrets.token_hex(32))`

Never commit `.env` to source control — it's already in `.gitignore`.

---

## 5. Database setup (PostgreSQL on Windows)

1. After installing PostgreSQL, open **SQL Shell (psql)** (or pgAdmin)
   and run:

   ```sql
   CREATE DATABASE ghaf_app;
   CREATE USER ghaf WITH PASSWORD 'STRONG_PASSWORD';
   GRANT ALL PRIVILEGES ON DATABASE ghaf_app TO ghaf;
   ```

2. Point `DATABASE_URL` at it (see step 4 above). `psycopg2-binary` is
   already in `requirements.txt`.

3. On first start, `app.main` calls `init_db()` (creates all tables from
   `models.py`) and `run_seed()` (creates a default facility `GHAF-001`
   and an admin user `admin@ghafapp.local` / `ChangeMe123!` **only if the
   database is empty**).

   **Change the seeded admin password immediately after first login**, or
   create your own admin user and remove/disable the seed step before
   exposing the instance publicly.

> For ongoing schema changes, introduce Alembic migrations rather than
> relying on `create_all` once the schema stabilizes in production.

---

## 6. Backend — install dependencies

Open **PowerShell as Administrator**:

```powershell
cd C:\inetpub\ghaf-app\backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Smoke-test it runs:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Visit `http://127.0.0.1:8000/api/health` from the server (or via
`curl`/`Invoke-WebRequest`) to confirm a healthy response, then `Ctrl+C`
to stop — the next step runs this as a managed service instead.

---

## 7. Run the backend as a Windows Service (NSSM)

1. Download [NSSM](https://nssm.cc/) and extract `nssm.exe` somewhere on
   `PATH`, e.g. `C:\nssm\nssm.exe`.

2. Install the service:

   ```powershell
   nssm install GhafAppBackend
   ```

   In the GUI that opens:
   - **Path**: `C:\inetpub\ghaf-app\backend\.venv\Scripts\python.exe`
   - **Startup directory**: `C:\inetpub\ghaf-app\backend`
   - **Arguments**: `-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2`

   On the **Environment** tab (or via `nssm set GhafAppBackend AppEnvironmentExtra`),
   you can also point Uvicorn at the `.env` file — `pydantic-settings`
   already reads `backend\.env` automatically when the working directory
   is `backend\`.

3. Start it:

   ```powershell
   nssm start GhafAppBackend
   ```

4. Confirm it's listening:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/api/health
   ```

The service will now auto-start on boot and restart if it crashes
(NSSM handles restart policies under the **Exit actions** tab).

---

## 8. Frontend — build static assets

```powershell
cd C:\inetpub\ghaf-app\frontend
npm install
npm run build
```

This produces `frontend\dist\` — the static files IIS will serve.

If the frontend and backend are served from the same domain via the IIS
reverse-proxy setup below, `src/api/client.js`'s relative `/api` base URL
works unchanged and `CORS_ORIGINS` only needs your public site URL.

---

## 9. IIS site — serve the frontend + proxy `/api/*`

1. Open **IIS Manager** → **Sites** → **Add Website**:
   - **Site name**: `GhafApp`
   - **Physical path**: `C:\inetpub\ghaf-app\frontend\dist`
   - **Binding**: HTTPS, port 443, with your certificate; add an HTTP→HTTPS
     redirect binding on port 80 if desired

2. Install **Application Request Routing (ARR)** and **URL Rewrite** if
   not already present (Web Platform Installer or direct MSI from
   iis.net).

3. In **ARR** (server-level): enable proxy
   (**Application Request Routing Cache → Server Proxy Settings →
   Enable proxy**).

4. Add a `web.config` to `frontend\dist\` (or edit it after build) with
   two URL Rewrite rules — one to proxy `/api/*` to the backend, and one
   SPA fallback so client-side routes (e.g. `/dha-sync`, `/analytics`)
   don't 404 on refresh:

   ```xml
   <?xml version="1.0" encoding="utf-8"?>
   <configuration>
     <system.webServer>
       <rewrite>
         <rules>
           <rule name="ProxyApi" stopProcessing="true">
             <match url="^api/(.*)" />
             <action type="Rewrite" url="http://127.0.0.1:8000/api/{R:1}" />
           </rule>
           <rule name="SPA Fallback" stopProcessing="true">
             <match url=".*" />
             <conditions logicalGrouping="MatchAll">
               <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
               <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
             </conditions>
             <action type="Rewrite" url="/index.html" />
           </rule>
         </rules>
       </rewrite>
       <staticContent>
         <remove fileExtension=".json" />
         <mimeMap fileExtension=".json" mimeType="application/json" />
       </staticContent>
     </system.webServer>
   </configuration>
   ```

   Because `npm run build` regenerates `dist\`, keep a copy of this
   `web.config` in `frontend\` (e.g. `frontend\iis\web.config`) and copy
   it into `dist\` as part of your deploy script after each build.

5. Browse to `https://app.ghafservices.com` — the React app should load,
   and API calls to `/api/...` should reach the backend service.

---

## 10. Metabase (Analytics & Financial Insights) — optional

**You can deploy and run Ghaf App in full without this section.** If
`METABASE_SECRET_KEY` is left blank in `backend\.env`, the Analytics &
Financial Insights tab simply shows a "not configured" placeholder for
each chart — every other feature (login, clinical profiles, DHA XML
Sync, live eClaimLink fetch, dashboard KPI summary) works normally. Skip
straight to step 11 if you don't have a Metabase instance; you can come
back and complete this section later without redeploying anything else.

1. Run Metabase on its own Windows Service/VM or container, on a subdomain
   such as `metabase.ghafservices.com` (Metabase ships as a Java JAR or
   Docker image — either works on Windows Server with Docker Desktop/WSL2).
2. In Metabase: **Admin → Settings → Embedding** → enable embedding, copy
   the **Embedding secret key** into `METABASE_SECRET_KEY` in
   `backend\.env`, then restart the `GhafAppBackend` service
   (`nssm restart GhafAppBackend`).
3. Build the 5 dashboards (financial overview, payer breakdown,
   collections, AR aging, denials), enable embedding per dashboard, and
   record their dashboard IDs.
4. Update `METABASE_DASHBOARDS` in `backend\app\config.py` with those IDs
   and restart the backend service.
5. Add a `facility_id` field filter to each dashboard's underlying
   questions for row-level scoping (the backend passes the current user's
   `facility_id` as an embed parameter).

If `METABASE_SECRET_KEY` is unset, the Analytics tab degrades gracefully
to a placeholder per dashboard — safe to deploy before Metabase is ready.

---

## 11. DHA XML Sync — scheduled worker (Task Scheduler)

To run the eClaimLink (DHPO) fetch + parse pipeline on a schedule, create
a **Windows Task Scheduler** task that runs
`backend\scripts\run_dha_sync.py` nightly:

1. Open **Task Scheduler** → **Create Task...**
2. **General**: name it `Ghaf App - DHA Sync`, run whether user is logged
   on or not, run with highest privileges.
3. **Triggers**: New → Daily, set the time (e.g. 02:00).
4. **Actions**: New → Start a program:
   - **Program/script**: `C:\inetpub\ghaf-app\backend\.venv\Scripts\python.exe`
   - **Add arguments**:
     ```
     scripts\run_dha_sync.py --facility-id 1 --from 2026-04-16 --to 2026-04-23
     ```
     In practice, wrap this in a small `.bat`/PowerShell script that
     computes "yesterday" and "today" dynamically, e.g.:

     ```powershell
     # run_dha_sync.ps1
     $yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
     $today = (Get-Date).ToString("yyyy-MM-dd")
     & "C:\inetpub\ghaf-app\backend\.venv\Scripts\python.exe" `
       "C:\inetpub\ghaf-app\backend\scripts\run_dha_sync.py" `
       --facility-id 1 --from $yesterday --to $today
     ```

     Then set the Task Scheduler action's program to
     `powershell.exe` with arguments
     `-ExecutionPolicy Bypass -File "C:\inetpub\ghaf-app\run_dha_sync.ps1"`.
   - **Start in**: `C:\inetpub\ghaf-app\backend`

5. Redirect output to a log file for troubleshooting (add
   `*>> C:\inetpub\ghaf-app\logs\dha_sync.log` to the PowerShell script).

Before relying on this in production, implement the real DHPO SOAP calls
in `_fetch_transactions` (`backend\app\services\fetch_service.py`) using
each facility's `eclaimlink_username` / `credential_key` /
`dhpo_provider_id`.

---

## 12. Windows Firewall

Allow inbound HTTPS (443) and HTTP (80, if used for redirect only) on the
server's Windows Firewall. The backend on port 8000 should **not** be
exposed externally — only IIS (via the reverse proxy) and `localhost`
need access to it:

```powershell
New-NetFirewallRule -DisplayName "Ghaf App HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
New-NetFirewallRule -DisplayName "Ghaf App HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

---

## 13. Security checklist before go-live

- [ ] Change/remove the seeded admin account (`admin@ghafapp.local`)
- [ ] Generate a strong, unique `JWT_SECRET_KEY` (not the example value)
- [ ] Set `ENVIRONMENT=production`
- [ ] Restrict `CORS_ORIGINS` to your real frontend domain only
- [ ] Serve everything over HTTPS (TLS bound in IIS)
- [ ] Use PostgreSQL (not SQLite) with regular automated backups
      (`pg_dump` via a scheduled task, or your backup tooling)
- [ ] Confirm port 8000 (Uvicorn) is bound to `127.0.0.1` only, not exposed
      via the firewall
- [ ] Store secrets (`JWT_SECRET_KEY`, DB password, `METABASE_SECRET_KEY`)
      with restricted NTFS permissions on `backend\.env`
- [ ] Review role assignments (`admin`, `billing_manager`, `clinician`,
      `staff`) for each seeded/created user
- [ ] Set up log review for the `GhafAppBackend` service (Event Viewer or
      a log file via NSSM's stdout/stderr redirection) and the DHA sync
      Task Scheduler job
- [ ] Confirm `eclaimlink_username` / `credential_key` per facility are
      stored securely before enabling live fetch

---

## 14. Health checks & smoke test

After deployment, from the server or a client machine:

```powershell
# Backend health (via IIS proxy)
Invoke-WebRequest https://app.ghafservices.com/api/health

# Login (replace with real admin credentials)
Invoke-WebRequest -Method POST https://app.ghafservices.com/api/auth/login `
  -Body @{ username = "admin@ghafapp.local"; password = "<password>" }

# Frontend
Invoke-WebRequest https://app.ghafservices.com/
```

Then log in via the browser and confirm: Dashboard loads, Clinical
Profiles CRUD works, DHA XML Sync upload/trigger/fetch works, and the
Analytics tab either renders Metabase dashboards or shows the
configuration placeholder.

---

## 15. Updating the application

```powershell
# 1. Pull/copy new code into C:\inetpub\ghaf-app

# 2. Backend
cd C:\inetpub\ghaf-app\backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
nssm restart GhafAppBackend

# 3. Frontend
cd C:\inetpub\ghaf-app\frontend
npm install
npm run build
# re-copy web.config into dist\ if it was regenerated
```

IIS picks up the new static files immediately; no IIS restart is needed
unless `web.config` rewrite rules changed.
