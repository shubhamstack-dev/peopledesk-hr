import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';

/* The contractor portal (PeopleDesk 2.9). A contractor's portal user signs in here, not to the main app. They see
   only their own contractor and its workers: they add workers, correct them until the worker signs in, and send
   each worker an access link to set a password. Workers then fill in their own details. The server decides all of
   this (backend/app/portal.py); this page only shows it. */

const PARTS = [['personal', 'Personal'], ['family', 'Family'], ['background', 'Education'], ['statutory', 'Aadhaar, PAN, UAN'], ['bank', 'Bank']];
const GENDERS = [['M', 'Male'], ['F', 'Female'], ['O', 'Other']];
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const dmy = (iso) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : '—');
const phone10 = (v) => { const d = String(v || '').replace(/\D/g, ''); return d.length >= 10 ? d.slice(-10) : ''; };
const nameOf = (w) => `${w.firstName || ''} ${w.lastName || ''}`.trim();
const BLANK = { firstName: '', lastName: '', gender: '', dob: '', phone: '', email: '', doj: '', deptId: '', desigId: '', locationId: '', shiftId: '' };

function Modal({ title, onClose, children }) {
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', k);
    return () => document.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="pmodal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pmodal-box"><div className="dlg"><h2>{title}</h2>{children}</div></div>
    </div>
  );
}

function WorkerForm({ st, worker, onDone, onClose }) {
  const [f, setF] = useState(worker ? { ...BLANK, ...Object.fromEntries(Object.keys(BLANK).map((k) => [k, worker[k] || ''])) }
    : { ...BLANK, doj: today(), shiftId: (st.masters.shifts[0] || {}).id || '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const sel = (k, label, list, blank) => (
    <label className="field">{label}
      <select className="inp" value={f[k]} onChange={set(k)}>
        {blank !== undefined && <option value="">{blank}</option>}
        {list.map((x) => <option key={x.id} value={x.id}>{x.name}{x.start ? ` (${x.start}–${x.end})` : ''}</option>)}
      </select>
    </label>
  );
  const submit = async (e) => {
    e.preventDefault();
    if (!f.firstName.trim()) return setErr("Enter the worker's first name.");
    if (!f.doj) return setErr('Enter the date of joining.');
    if (!phone10(f.phone) && !f.email.trim()) return setErr('Enter a mobile number or an e-mail address: the worker signs in with it.');
    if (f.phone && !phone10(f.phone)) return setErr('Enter a 10-digit mobile number.');
    setBusy(true); setErr('');
    try {
      const r = await api.post(worker ? `/api/contractor/workers/${worker.id}` : '/api/contractor/workers', f);
      onDone(worker ? null : { id: r.id, empNo: r.empNo, name: `${f.firstName} ${f.lastName}`.trim(), phone: f.phone, email: f.email });
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <Modal title={worker ? `Correct ${nameOf(worker)}` : 'Add a worker'} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: 'contents' }}>
        <p className="fine" style={{ margin: 0 }}>{worker ? 'You can correct these until the worker signs in. After that, they keep their own details.'
          : `The worker joins ${st.company.name} as a contract worker engaged through ${st.contractor.name}. Next, send them an access link: they fill in the rest themselves.`}</p>
        <div className="form">
          <label className="field">First name<input className="inp" value={f.firstName} onChange={set('firstName')} autoFocus /></label>
          <label className="field">Last name<input className="inp" value={f.lastName} onChange={set('lastName')} /></label>
          <label className="field">Gender<select className="inp" value={f.gender} onChange={set('gender')}><option value="">Not stated</option>{GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="field">Date of birth<input className="inp" type="date" value={f.dob} onChange={set('dob')} max={today()} /><small>At least 18 on joining</small></label>
          <label className="field">Mobile number<input className="inp" inputMode="tel" value={f.phone} onChange={set('phone')} /><small>They sign in with it</small></label>
          <label className="field">E-mail (if they have one)<input className="inp" type="email" value={f.email} onChange={set('email')} /></label>
          <label className="field">Date of joining<input className="inp" type="date" value={f.doj} onChange={set('doj')} /></label>
          {sel('deptId', 'Department', st.masters.depts, 'Choose')}
          {sel('desigId', 'Designation', st.masters.desigs, 'Choose')}
          {sel('locationId', 'Location', st.masters.locations, 'Choose')}
          {sel('shiftId', 'Shift', st.masters.shifts, st.masters.shifts.length ? undefined : 'None')}
        </div>
        <p className="err" role="alert">{err}</p>
        <div className="btns"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn pri" disabled={busy}>{busy ? 'Saving…' : worker ? 'Save' : 'Add worker'}</button></div>
      </form>
    </Modal>
  );
}

function LinkBox({ link, onClose }) {
  const [copied, setCopied] = useState(false);
  const ph = phone10(link.phone);
  const msg = `Hello ${link.name}, you have been added to PeopleDesk. Set your password with this link (it works once, for ${link.days} days): ${link.url}`;
  const copy = async () => {
    try { await navigator.clipboard.writeText(link.url); } catch { const t = document.getElementById('plink'); t.select(); document.execCommand('copy'); }
    setCopied(true);
  };
  return (
    <Modal title={`Access link for ${link.name}`} onClose={onClose}>
      {link.added && <div className="note ok">{link.name} is added, with employee number {link.added}.</div>}
      {link.sent ? <div className="note ok">Sent by e-mail to {link.to}.</div> : <p className="fine" style={{ margin: 0 }}>Send this link to {link.name}: on WhatsApp, by text message or by e-mail. With it they set their password and fill in their own details.</p>}
      <label className="field">Link (works once, for {link.days} days)
        <textarea id="plink" className="inp" readOnly rows={3} value={link.url} style={{ fontSize: 12 }} /></label>
      <p className="fine" style={{ margin: 0 }}>Anyone with the link can set the password, so send it only to {link.name}.</p>
      <div className="btns">
        <button className="btn" onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
        {ph && <a className="btn" target="_blank" rel="noopener noreferrer" href={`https://wa.me/91${ph}?text=${encodeURIComponent(msg)}`}>Send on WhatsApp</a>}
        <button className="btn pri" onClick={onClose}>Done</button>
      </div>
    </Modal>
  );
}

function PasswordCard() {
  const [pw, setPw] = useState({ current: '', next: '', again: '' });
  const [msg, setMsg] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    if (pw.next.length < 10) return setMsg('Use a password of at least 10 characters.');
    if (pw.next !== pw.again) return setMsg('The two new passwords are different.');
    try { await api.post('/api/contractor/password', { current: pw.current, new: pw.next }); setPw({ current: '', next: '', again: '' }); setMsg('Password changed.'); }
    catch (x) { setMsg(x.message); }
  };
  return (
    <form className="card" onSubmit={submit} noValidate>
      <h2>Your password</h2>
      <div className="form">
        <label className="field">Current password<input className="inp" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></label>
        <label className="field">New password<input className="inp" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></label>
        <label className="field">New password again<input className="inp" type="password" autoComplete="new-password" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} /></label>
      </div>
      <p className="fine">{msg}</p>
      <div className="btns" style={{ justifyContent: 'flex-start' }}><button className="btn">Change password</button></div>
    </form>
  );
}

export default function ContractorPortal({ onSignOut, onSessionEnded }) {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState('');
  const [form, setForm] = useState(null);     // { worker } or { worker: null } for a new one
  const [link, setLink] = useState(null);
  const [q, setQ] = useState('');
  const [show, setShow] = useState('active');

  const load = useCallback(async () => {
    try { const r = await api.get('/api/contractor/state'); setSt(r.state); setErr(''); }
    catch (x) { if (x.status === 401 || x.status === 403) onSessionEnded(); else setErr(x.message); }
  }, [onSessionEnded]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const on = () => { if (!document.hidden) load(); };
    window.addEventListener('focus', on);
    return () => window.removeEventListener('focus', on);
  }, [load]);

  const sendLink = async (w, added) => {
    try {
      const r = await api.post(`/api/contractor/workers/${w.id}/access`, { send: true });
      setLink({ ...r, name: w.name || nameOf(w), phone: w.phone, added });
      load();
    } catch (x) { setErr(x.message); }
  };

  if (!st) return <div className="boot">{err || 'Loading…'}</div>;
  const t = today();
  const c = st.contractor;
  const active = st.workers.filter((w) => w.status !== 'exited');
  const soon = c.licenceTo && c.licenceTo >= t && (new Date(c.licenceTo) - new Date(t)) / 86400000 <= 30;
  const full = c.maxWorkers && active.length >= +c.maxWorkers;
  const ql = q.trim().toLowerCase();
  const list = st.workers.filter((w) => (show === 'all' || (show === 'active' ? w.status !== 'exited' : w.status === 'exited'))
    && (!ql || `${nameOf(w)} ${w.empNo} ${w.phone || ''} ${w.email || ''}`.toLowerCase().includes(ql)));
  const nm = (k, id) => ((st.masters[k] || []).find((x) => x.id === id) || {}).name || '';
  const doneN = (w) => PARTS.filter(([k]) => w.details[k]).length;

  return (
    <div className="portal">
      <header className="ptop">
        <div className="brand" style={{ padding: 0 }}>
          <span className="logo"><img src="/aequm-mark.png" alt="Aequm" /></span>
          <div><b>{c.name}</b><small>Contractor portal · {st.company.name}</small></div>
        </div>
        <span className="sp" />
        <div className="who"><div className="txt"><b>{st.user.name}</b><small>{st.user.email || st.user.phone}</small></div>
          <button className="btn sm" onClick={onSignOut}>Sign out</button></div>
      </header>

      <main className="content">
        {err && <div className="note bad">{err}</div>}
        {c.licenceTo && c.licenceTo < t && <div className="note bad">Your labour licence ended on {dmy(c.licenceTo)}. Renew it and give the company the new licence before adding workers.</div>}
        {soon && <div className="note warn">Your labour licence ends on {dmy(c.licenceTo)}. Give the company the renewed licence in time.</div>}

        <div className="grid g4" style={{ marginBottom: 16 }}>
          <div className="kpi"><span>Workers engaged</span><b>{active.length}{c.maxWorkers ? ` of ${c.maxWorkers}` : ''}</b><small>{c.maxWorkers ? 'allowed by your licence' : 'with ' + st.company.name}</small></div>
          <div className="kpi"><span>Signed in</span><b>{active.filter((w) => w.access === 'active').length}</b><small>{active.filter((w) => w.access === 'link').length} sent a link, not yet used</small></div>
          <div className="kpi"><span>Details complete</span><b>{active.filter((w) => doneN(w) === PARTS.length).length}</b><small>of {active.length} workers</small></div>
          <div className="kpi"><span>Licence</span><b style={{ fontSize: 18 }}>{c.licenceNo || '—'}</b><small>{c.licenceTo ? `valid to ${dmy(c.licenceTo)}` : 'no end date recorded'}</small></div>
        </div>

        <div className="card">
          <div className="hd"><div><h2>Your workers</h2><p className="sub">Add each worker you supply to {st.company.name}, then send them an access link. They set a password and fill in their own personal details, family, education, Aadhaar, PAN, UAN and bank account. The company's HR sets their wages and who they report to.</p></div>
            <div className="tools">
              <input className="inp" placeholder="Search name, number, mobile" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 200 }} />
              <select className="inp" value={show} onChange={(e) => setShow(e.target.value)}><option value="active">Working</option><option value="exited">Left</option><option value="all">Everyone</option></select>
              <button className="btn pri" disabled={!!full || (c.licenceTo && c.licenceTo < t)} title={full ? 'Your licence allows no more workers' : ''} onClick={() => setForm({ worker: null })}>Add worker</button>
            </div>
          </div>
          {full ? <div className="note warn">Your licence allows {c.maxWorkers} workers and all are engaged. Ask the company to record a licence for more before adding anyone.</div> : null}
          {list.length ? (
            <div className="scroll"><table className="t"><thead><tr><th>Worker</th><th>Job</th><th>Joined</th><th>Signs in with</th><th>Access</th><th>Details filled in</th><th></th></tr></thead>
              <tbody>{list.map((w) => (
                <tr key={w.id}>
                  <td><b>{nameOf(w)}</b> <span className="fine mono">{w.empNo}</span>{w.status === 'exited' ? <div className="fine">Left {dmy(w.lwd)}</div> : w.status === 'notice' ? <div className="fine">Leaving {dmy(w.lwd)}</div> : null}</td>
                  <td>{nm('desigs', w.desigId) || '—'}<div className="fine">{[nm('depts', w.deptId), nm('locations', w.locationId)].filter(Boolean).join(', ')}</div></td>
                  <td>{dmy(w.doj)}</td>
                  <td>{[w.phone, w.email].filter(Boolean).join(', ') || '—'}</td>
                  <td>{w.access === 'active' ? <span className="badge ok">Signed in</span> : w.access === 'link' ? <span className="badge info">Link sent</span> : <span className="badge warn">No link yet</span>}</td>
                  <td><div className="parts">{PARTS.map(([k, l]) => <span key={k} className={`badge ${w.details[k] ? 'ok' : ''}`} title={w.details[k] ? `${l}: filled in` : `${l}: not yet`}>{l}</span>)}</div></td>
                  <td className="r" style={{ whiteSpace: 'nowrap' }}>
                    {w.editable && <button className="btn sm" onClick={() => setForm({ worker: w })}>Correct</button>}{' '}
                    {w.status !== 'exited' && w.access !== 'active' && <button className="btn sm pri" onClick={() => sendLink(w)}>{w.access === 'link' ? 'New link' : 'Access link'}</button>}
                  </td>
                </tr>
              ))}</tbody></table></div>
          ) : <div className="empty">{st.workers.length ? 'No workers match.' : 'No workers yet. Add the first one.'}</div>}
          <p className="fine">A worker stays with one contractor. To end a worker's engagement or move them, or if a worker who has signed in forgets their password, ask the company's HR.</p>
        </div>

        <PasswordCard />
      </main>

      {form && <WorkerForm st={st} worker={form.worker} onClose={() => setForm(null)}
        onDone={(added) => { setForm(null); load(); if (added) sendLink(added, added.empNo); }} />}
      {link && <LinkBox link={link} onClose={() => setLink(null)} />}
    </div>
  );
}
