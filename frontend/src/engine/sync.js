/* Saves changes to the server.
   The screens change the in-memory state and call save(). Here the state is compared with
   what the server last confirmed, record by record, and only the differences are sent:
   new and changed records, deleted ids, roster days, settings and new activity-log entries.
   The server applies a batch completely or not at all. */
import { api, ApiError } from '../api.js';

export const COLLECTIONS = ['companies', 'employees', 'depts', 'desigs', 'grades', 'locations', 'holidays',
  'leaveTypes', 'leaveReqs', 'leaveAdj', 'shifts', 'punches', 'regs', 'cycles', 'goals', 'reviews', 'feedback', 'posts',
  'payComps', 'payInputs', 'payRuns', 'declarations', 'exits', 'reqs', 'cands', 'apps', 'interviews', 'otRecs', 'shiftPatterns'];
const SINGLETONS = ['group', 'settings', 'stat', 'seq'];
const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

function snapshot(S) {
  const snap = { colls: {}, single: {}, roster: new Map(), audit: new Set() };
  for (const c of COLLECTIONS) {
    const m = new Map();
    for (const r of S[c] || []) { if (!r.id) r.id = newId(); m.set(r.id, JSON.stringify(r)); }
    snap.colls[c] = m;
  }
  for (const k of SINGLETONS) snap.single[k] = JSON.stringify(S[k] ?? null);
  for (const [emp, days] of Object.entries(S.roster || {})) for (const [d, v] of Object.entries(days || {})) if (v) snap.roster.set(`${emp}|${d}`, String(v));
  for (const a of S.audit || []) { if (!a.id) a.id = newId(); snap.audit.add(a.id); }
  return snap;
}

function diff(base, snap, S) {
  const body = { upsert: {}, delete: {}, singletons: {}, rosterSet: [], rosterDel: [], audit: [] };
  let n = 0;
  for (const c of COLLECTIONS) {
    const was = base.colls[c], now = snap.colls[c];
    const up = []; const del = [];
    now.forEach((json, id) => { if (was.get(id) !== json) up.push(JSON.parse(json)); });
    was.forEach((_j, id) => { if (!now.has(id)) del.push(id); });
    if (up.length) { body.upsert[c] = up; n += up.length; }
    if (del.length) { body.delete[c] = del; n += del.length; }
  }
  for (const k of SINGLETONS) if (base.single[k] !== snap.single[k]) { body.singletons[k] = JSON.parse(snap.single[k]); n++; }
  snap.roster.forEach((v, key) => { if (base.roster.get(key) !== v) { const [empId, date] = key.split('|'); body.rosterSet.push({ empId, date, value: v }); n++; } });
  base.roster.forEach((_v, key) => { if (!snap.roster.has(key)) { const [empId, date] = key.split('|'); body.rosterDel.push({ empId, date }); n++; } });
  for (const a of S.audit || []) if (!base.audit.has(a.id)) { body.audit.push(a); n++; }
  return n ? body : null;
}

export function createSync(getState, { onRejected, onUnauthorised, onOffline }) {
  let base = null; let timer = null; let inFlight = null; let again = false; let retry = null;
  const state = { rev: 0 };

  async function flush() {
    clearTimeout(timer); timer = null;
    if (inFlight) { again = true; return inFlight; }
    const S = getState();
    if (!base || !S) return;
    const snap = snapshot(S);
    const body = diff(base, snap, S);
    if (!body) return;
    inFlight = (async () => {
      try {
        const res = await api.post('/api/sync', body);
        base = snap;
        // If only our own save moved the revision on, nothing new from others needs loading
        if (res.rev === state.rev + 1) state.rev = res.rev;
        clearTimeout(retry); retry = null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) onUnauthorised();
        else if (e instanceof ApiError && (e.status === 403 || e.status === 400 || e.status === 409)) onRejected(e.message);
        else { onOffline(); clearTimeout(retry); retry = setTimeout(flush, 8000); }
      } finally {
        inFlight = null;
        if (again) { again = false; flush(); }
      }
    })();
    return inFlight;
  }

  return {
    state,
    /* Forget pending differences: what is in memory now matches the server */
    reset() { base = snapshot(getState()); clearTimeout(timer); timer = null; },
    stop() { base = null; clearTimeout(timer); clearTimeout(retry); timer = null; },
    schedule() { clearTimeout(timer); timer = setTimeout(flush, 150); },
    flush,
    busy: () => !!(inFlight || timer || retry),
    pending: () => { const S = getState(); return !!(base && S && diff(base, snapshot(S), S)); },
  };
}
