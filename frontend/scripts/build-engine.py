"""
Builds src/engine/engine.js from the original single-file app (PeopleDesk_HR.html).

The business rules (Indian statutory payroll, leave, time, performance, exits,
recruitment) and the feature screens are taken over unchanged. What changes:
  - browser storage (IndexedDB/localStorage) is replaced by the server sync in sync.js
  - sign-in, first-time setup, the menu shell, Home, Approvals and Settings move to React
  - the module exports what the React components use

Run:  npm run engine   (reads ../original/PeopleDesk_HR.html)

WARNING: since version 2, src/engine/engine.js is edited directly and holds features
that are not in the original HTML. Re-running this script would remove them, so it
refuses unless you pass --force.
"""
import pathlib
import re
import sys

_target = pathlib.Path(__file__).resolve().parents[1] / "src" / "engine" / "engine.js"
if _target.exists() and "PeopleDesk v2" in _target.read_text(encoding="utf-8") and "--force" not in sys.argv:
    raise SystemExit("engine.js contains the version 2 features; regenerating it would remove them. Use --force only if you mean to.")
sys.argv = [a for a in sys.argv if a != "--force"]

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "PeopleDesk_HR.html").read_text(encoding="utf-8")
scripts = list(re.finditer(r"<script[^>]*>(.*?)</script>", src, re.S))
app_js = max((m.group(1) for m in scripts), key=lambda s: ("VIEWS" in s, len(s)))   # the app, not the Excel library
L = app_js.split("\n")
# L[0] is the empty remainder after <script>; make L 1-based like an editor
if L and L[0].strip() == "":
    L = L[1:]
L = [""] + ["<script>"] + L   # line 1 was the <script> tag in the analysis


def find(pattern, start=1):
    for i in range(start, len(L)):
        if re.search(pattern, L[i]):
            return i
    raise SystemExit(f"Not found: {pattern}")


def block_end(start):
    """Line of the closing brace for a top-level block starting at `start` (ends with '}' or '};' at column 0)."""
    for i in range(start, len(L)):
        if re.match(r"^\};?\s*$", L[i]):
            return i
    raise SystemExit(f"No end for block at {start}")


cuts = []   # (first, last, replacement)

# 1. storage -> server sync
a = find(r"^/\* Storage: IndexedDB")
b = find(r"^function saveNow\(\)", a)
b = block_end(b)
cuts.append((a, b, """/* Storage: the MySQL database behind the Python API. Changes are sent as they happen (see sync.js). */
function hydrate(d) {
  if (d && Array.isArray(d.employees)) {
    const out = Object.assign(blank(), d);
    out.settings = Object.assign(blank().settings, d.settings || {});
    out.stat = Object.assign(defaultStatutory(), d.stat || {});
    return out;
  }
  return blank();
}
let S = blank();
const sync = createSync(() => S, {
  onRejected: (msg) => hooks.onSyncRejected(msg),
  onUnauthorised: () => hooks.onSessionEnded(),
  onOffline: () => toast('The server cannot be reached. Changes are kept and saved when it is back.'),
});
function save() { sync.schedule(); }
function saveNow() { sync.flush(); }"""))

# 2. menu group toggle handled by React
a = find(r"^ACT\.menuGroup = ")
cuts.append((a, a, ""))

# 3. route + renderShell -> resolvePage for React
a = find(r"^function route\(\) \{")
b = block_end(find(r"^function renderShell\(", a))
cuts.append((a, b, """/* Pages drawn by React components rather than by the HTML views below */
const REACT_PAGES = new Set(['home', 'inbox', 'settings']);
const REACT_TITLES = { home: 'Home', inbox: 'Approvals', settings: 'Settings and data' };
/* Works out the page for a location hash: sets R, runs the page's view, and names the menu item it belongs to */
function resolvePage(hash) {
  const raw = String(hash || '').replace(/^#\\/?/, '');
  const [path, query] = raw.split('?');
  const [page, arg] = path.split('/');
  R.page = page || 'home'; R.arg = arg || ''; R.q = new URLSearchParams(query || '');
  if (!(VIEWS[R.page] || REACT_PAGES.has(R.page)) || !pageAllowed(R.page)) { R.page = 'home'; R.arg = ''; R.q = new URLSearchParams(); }
  let view = null;
  if (!REACT_PAGES.has(R.page)) {
    try { view = VIEWS[R.page](); } catch (e) { console.error(e); view = { title: 'Something went wrong', html: `<div class="note bad">This page could not be shown: ${esc(e.message)}</div>` }; }
  }
  const PARENT = { exit: 'exits', req: 'reqs', app: 'reqs', payroll: 'payroll' };
  const cur = allItems().find(itemOn) || allItems().find((it) => it.page === R.page) || allItems().find((it) => it.page === PARENT[R.page]);
  const title = cur && cur.tab && itemOn(cur) ? cur.label : (view && view.title) || REACT_TITLES[R.page] || (cur && cur.label) || '';
  return { page: R.page, arg: R.arg, view, title, group: cur && cur.group };
}
/* Every screen calls route() after a change; React redraws */
function route() { if (me) hooks.refresh(); }"""))

# 4. events: drop the ones React handles
a = find(r"^window\.addEventListener\('hashchange'")
cuts.append((a, a, ""))
a = find(r"^ACT\.burger = ")
b = find(r"^ACT\.logout = ", a)
cuts.append((a, b, "ACT.logout = () => hooks.logout();"))

# 5. sign-in moves to React and the server (keep loadGsi for the Workspace directory sync)
a = find(r"^/\* -+ sign-in \*/")
b = find(r"^/\* Google Identity Services", a) - 1
cuts.append((a, b, "/* ---------------------------------------------------------------- Google (sign-in itself is in React and verified by the server) */"))
a = find(r"^/\* Google Identity Services")
cuts.append((a, a + 1, ""))
a = find(r"^function decodeJwt\(")
b = block_end(find(r"^function initGoogleSignIn\(", a))
cuts.append((a, b, ""))

# 6. first-time setup screen -> data builder used by the React setup page
a = find(r"^function renderSetup\(\)")
b = block_end(a)
cuts.append((a, b, """/* First-time setup: the group, its first company with default policies, and the group administrator.
   The server stores it and keeps the password (bcrypt) apart from the employee record. */
function buildSetupState(f) {
  S = blank();
  S.group.name = f.group.trim();
  const co = newCompany({ name: f.coName.trim(), code: f.coCode.trim().toUpperCase(), state: f.state, domain: f.email.split('@')[1] });
  const [first, ...rest] = f.name.trim().split(/\\s+/);
  const emp = { id: uid(), companyId: co.id, empNo: nextNo('emp', co.code + '-'), firstName: first, lastName: rest.join(' '), email: f.email.trim().toLowerCase(), role: 'super', status: 'active',
    doj: todayISO(), gender: '', shiftId: S.shifts.find((x) => x.companyId === co.id).id, salaryHist: [], history: [{ date: todayISO(), type: 'Hire', note: 'Group administrator' }], source: 'setup', attGroup: 'regular' };
  S.employees.push(emp);
  return { state: JSON.parse(JSON.stringify(S)), adminId: emp.id };
}"""))
a = find(r"^ACT\.loadDemo = ")
cuts.append((a, a, "function buildDemoState() { loadDemo(); return JSON.parse(JSON.stringify(S)); }"))

# 7. Approvals and Home are React components
a = find(r"^VIEWS\.inbox = ")
cuts.append((a, block_end(a), ""))
a = find(r"^/\* -+ home \*/")
b = block_end(find(r"^VIEWS\.home = ", a))
cuts.append((a, b, ""))

# 8. Settings is a React component; boot is the React app
a = find(r"^/\* -+ settings and data \*/")
b = block_end(find(r"^async function boot\(\)", a))
cuts.append((a, b, """/* ---------------------------------------------------------------- server state and session (used by the React app) */
function loadServerState(state, meId) {
  S = hydrate(state);
  me = empById(meId) || null;
  if (!me) return false;
  const saved = sessionStorage.getItem('pd.co');
  CO = companiesForMe().some((c) => c.id === saved) ? saved : me.companyId;
  sync.reset();
  if (S.companies.length) {
    ensureSchema();
    if (isSuper()) save(); else sync.reset();   // only the group administrator saves upgrades for every company
  }
  lastActive = Date.now();
  return true;
}
function clearSession() { me = null; closeDlg(); }
function switchCompany(id) { CO = id; sessionStorage.setItem('pd.co', id); }
const getS = () => S, getMe = () => me, getCO = () => CO;"""))

a = find(r"^boot\(\);")
cuts.append((a, a, ""))

# apply from the bottom up
cuts.sort(key=lambda c: c[0], reverse=True)
for i in range(len(cuts) - 1):
    assert cuts[i + 1][1] < cuts[i][0], f"overlap {cuts[i + 1]} {cuts[i]}"
for a, b, rep in cuts:
    L[a:b + 1] = [rep] if rep else []

body = "\n".join(L[2:])                        # drop the placeholders
body = body.replace('"use strict";\n', "", 1)
body = body.replace("if (!window.XLSX) {", "if (!XLSX) {")
body = body.replace("Data is kept in this browser (localStorage) until a shared server is added.",
                    "Data is kept in MySQL behind the Python API; this module runs in the React app.")

header = """/* eslint-disable */
/* =====================================================================
   PeopleDesk HR engine. Generated by scripts/build-engine.py from the
   original single-file app: rules and feature screens, now saving to the
   server. Edit here, or re-run the script if the original changes.
   ===================================================================== */
import * as XLSX from 'xlsx';
import { createSync } from './sync.js';

/* What the React app plugs in */
const hooks = { refresh: () => {}, logout: () => {}, onSyncRejected: () => {}, onSessionEnded: () => {} };
"""

footer = """
/* ---------------------------------------------------------------- used by the React components */
export {
  hooks, sync, ACT, VIEWS, MENU, BOTTOM, ROLES, STATES, R,
  getS, getMe, getCO, loadServerState, clearSession, switchCompany, resolvePage, buildSetupState, buildDemoState,
  itemShown, itemOn, itemHref, companiesForMe, company, isHR, isSuper, isManager, pendingForMe,
  empById, nameOf, fullName, initials, coEmployees, leaveTypesFor, leaveBalance, ltById,
  shiftFor, punchOf, leaveOn, holidayOn, todayISO, addDays, D, ymAdd, monthName, yearsBetween,
  num, inr0, hm, dt, dShort, dmy, toast, confirmBox, closeDlg, downloadText, audit, save, saveNow, loadGsi,
};
"""
out = pathlib.Path(__file__).resolve().parents[1] / "src" / "engine" / "engine.js"
out.write_text(header + body + footer, encoding="utf-8")
print(f"wrote {out} ({len(body) // 1024} KB)")
