import { useEffect, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* Administration › Reports.
   A saved report (reportDefs) picks a base collection, filters and columns; backend/app/reports.py
   runs it over that collection's records, scoped to the companies the signed-in person is HR for.
   A schedule (reportSchedules) e-mails a saved report's Excel file to a list of recipients on a
   cadence (daily/weekly/monthly at a chosen hour); backend/app/reports.py's background scheduler
   checks for due schedules every REPORT_TICK_MIN minutes (default 60), mirroring reimb.py's own
   automatic-run pattern. */

const OPS = [['equals', 'is'], ['notEquals', 'is not'], ['contains', 'contains'], ['before', 'is before'], ['after', 'is after'], ['in', 'is one of (comma-separated)']];
const CADENCES = [['daily', 'Every day'], ['weekly', 'Every week'], ['monthly', 'Every month']];
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

async function exportExcel(body) {
  const r = await fetch('/api/reports/export', { method: 'POST', credentials: 'same-origin', headers: { 'x-peopledesk': '1', 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : `The server returned ${r.status}`); }
  const m = (r.headers.get('content-disposition') || '').match(/filename="([^"]+)"/);
  E.downloadBlob(m ? m[1] : 'report.xlsx', await r.blob());
}

export default function Reports() {
  const [fields, setFields] = useState(null);
  const [err, setErr] = useState('');
  const [edit, setEdit] = useState(null);     // a reportDefs id, '' for new, or null for the list
  useEffect(() => { api.get('/api/reports/fields').then((d) => setFields(d.collections)).catch((x) => setErr(x.message)); }, []);

  const S = E.getS();
  const cos = E.companiesForMe();
  const mine = (S.reportDefs || []).filter((r) => !r.companyId || cos.some((c) => c.id === r.companyId)).sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const collLabel = (k) => (fields || []).find((c) => c.collection === k)?.label || k;

  if (err) return <div className="note bad">{err}</div>;
  if (!fields) return <div className="empty">Loading…</div>;
  if (edit !== null) return <Editor fields={fields} reportId={edit} onDone={() => setEdit(null)} />;

  return (
    <div className="card">
      <div className="hd"><h2>Reports</h2><button className="btn pri" onClick={() => setEdit('')}>New report</button></div>
      <p className="sub">Build a report over your HR data, run it or download it as Excel, and optionally e-mail it to people on a schedule.</p>
      {mine.length ? (
        <div className="scroll"><table className="t">
          <thead><tr><th>Name</th><th>Over</th><th>Schedules</th><th /></tr></thead>
          <tbody>{mine.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td><td>{collLabel(r.baseCollection)}</td>
              <td>{(S.reportSchedules || []).filter((s) => s.reportDefId === r.id).length || <span className="fine">None</span>}</td>
              <td><button className="btn sm" onClick={() => setEdit(r.id)}>Open</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <div className="empty">No reports saved yet.</div>}
    </div>
  );
}

function Editor({ fields, reportId, onDone }) {
  const S = E.getS();
  const existing = reportId ? (S.reportDefs || []).find((r) => r.id === reportId) : null;
  const [name, setName] = useState(existing?.name || '');
  const [baseCollection, setBaseCollection] = useState(existing?.baseCollection || fields[0]?.collection || '');
  const [filters, setFilters] = useState(existing?.filters || []);
  const [columns, setColumns] = useState(existing?.columns?.length ? existing.columns : (fields[0]?.fields || []).map(([f]) => f));
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const coll = fields.find((c) => c.collection === baseCollection) || { fields: [] };
  const allFields = coll.fields.map(([f]) => f);
  useEffect(() => { if (!existing) setColumns(allFields); }, [baseCollection]);   // eslint-disable-line react-hooks/exhaustive-deps

  const body = () => ({ reportDefId: existing?.id, baseCollection, filters, columns });

  const run = async () => {
    setBusy(true); setMsg('');
    try { const d = await api.post('/api/reports/run', body()); setRows(d.rows); setTotal(d.total); }
    catch (x) { setMsg(x.message); } finally { setBusy(false); }
  };

  const download = async () => {
    setBusy(true); setMsg('');
    try { await exportExcel(body()); } catch (x) { setMsg(x.message); } finally { setBusy(false); }
  };

  const save = () => {
    if (!name.trim()) { setMsg('Give the report a name.'); return; }
    const rec = { ...(existing || {}), id: existing?.id || E.uid(), name: name.trim(), baseCollection, filters, columns,
      companyId: existing?.companyId ?? (E.isSuper() ? '' : E.getCO()) };
    const i = (S.reportDefs || []).findIndex((x) => x.id === rec.id);
    if (i >= 0) S.reportDefs[i] = rec; else S.reportDefs.push(rec);
    E.audit(i >= 0 ? 'Report changed' : 'Report saved', rec.name, 'admin'); E.saveNow(); E.toast('Report saved'); onDone();
  };

  const remove = () => {
    S.reportSchedules = (S.reportSchedules || []).filter((s) => s.reportDefId !== existing.id);
    S.reportDefs = S.reportDefs.filter((r) => r.id !== existing.id);
    E.audit('Report deleted', existing.name, 'admin'); E.saveNow(); E.toast('Report deleted'); onDone();
  };

  return (
    <>
      <div className="card">
        <div className="hd"><h2>{existing ? `Edit ${existing.name}` : 'New report'}</h2><button className="btn ghost" onClick={onDone}>Back to reports</button></div>
        <div className="form">
          <label className="field">Name<input className="inp" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Monthly attrition" /></label>
          <label className="field">Over<select className="inp" value={baseCollection} onChange={(e) => setBaseCollection(e.target.value)}>
            {fields.map((c) => <option key={c.collection} value={c.collection}>{c.label}</option>)}
          </select></label>
        </div>

        <h3>Filters</h3>
        {filters.map((f, i) => (
          <div className="tools" key={i}>
            <select className="inp" value={f.field} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, field: e.target.value } : x))}>
              {allFields.map((k) => <option key={k} value={k}>{(coll.fields.find(([x]) => x === k) || [k, k])[1]}</option>)}
            </select>
            <select className="inp" value={f.op} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, op: e.target.value } : x))}>
              {OPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <input className="inp" value={f.value || ''} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
            <button className="btn sm ghost" onClick={() => setFilters(filters.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button className="btn sm" onClick={() => setFilters([...filters, { field: allFields[0] || '', op: 'equals', value: '' }])}>Add a filter</button>

        <h3>Columns</h3>
        <div className="picklist">{allFields.map((k) => (
          <label key={k}><input type="checkbox" checked={columns.includes(k)} onChange={(e) => setColumns(e.target.checked ? [...columns, k] : columns.filter((x) => x !== k))} />
            {(coll.fields.find(([x]) => x === k) || [k, k])[1]}</label>
        ))}</div>

        {msg && <p className="note">{msg}</p>}
        <div className="btns">
          {existing && <button className="btn danger" disabled={busy} onClick={remove}>Delete</button>}
          <button className="btn" disabled={busy} onClick={run}>Run</button>
          <button className="btn" disabled={busy} onClick={download}>Download Excel</button>
          <button className="btn pri" disabled={busy} onClick={save}>Save</button>
        </div>

        {rows && (
          <div className="scroll" style={{ maxHeight: 360 }}>
            <p className="fine">{total} row{total === 1 ? '' : 's'}{rows.length < total ? ` (showing the first ${rows.length})` : ''}</p>
            <table className="t">
              <thead><tr>{columns.map((c) => <th key={c}>{(coll.fields.find(([x]) => x === c) || [c, c])[1]}</th>)}</tr></thead>
              <tbody>{rows.map((r, i) => <tr key={i}>{columns.map((c) => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody>
            </table>
          </div>
        )}
      </div>
      {existing && <Schedules reportDef={existing} />}
    </>
  );
}

function Schedules({ reportDef }) {
  const S = E.getS();
  const mine = (S.reportSchedules || []).filter((s) => s.reportDefId === reportDef.id);
  const [f, setF] = useState({ recipients: '', type: 'daily', hour: 8, dayOfWeek: 0, dayOfMonth: 1 });

  const add = () => {
    const recipients = f.recipients.split(',').map((x) => x.trim()).filter(Boolean);
    if (!recipients.length) return;
    S.reportSchedules = [...(S.reportSchedules || []), {
      id: E.uid(), reportDefId: reportDef.id, companyId: reportDef.companyId, recipients, active: true,
      cadence: { type: f.type, hour: Number(f.hour) || 8, dayOfWeek: Number(f.dayOfWeek) || 0, dayOfMonth: Number(f.dayOfMonth) || 1 },
    }];
    E.audit('Report schedule added', reportDef.name, 'admin'); E.saveNow(); E.toast('Scheduled');
    setF({ recipients: '', type: 'daily', hour: 8, dayOfWeek: 0, dayOfMonth: 1 });
  };
  const toggle = (s) => { S.reportSchedules = S.reportSchedules.map((x) => x.id === s.id ? { ...x, active: !x.active } : x); E.saveNow(); };
  const remove = (s) => { S.reportSchedules = S.reportSchedules.filter((x) => x.id !== s.id); E.audit('Report schedule removed', reportDef.name, 'admin'); E.saveNow(); };

  return (
    <div className="card">
      <h2>E-mail this report on a schedule</h2>
      {mine.length ? (
        <table className="t"><thead><tr><th>Recipients</th><th>When</th><th>Last sent</th><th>Active</th><th /></tr></thead>
          <tbody>{mine.map((s) => (
            <tr key={s.id}>
              <td>{(s.recipients || []).join(', ')}</td>
              <td>{s.cadence?.type === 'weekly' ? `Every ${WEEKDAYS[s.cadence.dayOfWeek || 0]}, ${s.cadence.hour}:00`
                : s.cadence?.type === 'monthly' ? `Day ${s.cadence.dayOfMonth} of the month, ${s.cadence.hour}:00` : `Daily, ${s.cadence?.hour}:00`}</td>
              <td>{s.lastSentAt ? E.dt(s.lastSentAt) : <span className="fine">Never</span>}{s.lastError && <div className="fine err">{s.lastError}</div>}</td>
              <td><input type="checkbox" checked={s.active !== false} onChange={() => toggle(s)} /></td>
              <td><button className="btn sm ghost" onClick={() => remove(s)}>Remove</button></td>
            </tr>
          ))}</tbody>
        </table>
      ) : <div className="empty">Not scheduled.</div>}
      <div className="form" style={{ marginTop: 12 }}>
        <label className="field wide">Recipients (e-mail addresses, comma-separated)<input className="inp" value={f.recipients} onChange={(e) => setF({ ...f, recipients: e.target.value })} /></label>
        <label className="field">Cadence<select className="inp" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>{CADENCES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        {f.type === 'weekly' && <label className="field">Day<select className="inp" value={f.dayOfWeek} onChange={(e) => setF({ ...f, dayOfWeek: e.target.value })}>{WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>}
        {f.type === 'monthly' && <label className="field">Day of month<input className="inp" type="number" min={1} max={28} value={f.dayOfMonth} onChange={(e) => setF({ ...f, dayOfMonth: e.target.value })} /></label>}
        <label className="field">Hour (24h)<input className="inp" type="number" min={0} max={23} value={f.hour} onChange={(e) => setF({ ...f, hour: e.target.value })} /></label>
      </div>
      <div className="btns"><button className="btn pri" onClick={add}>Add schedule</button></div>
    </div>
  );
}
