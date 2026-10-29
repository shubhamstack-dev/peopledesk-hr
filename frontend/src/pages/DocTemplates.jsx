import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* Administration › Document templates and Document types.
   A template is a Word (.docx) file with {{ placeholders }}. Each placeholder is mapped to a database field,
   a field of the employee record, fixed text, or a question HR answers when making the document.
   The server fills it from MySQL (backend/app/doctemplates.py). HR makes documents from an employee's
   profile: Documents › Create from a template. */

const SOURCES = [
  ['field', 'Database field'],
  ['emp', 'Employee record field'],
  ['text', 'Fixed text'],
  ['ask', 'Ask when creating'],
  ['blank', 'Leave empty'],
];
const ASK_TYPES = [['text', 'Short text'], ['long', 'Paragraph'], ['date', 'Date'], ['money', 'Amount (₹)'], ['number', 'Number']];
/* Employee record keys offered for "Employee record field" (any key stored on the record works) */
const EMP_KEYS = ['firstName', 'lastName', 'empNo', 'email', 'phone', 'personalEmail', 'dob', 'doj', 'probationEnd', 'gender', 'marital',
  'blood', 'address', 'addrCity', 'addrState', 'addrPin', 'addrCountry', 'emergencyName', 'emergencyRelation', 'emergencyPhone',
  'pan', 'uan', 'pfNo', 'esiNo', 'bankName', 'bankAcc', 'ifsc', 'empType', 'taxRegime'];
const SUGGESTED_PREFIX = { 'Offer letter': 'OL', 'Appointment and joining letter': 'APL', 'Confirmation letter': 'CNF', 'Salary revision letter': 'SRL',
  'Bonus letter': 'BNL', 'Promotion letter': 'PRL', 'Transfer letter': 'TRL', 'Appreciation letter': 'APR', 'Experience or relieving letter': 'EXL' };

const humanise = (ph) => ph.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

async function scanFile(file) {
  const fd = new FormData(); fd.append('file', file);
  const r = await fetch('/api/doc-templates/scan', { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'x-peopledesk': '1' } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'The template could not be read.');
  return d;
}

/* Every placeholder gets an explicit mapping: kept if it had one, a database field when the name is one, otherwise asked */
function mergeMapping(placeholders, old, fieldKeys) {
  const out = {};
  for (const ph of placeholders) out[ph] = (old || {})[ph] || (fieldKeys.has(ph) ? { source: 'field', key: ph } : { source: 'ask', label: humanise(ph), type: 'text', required: true });
  return out;
}

export default function DocTemplates() {
  const tab = E.R.q.get('tab') === 'types' ? 'types' : 'templates';
  const [fields, setFields] = useState(null);
  const [fieldErr, setFieldErr] = useState('');
  useEffect(() => { api.get('/api/doc-templates/fields').then((d) => setFields(d.fields)).catch((x) => setFieldErr(x.message)); }, []);

  return (
    <>
      <nav className="tabs">
        <a href="#/doctemplates?tab=templates" className={tab === 'templates' ? 'on' : ''}>Templates</a>
        <a href="#/doctemplates?tab=types" className={tab === 'types' ? 'on' : ''}>Document types</a>
      </nav>
      {fieldErr && <div className="note bad">{fieldErr}</div>}
      {tab === 'templates' ? <Templates fields={fields} /> : <Types />}
    </>
  );
}

/* ================================================================ templates */
function Templates({ fields }) {
  const S = E.getS();
  const [edit, setEdit] = useState(null);
  const cos = E.companiesForMe();
  const coName = (id) => (id ? (E.coById(id) || {}).name || '—' : 'All companies');
  const mine = S.docTemplates.filter((t) => !t.companyId || cos.some((c) => c.id === t.companyId))
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const typeName = (id) => (S.docTypes.find((t) => t.id === id) || {}).name || '—';

  if (edit) return <Editor draft={edit} fields={fields} onDone={() => setEdit(null)} />;

  return (
    <>
      <div className="card">
        <div className="hd">
          <div><h2>Word templates</h2>
            <p className="sub">Letters and forms written in Word with placeholders such as {'{{ employee_name }}'}. When HR creates a document from an employee’s profile, the placeholders are filled from the database and the file is added to the employee’s documents.</p></div>
          <button className="btn pri" onClick={() => setEdit({ id: '', name: '', typeId: '', companyId: E.getCO(), status: 'active', description: '', placeholders: [], mapping: {} })}>Add a template</button>
        </div>
        {mine.length ? (
          <div className="scroll"><table className="t">
            <thead><tr><th>Template</th><th>Document type</th><th>Company</th><th className="r">Placeholders</th><th>Status</th><th /></tr></thead>
            <tbody>{mine.map((t) => {
              const asks = (t.placeholders || []).filter((p) => (t.mapping[p] || {}).source === 'ask').length;
              return (
                <tr key={t.id}>
                  <td><b>{t.name}</b>{t.fileName && <div className="fine"><a href={`/api/files/${t.fileId}`}>{t.fileName}</a></div>}</td>
                  <td>{typeName(t.typeId)}</td>
                  <td>{coName(t.companyId)}</td>
                  <td className="r">{(t.placeholders || []).length}{asks ? <div className="fine">{asks} asked when creating</div> : null}</td>
                  <td>{t.status === 'inactive' ? <span className="badge">Not in use</span> : <span className="badge ok">In use</span>}</td>
                  <td className="r"><button className="btn sm" onClick={() => setEdit(JSON.parse(JSON.stringify(t)))}>Edit</button></td>
                </tr>
              );
            })}</tbody>
          </table></div>
        ) : <div className="empty">No templates yet. Start with one of the letters you already send, and replace the details with placeholders.</div>}
      </div>
      <FieldReference fields={fields} />
    </>
  );
}

function Editor({ draft, fields, onDone }) {
  const S = E.getS();
  const [t, setT] = useState(draft);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [testEmp, setTestEmp] = useState('');
  const cos = E.companiesForMe();
  const fieldKeys = useMemo(() => new Set((fields || []).map((f) => f.key)), [fields]);
  const groups = useMemo(() => [...new Set((fields || []).map((f) => f.group))], [fields]);
  const types = E.docTypesFor(t.companyId || E.getCO()).filter((x) => !t.companyId ? !x.companyId : true);
  const emps = (t.companyId ? E.coEmployees(t.companyId) : cos.flatMap((c) => E.coEmployees(c.id))).slice().sort((a, b) => E.fullName(a).localeCompare(E.fullName(b)));
  const set = (k, v) => setT((x) => ({ ...x, [k]: v }));
  const setMap = (ph, m) => setT((x) => ({ ...x, mapping: { ...x.mapping, [ph]: m } }));

  const upload = async (ev) => {
    const file = ev.target.files[0]; ev.target.value = '';
    if (!file) return;
    setBusy(true); setMsg(`Reading ${file.name}…`);
    try {
      const d = await scanFile(file);
      setT((x) => ({
        ...x, name: x.name || file.name.replace(/\.docx$/i, ''),
        versions: x.fileId ? [...(x.versions || []), { fileId: x.fileId, fileName: x.fileName, at: x.uploadedAt || Date.now() }].slice(-10) : x.versions,
        fileId: d.fileId, fileName: d.name, uploadedAt: Date.now(), placeholders: d.placeholders, mapping: mergeMapping(d.placeholders, x.mapping, fieldKeys),
      }));
      setMsg(d.placeholders.length
        ? `Found ${d.placeholders.length} placeholders. ${d.unknown.length ? `${d.unknown.length} are not database fields; they are asked when the document is created unless you map them below.` : 'All of them are database fields.'}`
        : 'No placeholders found. Type them in Word as {{ employee_name }} and upload again.');
    } catch (x) { setMsg(x.message); } finally { setBusy(false); }
  };

  const problems = () => {
    const p = [];
    if (!t.name.trim()) p.push('a name');
    if (!t.fileId) p.push('the Word file');
    for (const ph of t.placeholders || []) {
      const m = t.mapping[ph] || {};
      if (m.source === 'field' && !fieldKeys.has(m.key)) p.push(`a database field for {{ ${ph} }}`);
      if (m.source === 'emp' && !String(m.key || '').trim()) p.push(`an employee field for {{ ${ph} }}`);
    }
    return p;
  };

  const save = (quiet = false) => {
    const p = problems();
    if (p.length) { setMsg(`Add ${p.join(', ')}.`); return null; }
    const rec = { ...t, name: t.name.trim(), id: t.id || E.uid(), updatedAt: Date.now(), updatedBy: E.getMe().id };
    const i = S.docTemplates.findIndex((x) => x.id === rec.id);
    if (i >= 0) S.docTemplates[i] = rec; else S.docTemplates.push(rec);
    E.audit(i >= 0 ? 'Document template changed' : 'Document template added', rec.name, 'admin');
    E.saveNow(); setT(rec);
    if (!quiet) { E.toast('Template saved'); E.hooks.refresh(); onDone(); }
    return rec;
  };

  const preview = async () => {
    if (!testEmp) { setMsg('Choose an employee to try the template with.'); return; }
    const rec = save(true); if (!rec) return;
    setBusy(true); setMsg('Preparing the draft…');
    // questions are filled with their labels so you can see where each answer lands
    const values = Object.fromEntries((rec.placeholders || []).filter((p) => rec.mapping[p].source === 'ask').map((p) => [p, `[${rec.mapping[p].label || p}]`]));
    try {
      const empty = await E.docPreview(rec.id, testEmp, E.todayISO(), values);
      setMsg(empty.length ? `Draft downloaded. Empty for this employee: ${empty.join(', ')}.` : 'Draft downloaded with every placeholder filled.');
    } catch (x) { setMsg(x.message); } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!(await E.confirmBox('Delete this template?', 'Documents already created from it stay on the employees’ profiles.', 'Delete'))) return;
    S.docTemplates = S.docTemplates.filter((x) => x.id !== t.id);
    E.audit('Document template deleted', t.name, 'admin'); E.saveNow(); E.hooks.refresh(); onDone();
  };

  return (
    <>
      <div className="card">
        <div className="hd"><h2>{t.id ? `Edit ${draft.name}` : 'New template'}</h2><button className="btn ghost" onClick={onDone}>Back to templates</button></div>
        <div className="form">
          <label className="field">Name<input className="inp" value={t.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Salary revision letter 2026" /></label>
          <label className="field">Document type
            <select className="inp" value={t.typeId || ''} onChange={(e) => set('typeId', e.target.value)}>
              <option value="">None (no letter number)</option>
              {types.map((x) => <option key={x.id} value={x.id}>{x.name}{x.prefix ? ` (${x.prefix})` : ''}</option>)}
            </select>
            <small>Gives the document its category and letter number. Add types under Document types.</small></label>
          <label className="field">Company
            <select className="inp" value={t.companyId || ''} onChange={(e) => set('companyId', e.target.value)}>
              {E.isSuper() && <option value="">All companies</option>}
              {cos.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="field">Status
            <select className="inp" value={t.status || 'active'} onChange={(e) => set('status', e.target.value)}>
              <option value="active">In use</option><option value="inactive">Not in use (hidden when creating documents)</option>
            </select></label>
          <label className="field wide">Note for HR<input className="inp" value={t.description || ''} onChange={(e) => set('description', e.target.value)} placeholder="Shown when someone creates a document from this template" /></label>
          <label className="field wide">Word file (.docx)
            <input className="inp" type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={busy} onChange={upload} />
            <small>{t.fileId ? <>Current file: <a href={`/api/files/${t.fileId}`}>{t.fileName}</a>. Uploading another replaces it; mappings for placeholders that stay are kept.</> : 'Write the letter in Word, put {{ placeholders }} where the details go, save it as .docx and upload it here.'}</small>
          </label>
        </div>
        {msg && <p className="fine" role="status">{msg}</p>}
      </div>

      {(t.placeholders || []).length > 0 && (
        <div className="card">
          <h2>Where each placeholder comes from</h2>
          <p className="sub">Placeholders named after a database field are filled automatically. Map the others to a field, fixed text, or a question HR answers when creating the document.</p>
          <div className="scroll"><table className="t">
            <thead><tr><th>Placeholder</th><th>Comes from</th><th>Details</th></tr></thead>
            <tbody>{t.placeholders.map((ph) => {
              const m = t.mapping[ph] || { source: 'blank' };
              return (
                <tr key={ph}>
                  <td><code>{`{{ ${ph} }}`}</code></td>
                  <td>
                    <select className="inp" value={m.source} onChange={(e) => {
                      const s = e.target.value;
                      setMap(ph, s === 'field' ? { source: s, key: fieldKeys.has(ph) ? ph : '' } : s === 'ask' ? { source: s, label: humanise(ph), type: 'text', required: true }
                        : s === 'emp' ? { source: s, key: '' } : s === 'text' ? { source: s, value: '' } : { source: s });
                    }}>{SOURCES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
                  </td>
                  <td><MappingDetail m={m} fields={fields} groups={groups} onChange={(n) => setMap(ph, n)} /></td>
                </tr>
              );
            })}</tbody>
          </table></div>
        </div>
      )}

      <div className="card">
        <h2>Save and try it</h2>
        <div className="form">
          <label className="field">Try with this employee
            <select className="inp" value={testEmp} onChange={(e) => setTestEmp(e.target.value)}>
              <option value="">Choose</option>
              {emps.map((e) => <option key={e.id} value={e.id}>{E.fullName(e)} ({e.empNo})</option>)}
            </select>
            <small>Downloads a draft. Nothing is numbered or added to the profile.</small></label>
        </div>
        <div className="btns" style={{ justifyContent: 'flex-start' }}>
          <button className="btn pri" disabled={busy} onClick={() => save()}>Save template</button>
          <button className="btn" disabled={busy || !t.fileId} onClick={preview}>Save and download a draft</button>
          {t.id && <button className="btn danger" disabled={busy} onClick={remove}>Delete</button>}
        </div>
        {(t.versions || []).length > 0 && (
          <p className="fine">Earlier files: {t.versions.slice().reverse().map((v, i) => <span key={v.fileId}>{i ? ', ' : ''}<a href={`/api/files/${v.fileId}`}>{v.fileName}</a> ({E.dt(v.at)})</span>)}</p>
        )}
      </div>
    </>
  );
}

function MappingDetail({ m, fields, groups, onChange }) {
  if (m.source === 'field') {
    return (
      <select className="inp" value={m.key || ''} onChange={(e) => onChange({ ...m, key: e.target.value })}>
        <option value="">Choose a field</option>
        {groups.map((g) => (
          <optgroup key={g} label={g}>{(fields || []).filter((f) => f.group === g).map((f) => <option key={f.key} value={f.key}>{f.label} ({f.key})</option>)}</optgroup>
        ))}
      </select>
    );
  }
  if (m.source === 'emp') {
    return (<>
      <input className="inp" list="pdEmpKeys" value={m.key || ''} onChange={(e) => onChange({ ...m, key: e.target.value.trim() })} placeholder="e.g. addrCity" />
      <datalist id="pdEmpKeys">{EMP_KEYS.map((k) => <option key={k} value={k} />)}</datalist>
    </>);
  }
  if (m.source === 'text') return <input className="inp" value={m.value || ''} onChange={(e) => onChange({ ...m, value: e.target.value })} placeholder="The same text in every document" />;
  if (m.source === 'ask') {
    return (
      <div className="tools">
        <input className="inp" style={{ flex: '2 1 160px' }} value={m.label || ''} onChange={(e) => onChange({ ...m, label: e.target.value })} placeholder="Question shown to HR" aria-label="Question" />
        <select className="inp" style={{ flex: '1 1 110px' }} value={m.type || 'text'} onChange={(e) => onChange({ ...m, type: e.target.value })} aria-label="Answer type">
          {ASK_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="fine" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={!!m.required} onChange={(e) => onChange({ ...m, required: e.target.checked })} /> Required</label>
      </div>
    );
  }
  return <span className="fine">Left empty in the document.</span>;
}

function FieldReference({ fields }) {
  const [copied, setCopied] = useState('');
  if (!fields) return null;
  const groups = [...new Set(fields.map((f) => f.group))];
  const copy = (txt) => { navigator.clipboard?.writeText(txt).then(() => { setCopied(txt); setTimeout(() => setCopied(''), 1500); }); };
  return (
    <div className="card">
      <h2>Placeholders you can use</h2>
      <p className="sub">Type these in Word exactly as shown, with double curly brackets. Names use letters, digits and underscores, no spaces. Select one to copy it. Headers and footers work too.</p>
      <div className="note">
        <b>Salary table:</b> to repeat a table row for each salary component, put <code>{'{%tr for c in salary_components %}'}</code> alone in a row, then a row with <code>{'{{ c.name }}'}</code>, <code>{'{{ c.monthly }}'}</code> and <code>{'{{ c.annual }}'}</code>, then <code>{'{%tr endfor %}'}</code> alone in the next row.
        {' '}<b>Optional text:</b> <code>{'{% if variable_pay %}'}</code>…<code>{'{% endif %}'}</code> shows the text only when there is a value.
      </div>
      <div className="grid g2">
        {groups.map((g) => (
          <div key={g}>
            <h3 style={{ margin: '6px 0' }}>{g}</h3>
            <table className="t"><tbody>{fields.filter((f) => f.group === g).map((f) => {
              const tag = f.list ? `{%tr for c in ${f.key} %}` : `{{ ${f.key} }}`;
              return (
                <tr key={f.key} className="click" onClick={() => copy(tag)} title="Copy">
                  <td><code>{tag}</code></td><td className="fine">{copied === tag ? 'Copied' : f.label}</td>
                </tr>
              );
            })}</tbody></table>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ================================================================ document types */
function Types() {
  const S = E.getS();
  const blankType = { id: '', name: '', prefix: '', companyId: '', description: '' };
  const [f, setF] = useState(blankType);
  const [err, setErr] = useState('');
  const cos = E.companiesForMe();
  const list = S.docTypes.filter((t) => !t.companyId || cos.some((c) => c.id === t.companyId)).sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const used = (id) => S.docTemplates.filter((t) => t.typeId === id).length;
  const coName = (id) => (id ? (E.coById(id) || {}).name || '—' : 'All companies');

  const save = (ev) => {
    ev.preventDefault(); setErr('');
    const name = f.name.trim(), prefix = f.prefix.trim().toUpperCase().replace(/[^A-Z0-9-]/g, '');
    if (!name) return setErr('Give the type a name.');
    if (!E.isSuper() && !f.companyId) return setErr('Choose the company.');
    if (S.docTypes.some((t) => t.id !== f.id && t.name.toLowerCase() === name.toLowerCase() && (t.companyId || '') === (f.companyId || ''))) return setErr('There is already a type with this name.');
    const rec = { ...f, name, prefix, id: f.id || E.uid() };
    const i = S.docTypes.findIndex((t) => t.id === rec.id);
    if (i >= 0) S.docTypes[i] = rec; else S.docTypes.push(rec);
    E.audit(i >= 0 ? 'Document type changed' : 'Document type added', name, 'admin'); E.saveNow(); setF(blankType); E.hooks.refresh();
  };
  const remove = async (t) => {
    if (used(t.id)) { E.toast('Templates use this type. Change them first.'); return; }
    if (!(await E.confirmBox('Delete this document type?', t.name, 'Delete'))) return;
    S.docTypes = S.docTypes.filter((x) => x !== t); E.audit('Document type deleted', t.name, 'admin'); E.saveNow(); E.hooks.refresh();
  };
  const seed = () => {
    const companyId = E.isSuper() ? '' : E.getCO();
    let n = 0;
    for (const name of E.DOC_CATEGORIES.filter((c) => !['Statutory proof', 'Other', 'Policy acknowledgement'].includes(c))) {
      if (S.docTypes.some((t) => t.name === name && (t.companyId || '') === companyId)) continue;
      S.docTypes.push({ id: E.uid(), name, prefix: SUGGESTED_PREFIX[name] || '', companyId, description: '' }); n++;
    }
    if (n) { E.audit('Document types added', `${n} standard types`, 'admin'); E.saveNow(); E.hooks.refresh(); }
    E.toast(n ? `${n} types added` : 'They are all here already');
  };

  return (
    <>
      <div className="card">
        <div className="hd">
          <div><h2>Document types</h2>
            <p className="sub">The kinds of document HR issues. Each template belongs to a type, which names the document on the employee’s profile and numbers it: with prefix SRL, letters are numbered SRL/company code/2026-27/0001, counting from 1 each financial year.</p></div>
          {!list.length && <button className="btn" onClick={seed}>Add the usual types</button>}
        </div>
        {list.length ? (
          <table className="t">
            <thead><tr><th>Type</th><th>Number prefix</th><th>Company</th><th className="r">Templates</th><th /></tr></thead>
            <tbody>{list.map((t) => (
              <tr key={t.id}>
                <td><b>{t.name}</b>{t.description && <div className="fine">{t.description}</div>}</td>
                <td>{t.prefix || <span className="fine">Not numbered</span>}</td>
                <td>{coName(t.companyId)}</td>
                <td className="r">{used(t.id)}</td>
                <td className="r" style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn sm" onClick={() => setF({ ...blankType, ...t, companyId: t.companyId || '' })}>Edit</button>{' '}
                  <button className="btn sm ghost" onClick={() => remove(t)}>Delete</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        ) : <div className="empty">No document types yet.</div>}
      </div>

      <form className="card" onSubmit={save}>
        <h2>{f.id ? `Edit ${f.name}` : 'Add a document type'}</h2>
        <div className="form">
          <label className="field">Name<input className="inp" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Salary revision letter" /></label>
          <label className="field">Number prefix<input className="inp" value={f.prefix} maxLength={12} onChange={(e) => setF({ ...f, prefix: e.target.value })} placeholder="e.g. SRL" />
            <small>Letters, digits and hyphens. Leave empty for documents without a number.</small></label>
          <label className="field">Company
            <select className="inp" value={f.companyId} onChange={(e) => setF({ ...f, companyId: e.target.value })}>
              {E.isSuper() ? <option value="">All companies</option> : <option value="">Choose</option>}
              {cos.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></label>
          <label className="field">Description<input className="inp" value={f.description || ''} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        </div>
        <p className="err">{err}</p>
        <div className="btns" style={{ justifyContent: 'flex-start' }}>
          <button className="btn pri">{f.id ? 'Save changes' : 'Add type'}</button>
          {f.id && <button type="button" className="btn ghost" onClick={() => { setF(blankType); setErr(''); }}>Cancel</button>}
        </div>
      </form>
    </>
  );
}
