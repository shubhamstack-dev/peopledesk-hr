# PeopleDesk HR: React + Python + MySQL

PeopleDesk HR, rebuilt from the single-file browser app as three tiers:

| Tier | Folder | Technology |
|---|---|---|
| Frontend | `frontend/` | React 18, Vite |
| Middleware | `backend/` | Python 3.10+, FastAPI, SQLAlchemy |
| Database | `database/` | MySQL 8.0+ (MariaDB 10.5+ also works) |

All features of the original are kept: personnel, recruitment, leave, time and shifts, overtime, performance, exits and rehire, Indian statutory payroll (PF, ESI, PT, LWF, TDS, Labour Code wages) and the SAP HR export.

## Version 2

Reporting structure with dotted lines, moving people on the organisation chart, approval workflows, shifts or time management per company, goal templates, fixed and variable pay, leave carry forward and encashment, expense claims, employee enrolment with department checklists and assets, promotions and progression, and activity logs. **Upgrade steps and how to use each feature: [docs/VERSION-2.md](docs/VERSION-2.md).** The database upgrades itself when the API starts.

## 1. Database

```sql
-- as a MySQL administrator
SOURCE database/schema.sql;
CREATE USER 'peopledesk'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON peopledesk.* TO 'peopledesk'@'localhost';
```

## 2. Backend (API)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # set DATABASE_URL and JWT_SECRET
uvicorn app.main:app --port 8000 --reload
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173 (passes /api to port 8000)
```

Open http://localhost:5173. On an empty database you get first-time setup: create the group, first company and the group administrator, or choose **Explore with demo data** (two companies, 18 employees, six months of attendance and payroll).

## Production

```bash
cd frontend && npm run build          # creates frontend/dist
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

The API serves the built React app itself, so one address serves everything. Put it behind HTTPS (nginx, Caddy or a load balancer) and set `COOKIE_SECURE=true`.

Before real use:
- Set a long random `JWT_SECRET` in `.env`.
- In **Settings and data**, turn off *Try the app as*. While it is on, anyone can sign in as anyone.
- Back up MySQL regularly (`mysqldump peopledesk`). The in-app backup is a convenience, not a substitute.

## Google sign-in

1. Create a Google Cloud OAuth client ID of type *Web application*.
2. Add your site's address as an authorised JavaScript origin.
3. Paste the client ID in **Personnel Information → Users from Google Workspace**.

The browser receives the Google ID token, and the **server verifies it** (signature, audience, expiry, verified e-mail, Workspace domain) before signing the person in. The original app could only decode the token in the browser.

For directory sync, also enable the Admin SDK API on that project.

## How it fits together

```
React (browser)                    Python API                         MySQL
───────────────                    ──────────                         ─────
Sign-in, setup, menu,      ─────►  /api/auth/*  bcrypt, Google        auth_credentials
Home, Approvals, Settings          verification, http-only cookie
Feature screens + rules    ◄─────  /api/state   filtered per person   34 tables, one per kind
(engine.js)                ─────►  /api/sync    permission checks,    of record (JSON + indexed
  changes diffed per record        all-or-nothing                     columns), roster, audit_log
```

**Frontend**
- React components: `src/App.jsx`, `src/components/Shell.jsx` and `src/pages/` (Login, Setup, Home, Approvals, Settings).
- `src/engine/engine.js` holds the business rules and the other feature screens, carried over unchanged from the original. They run inside React through `PageHost.jsx`.
- `src/engine/sync.js` compares the in-memory data with what the server last confirmed and sends only new, changed and deleted records. The server applies each batch completely or not at all.
- Every minute, and when you return to the tab, the app checks whether someone else saved changes and reloads if so.

**Database**
- Each business record is stored whole in a `data` JSON column. The fields the server filters or checks permissions on (company, employee, status, dates, e-mail, role, manager) are copied into indexed columns.
- To change which columns exist, edit `backend/app/collections.py`, then run `python backend/scripts/gen_schema.py`.

**Who sees what**, enforced on the server in `backend/app/policy.py`:
- HR sees and changes everything in the companies they administer. The group administrator sees and changes everything.
- Others receive what the screens need, such as names, the reporting line and team leave. Colleagues' salary, bank, PAN/Aadhaar/UAN, personal contact details, year of birth, payslips and tax declarations are removed before data leaves the server. So is the activity log.
- Employees cannot approve their own requests, or change their role, salary or job record.
- Managers can act only on people in their reporting line.
- HR-only data (policies, pay components, payroll runs, settings) is refused from anyone else.
- A refused save shows its reason, and the screen reloads the server's data.

## Moving more screens to React

Home, Approvals and Settings show the pattern:
1. Write a component in `src/pages/` that reads data through the engine's exported helpers. Keep `data-act="…"` on buttons to reuse the existing actions, or call the API directly.
2. List the page in `App.jsx`.
3. Add the page to `REACT_PAGES` in `frontend/scripts/build-engine.py`, and delete its `VIEWS.x` from the engine.

`npm run engine` regenerates `engine.js` from `original/PeopleDesk_HR.html`. You only need it if you start again from the original file. After you edit `engine.js` by hand, don't re-run it.

## Things to know

- **Excel library.** Export and import use SheetJS. `package.json` installs it from SheetJS's own CDN, because the npm copy (0.18.5) is outdated. If your network blocks `cdn.sheetjs.com`, change the version to `0.18.5`.
- **Document numbering.** Employee, requisition and offer numbers come from a shared counter. If two HR users create one at the same moment, the numbers can collide. Check before relying on them for statutory documents.
- **Settings scope.** Statutory rates and settings apply group-wide, as in the original, and any HR administrator can change them.
- **Moving from the browser version.** Download a backup from the old browser version and restore it in **Settings and data**. Old back-up passwords keep working and are upgraded to bcrypt on first sign-in.
