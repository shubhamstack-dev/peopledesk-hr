import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* PeopleDesk 2.19: the candidate portal. After signing in with the candidate sign-in they created (2.17), a candidate
   sees their applications (where each stands, as steps), their interviews, their offer (the letter as issued; accept
   with a typed signature, decline, or ask for changes), and their messages with HR, both ways. Their details form is
   the third tab. Everything is read from and written to the server for this candidate only
   (backend/app/cportal.py); nothing HR keeps for itself (notes, feedback, approvals) is sent here. */

const inr = (n) => (n === '' || n == null ? '—' : `₹ ${Math.round(+n).toLocaleString('en-IN')}`);
const dmy = (iso) => (iso && String(iso).length >= 10 ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : '');
const when = (ms) => (ms ? new Date(ms).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const FILE_TYPES = '.pdf,.jpg,.jpeg,.png,.webp,.doc,.docx';
const MAX_MB = 5;

function readFile(f) {
  return new Promise((res, rej) => {
    if (f.size > MAX_MB * 1024 * 1024) { rej(new Error(`${f.name} is larger than ${MAX_MB} MB.`)); return; }
    const r = new FileReader(); r.onload = () => res({ name: f.name, type: f.type, data: r.result }); r.onerror = () => rej(new Error(`${f.name} could not be read.`)); r.readAsDataURL(f);
  });
}
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type })); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function icsFor(iv, app, company) {
  const d = (iv.date || '').replace(/-/g, ''); const [h, m] = (iv.start || '00:00').split(':').map(Number);
  const end = new Date(2000, 0, 1, h, m + iv.duration); const p2 = (x) => String(x).padStart(2, '0');
  const esc = (s) => String(s || '').replace(/[\\;,]/g, (c) => `\\${c}`).replace(/\n/g, '\\n');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
  return ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//PeopleDesk//Candidate portal//EN', 'BEGIN:VEVENT', `UID:${iv.id}@peopledesk`, `DTSTAMP:${stamp}`,
    `DTSTART:${d}T${p2(h)}${p2(m)}00`, `DTEND:${d}T${p2(end.getHours())}${p2(end.getMinutes())}00`, `SUMMARY:${esc(`${iv.round}: ${app.job} (${company})`)}`,
    `LOCATION:${esc(iv.link || iv.venue || iv.modeLabel)}`, `DESCRIPTION:${esc([iv.modeLabel, iv.link, iv.venue, iv.panel.length ? `With ${iv.panel.join(', ')}` : ''].filter(Boolean).join('\n'))}`,
    'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
}

function Steps({ steps }) {
  return (
    <ol className="cp-steps" aria-label="Progress">
      {steps.map((s) => <li key={s.key} className={`cp-step ${s.state}`} aria-current={s.state === 'now' ? 'step' : undefined}><span className="dot" aria-hidden="true">{s.state === 'done' ? '✓' : s.state === 'stop' ? '×' : ''}</span>{s.label}</li>)}
    </ol>
  );
}

function Interviews({ app, company }) {
  if (!app.interviews.length) return null;
  const t = today();
  return (
    <div><h3>Interviews</h3>
      <div className="scroll"><table className="t"><thead><tr><th>Round</th><th>When</th><th>How</th><th>With</th><th></th></tr></thead><tbody>
        {app.interviews.map((iv) => (
          <tr key={iv.id}>
            <td><b>{iv.round}</b></td>
            <td>{dmy(iv.date)} at {iv.start}<div className="fine">{iv.duration} minutes</div></td>
            <td>{iv.modeLabel}{iv.link && iv.status === 'scheduled' && <div><a href={iv.link} target="_blank" rel="noopener noreferrer">Join the call</a></div>}{iv.venue && <div className="fine">{iv.venue}</div>}{iv.mode === 'phone' && iv.status === 'scheduled' && <div className="fine">We will call you on your mobile.</div>}</td>
            <td className="fine">{iv.panel.join(', ') || '—'}</td>
            <td><span className={`badge ${iv.status === 'scheduled' ? 'info' : iv.status === 'completed' ? 'ok' : ''}`}>{iv.statusLabel}</span>
              {iv.status === 'scheduled' && iv.date >= t && <div><button type="button" className="btn sm ghost" onClick={() => download(`interview-${iv.date}.ics`, icsFor(iv, app, company), 'text/calendar')}>Add to calendar</button></div>}</td>
          </tr>))}
      </tbody></table></div>
    </div>
  );
}

function OfferBox({ app, onDone, onSessionEnded }) {
  const o = app.offer;
  const [mode, setMode] = useState('');            // '' | accept | decline | negotiate
  const [f, setF] = useState({ name: '', agree: false, reason: '', askCtc: '', askDoj: '', askBonus: '', askOther: '', note: '' });
  const [file, setFile] = useState(null);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const go = async (e) => {
    e.preventDefault(); setErr(''); setBusy(true);
    try {
      const body = { appId: app.id, action: mode, letterNo: o.letterNo, ...f };
      if (mode === 'accept' && file) body.file = await readFile(file);
      const v = await api.post('/api/candidate/offer', body);
      E.toast(mode === 'accept' ? 'Offer accepted. Congratulations!' : mode === 'decline' ? 'Your answer is sent to HR' : 'Your request is sent to HR');
      setMode(''); onDone(v);
    } catch (x) { if (x.status === 401) onSessionEnded(x.message); else setErr(x.message); } finally { setBusy(false); }
  };
  const nego = o.negotiation || [];
  return (
    <div className="cp-offer">
      <h3>Your offer {o.round > 1 && <span className="badge info">Round {o.round}</span>}</h3>
      <div className="cp-terms">
        <div><small>Annual CTC</small><b>{inr(o.ctc)}</b></div><div><small>Joining on</small><b>{dmy(o.doj)}</b></div>
        {+o.joiningBonus > 0 && <div><small>Joining bonus</small><b>{inr(o.joiningBonus)}</b></div>}
        {o.expiry && o.status === 'issued' && <div><small>Please reply by</small><b>{dmy(o.expiry)}</b></div>}
        <div><small>Letter</small><b>{o.letterNo}</b></div>
      </div>
      {o.status === 'accepted' && <div className="note ok">You accepted this offer{o.signed && o.signed.name ? `, signed as ${o.signed.name}` : ''}{o.signed && o.signed.at ? ` on ${when(o.signed.at)}` : ''}.</div>}
      {o.status === 'declined' && <div className="note">You declined this offer{o.declineReason ? `: ${o.declineReason}` : ''}.</div>}
      {o.expired && o.status === 'issued' && <div className="note warn">This offer expired on {dmy(o.expiry)}. Write to HR in Messages if you would still like to join.</div>}
      {o.letterHtml
        ? <><iframe className="cp-letter" title={`Offer letter ${o.letterNo}`} sandbox="" srcDoc={o.letterHtml} />
            <div className="tools"><button type="button" className="btn sm" onClick={() => download(`Offer letter ${o.letterNo.replace(/\//g, '-')}.html`, o.letterHtml, 'text/html')}>Download the letter</button></div></>
        : <p className="fine">Your offer letter is with HR; ask in Messages for a copy.</p>}
      {nego.length > 0 && (
        <div><h3>Your requests</h3>
          {nego.map((x) => (
            <div key={x.id} className="apply-row">
              <div className="fine">{when(x.at)}</div>
              <div>You asked: {[x.askCtc !== '' && x.askCtc != null ? `CTC ${inr(x.askCtc)}` : '', x.askDoj ? `joining ${dmy(x.askDoj)}` : '', x.askBonus !== '' && x.askBonus != null ? `bonus ${inr(x.askBonus)}` : '', x.askOther].filter(Boolean).join('; ')}{x.note ? `. ${x.note}` : ''}</div>
              {x.outcome === 'open' ? <div className="fine">Waiting for HR’s answer.</div>
                : <div><b>HR:</b> {x.answer}{x.outcome === 'agreed' && <span className="badge ok" style={{ marginLeft: 6 }}>Agreed: a revised offer follows</span>}</div>}
            </div>))}
        </div>)}
      {o.canRespond && !mode && (
        <div className="tools" style={{ marginTop: 10 }}>
          <button type="button" className="btn pri" onClick={() => setMode('accept')}>Accept the offer</button>
          {o.canNegotiate && <button type="button" className="btn" onClick={() => setMode('negotiate')}>Ask for changes</button>}
          <button type="button" className="btn ghost" onClick={() => setMode('decline')}>Decline</button>
        </div>)}
      {mode && (
        <form className="apply-row" onSubmit={go} noValidate style={{ marginTop: 10 }}>
          {mode === 'accept' && <>
            <h3>Accept the offer</h3>
            <p className="fine">Your typed name is your signature on offer {o.letterNo}. If you have printed, signed and scanned the letter, attach it too.</p>
            <div className="form">
              <label className="field">Your full name, as on the letter<input className="inp" value={f.name} onChange={set('name')} autoComplete="name" /></label>
              <label className="field">Signed copy (optional: PDF or photo, up to {MAX_MB} MB)<input className="inp" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
            </div>
            <label className="chk"><input type="checkbox" checked={f.agree} onChange={set('agree')} /> I accept this offer on the terms in the letter, and I will join on {dmy(o.doj)}.</label>
          </>}
          {mode === 'decline' && <>
            <h3>Decline the offer</h3>
            <div className="form"><label className="field wide">Please tell us why<textarea className="inp" value={f.reason} onChange={set('reason')} maxLength={1000} /></label></div>
          </>}
          {mode === 'negotiate' && <>
            <h3>Ask for changes</h3>
            <p className="fine">Fill in only what you would like changed. HR will answer here and by e-mail; the offer as issued stays open meanwhile.</p>
            <div className="form">
              <label className="field">CTC you ask for (₹ a year)<input className="inp" type="number" min="0" value={f.askCtc} onChange={set('askCtc')} /></label>
              <label className="field">Joining date you ask for<input className="inp" type="date" min={today()} value={f.askDoj} onChange={set('askDoj')} /></label>
              <label className="field">Joining bonus you ask for (₹)<input className="inp" type="number" min="0" value={f.askBonus} onChange={set('askBonus')} /></label>
              <label className="field wide">Anything else (for example notice buyout, relocation, designation)<input className="inp" value={f.askOther} onChange={set('askOther')} maxLength={500} /></label>
              <label className="field wide">Why (optional)<textarea className="inp" value={f.note} onChange={set('note')} maxLength={1000} /></label>
            </div>
          </>}
          <p className="err" role="alert">{err}</p>
          <div className="btns" style={{ justifyContent: 'flex-start' }}>
            <button className={`btn ${mode === 'decline' ? 'danger' : 'pri'}`} disabled={busy}>{busy ? 'Sending…' : mode === 'accept' ? 'Accept and sign' : mode === 'decline' ? 'Decline the offer' : 'Send my request'}</button>
            <button type="button" className="btn ghost" onClick={() => { setMode(''); setErr(''); }}>Cancel</button>
          </div>
        </form>)}
    </div>
  );
}

function Applications({ view, onDone, onSessionEnded, toDetails }) {
  if (!view.applications.length) return <div className="card"><h2>Your applications</h2><p className="mut">HR has not put you forward for a job yet. Your details are under My details.</p></div>;
  return view.applications.map((app) => (
    <div className="card" key={app.id}>
      <div className="hd"><div><h2>{app.job}</h2><p className="sub">{[app.reqNo, app.location, app.appliedAt ? `since ${when(app.appliedAt).split(',')[0]}` : ''].filter(Boolean).join(' · ')}</p></div>
        <span className={`badge ${app.status.tone}`}>{app.status.label}</span></div>
      <Steps steps={app.steps} />
      <p>{app.status.detail}</p>
      {['sent', 'returned', 'draft'].includes(view.formStatus) && app.status.key === 'review' && <div className="note warn">Please finish <button type="button" className="btn sm" onClick={toDetails}>your details</button> so that HR can review your application.</div>}
      <Interviews app={app} company={view.company} />
      {app.offer && <OfferBox app={app} onDone={onDone} onSessionEnded={onSessionEnded} />}
    </div>));
}

function Messages({ view, onDone, onSessionEnded }) {
  const [text, setText] = useState(''); const [subject, setSubject] = useState(''); const [appId, setAppId] = useState('');
  const [files, setFiles] = useState([]); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { if (end.current) end.current.scrollIntoView({ block: 'nearest' }); }, [view.messages.length]);
  const send = async (e) => {
    e.preventDefault(); setErr('');
    if (!text.trim() && !files.length) { setErr('Write a message.'); return; }
    if (files.length > 5) { setErr('Attach up to 5 files.'); return; }
    setBusy(true);
    try {
      const fs = []; for (const f of files) fs.push(await readFile(f));
      const v = await api.post('/api/candidate/message', { text, subject, appId, files: fs });
      setText(''); setSubject(''); setFiles([]); e.target.reset(); E.toast('Sent to HR'); onDone(v);
    } catch (x) { if (x.status === 401) onSessionEnded(x.message); else setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="card"><h2>Messages with HR</h2>
      <p className="sub">{view.hasEmail ? 'Messages from HR also come to your e-mail; you can reply there or here.' : 'Messages from HR appear here.'}</p>
      <div className="thread">
        {view.messages.length ? view.messages.map((m) => (
          <div key={m.id} className={`msg ${m.dir === 'in' ? 'out' : 'in'}`}>
            <div className="fine">{m.from}{m.job ? ` · ${m.job}` : ''} · {when(m.at)}{m.via === 'email' ? ' · by e-mail' : ''}</div>
            {m.subject && <b>{m.subject}</b>}
            <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
            {m.files.map((f) => <div key={f.id}><a href={`/api/candidate/files/${encodeURIComponent(f.id)}`} target="_blank" rel="noopener noreferrer">📎 {f.name}</a></div>)}
          </div>)) : <p className="mut">No messages yet.</p>}
        <div ref={end} />
      </div>
      <form onSubmit={send} noValidate style={{ marginTop: 12 }}>
        <div className="form">
          <label className="field">Subject (optional)<input className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={160} /></label>
          {view.applications.length > 1 && <label className="field">About<select className="inp" value={appId} onChange={(e) => setAppId(e.target.value)}><option value="">General</option>{view.applications.map((a) => <option key={a.id} value={a.id}>{a.job}</option>)}</select></label>}
          <label className="field wide">Your message<textarea className="inp" value={text} onChange={(e) => setText(e.target.value)} maxLength={5000} style={{ minHeight: 110 }} /></label>
          <label className="field wide">Attach files (optional: up to 5, {MAX_MB} MB each)<input className="inp" type="file" multiple accept={FILE_TYPES} onChange={(e) => setFiles([...e.target.files])} /></label>
        </div>
        <p className="err" role="alert">{err}</p>
        <div className="btns" style={{ justifyContent: 'flex-start' }}><button className="btn pri" disabled={busy}>{busy ? 'Sending…' : 'Send to HR'}</button></div>
      </form>
    </div>
  );
}

export default function CandidatePortal({ details, login, onSignOut, onSessionEnded, changePassword }) {
  const [view, setView] = useState(null);
  const [tab, setTab] = useState('apps');
  const [err, setErr] = useState('');
  const [pwOpen, setPwOpen] = useState(false);
  const load = async () => {
    try { setView(await api.get('/api/candidate/portal')); setErr(''); }
    catch (x) { if (x.status === 401 || x.status === 403) onSessionEnded(x.message); else setErr(x.message); }
  };
  useEffect(() => {
    load();
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 60000);
    const f = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', f);
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', f); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab === 'msgs' && view && view.unread) api.post('/api/candidate/messages/read', {}).then(() => setView({ ...view, unread: 0 })).catch(() => {});
  }, [tab, view && view.unread]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!view) return <div className="apply">{err ? <div className="card"><h2>Could not load</h2><p className="err">{err}</p><button className="btn" onClick={load}>Try again</button></div> : <div className="boot">Loading…</div>}</div>;
  const openOffer = view.applications.some((a) => a.offer && a.offer.canRespond);
  return (
    <div className="apply">
      <div className="apply-head"><span className="logo"><img src="/aequm-mark.png" alt="" /></span>
        <div><b>{view.company}</b><small>Candidate portal</small></div>
        <div className="apply-who"><small>Signed in as {view.name}: {login || view.login}</small>
          <button type="button" className="btn sm ghost" onClick={() => setPwOpen(!pwOpen)}>Change password</button>
          <button type="button" className="btn sm" onClick={onSignOut}>Sign out</button></div></div>
      {pwOpen && changePassword(() => setPwOpen(false))}
      <div className="cp-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'apps'} className={tab === 'apps' ? 'on' : ''} onClick={() => setTab('apps')}>My applications{openOffer && <span className="badge ok">Offer</span>}</button>
        <button type="button" role="tab" aria-selected={tab === 'msgs'} className={tab === 'msgs' ? 'on' : ''} onClick={() => setTab('msgs')}>Messages{view.unread > 0 && <span className="badge warn">{view.unread} new</span>}</button>
        <button type="button" role="tab" aria-selected={tab === 'details'} className={tab === 'details' ? 'on' : ''} onClick={() => setTab('details')}>My details{['sent', 'returned', 'draft'].includes(view.formStatus) && <span className="badge warn">To finish</span>}</button>
      </div>
      {tab === 'apps' && <Applications view={view} onDone={setView} onSessionEnded={onSessionEnded} toDetails={() => setTab('details')} />}
      {tab === 'msgs' && <Messages view={view} onDone={setView} onSessionEnded={onSessionEnded} />}
      {tab === 'details' && details}
    </div>
  );
}
