import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';
import CandidatePortal from './CandidatePortal.jsx';

/* The candidate's own page. HR sends a link (#/apply?t=…). 2.17: the link does not open the form by itself: the
   first time, the candidate creates a candidate sign-in (their e-mail address or mobile number and a password of
   their own); after that they sign in, from the link or from the sign-in page (Candidate? Sign in). Signed in as a
   candidate, they fill in their details and attach their CV, save as they go and send the form. The form is read
   and written only with a candidate's session, so an employee (or anyone who merely has the link) cannot fill it
   in. When they join, HR converts them into an employee and these details become their employee record. The
   server checks and keeps the form (backend/app/candform.py). */
export const applyToken = () => {
  const h = window.location.hash || '';
  if (!h.startsWith('#/apply')) return '';
  return new URLSearchParams(h.split('?')[1] || '').get('t') || '';
};

const GENDERS = [['M', 'Male'], ['F', 'Female'], ['O', 'Other']];
const MARITAL = [['single', 'Single'], ['married', 'Married'], ['divorcee', 'Divorcee'], ['widowed', 'Widowed'], ['other', 'Other']];
const BLANK_ROW = {
  education: { level: 'Graduate', qualification: '', specialisation: '', institution: '', university: '', mode: 'full', fromYear: '', toYear: '', score: '', scoreType: 'pct' },
  prevJobs: { employer: '', designation: '', location: '', from: '', to: '', empCode: '', lastCtc: '', reason: '', mainResp: [], secResp: [], duties: '', contact: '' },
  references: { name: '', organisation: '', designation: '', relation: '', phone: '', email: '', years: '' },
  family: { relation: 'Father', name: '', dob: '', gender: '', occupation: '', phone: '', dependant: false },
  awards: { title: '', issuer: '', date: '', category: 'Professional', description: '' },
};
const LIST_FIELDS = {
  education: [['level', 'Level', 'select', () => E.EDU_LEVELS.map((x) => [x, x])], ['qualification', 'Qualification (e.g. B.E., B.Com, ITI Fitter)'], ['specialisation', 'Subject or specialisation'],
    ['institution', 'School, college or institute'], ['university', 'Board or university'], ['mode', 'Mode', 'select', () => [['full', 'Full time'], ['part', 'Part time'], ['distance', 'Distance or online']]],
    ['fromYear', 'From (year)', 'number'], ['toYear', 'Passed in (year)', 'number'], ['score', 'Result (e.g. 78.4 or First class)'], ['scoreType', 'Result as', 'select', () => [['pct', 'Percentage'], ['cgpa', 'CGPA'], ['grade', 'Grade or class']]]],
  prevJobs: [['employer', 'Employer', 'pick', 'employers'], ['designation', 'Designation', 'pick', 'designations'], ['location', 'City', 'pick', 'cities'], ['from', 'From', 'month'], ['to', 'To (empty if current)', 'month'], ['empCode', 'Employee number there'],
    ['lastCtc', 'Last annual CTC (₹)', 'number'], ['reason', 'Reason for leaving', 'pick', 'leaveReasons'], ['resp', 'Responsibilities', 'resp'], ['duties', 'Other responsibilities, in your words', 'textarea'], ['contact', 'HR contact there (name, e-mail or phone)']],
  references: [['name', 'Name'], ['organisation', 'Organisation', 'pick', 'employers'], ['designation', 'Their designation', 'pick', 'designations'], ['relation', 'How they know you (e.g. former manager)'], ['phone', 'Phone'], ['email', 'E-mail', 'email'], ['years', 'Known for (years)', 'number']],
  family: [['relation', 'Relationship', 'select', () => E.FAMILY_RELATIONS.map((x) => [x, x])], ['name', 'Name'], ['dob', 'Date of birth', 'date'], ['gender', 'Gender', 'select', () => [['', '—'], ...GENDERS]],
    ['occupation', 'Occupation'], ['phone', 'Phone'], ['dependant', 'Depends on me', 'check']],
  /* 2.14 */
  awards: [['title', 'Award or achievement'], ['issuer', 'Given by (organisation or body)'], ['date', 'Date', 'date'],
    ['category', 'Kind', 'select', () => [['Professional', 'Professional'], ['Academic', 'Academic'], ['Sports', 'Sports'], ['Community', 'Community and social'], ['Other', 'Other']]],
    ['description', 'What it was for', 'textarea']],
};
const LIST_TITLES = { education: ['Education', 'qualification', 'Your schooling, degrees, diplomas and certifications, highest first.'], prevJobs: ['Previous employment', 'job', 'Your employers so far, latest first. Leave empty if this is your first job.'],
  references: ['References', 'reference', 'People who can confirm your work, such as a former manager.'], family: ['Family', 'family member', 'Parents, spouse and children: for medical insurance and nominations.'],
  awards: ['Awards and achievements', 'award', 'Academic, professional, sports or community recognition. Leave empty if none.'] };

function Field({ label, type = 'text', value, onChange, opts, wide, help, disabled, req, maxLength }) {
  let input;
  if (type === 'select') input = <select className="inp" value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled}>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;
  else if (type === 'textarea') input = <textarea className="inp" value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled} maxLength={maxLength} required={req} />;
  else if (type === 'check') return <label className="chk" style={{ alignSelf: 'end' }}><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} disabled={disabled} /> {label}</label>;
  else input = <input className="inp" type={type} value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled} inputMode={type === 'number' ? 'decimal' : undefined} maxLength={type === 'number' || type === 'date' ? undefined : maxLength} required={req} />;
  return <label className={`field${wide ? ' wide' : ''}`}><span>{label}{req && <span className="reqm" aria-label="required"> *</span>}</span>{input}{help && <small>{help}</small>}</label>;
}

/* 2.12: a drop-down from the company's list, with Others for a name that is not there */
const OTHER = '__other';
function PickField({ label, value, onChange, names, disabled }) {
  const v = value ?? '';
  const hit = names.find((n) => n.toLowerCase() === String(v).trim().toLowerCase()) || '';
  const [other, setOther] = useState(!!String(v).trim() && !hit);
  const pick = (e) => {
    if (e.target.value === OTHER) { setOther(true); onChange(hit ? '' : v); } else { setOther(false); onChange(e.target.value); }
  };
  return (
    <label className="field">{label}
      <select className="inp" value={other ? OTHER : hit} onChange={pick} disabled={disabled}>
        <option value="">Choose</option>{names.map((n) => <option key={n} value={n}>{n}</option>)}<option value={OTHER}>Others</option>
      </select>
      {other && <input className="inp" value={v} onChange={(e) => onChange(e.target.value)} placeholder="Type it in full" disabled={disabled} aria-label={`${label}, typed`} />}
      <small>Choose Others if it is not on the list.</small>
    </label>
  );
}
/* 2.12: each responsibility on the company's list is a main one, a secondary one, or not part of the job */
function RespMatrix({ list, main, sec, onChange, disabled, rowKey }) {
  const [q, setQ] = useState('');
  if (!list.length) return null;
  const m = main || [], s = sec || [];
  const setOne = (id, val) => {
    const nm = m.filter((x) => x !== id), ns = s.filter((x) => x !== id);
    if (val === 'main') nm.push(id); if (val === 'sec') ns.push(id);
    onChange(nm, ns);
  };
  const shown = q ? list.filter((x) => `${x.name} ${x.category}`.toLowerCase().includes(q.toLowerCase())) : list;
  const cols = [['main', 'Main'], ['sec', 'Secondary'], ['', 'Not in this job']];
  return (
    <div className="field wide">Responsibilities<small>Mark each one you had in this job as main or secondary.</small>
      {list.length > 8 && <input className="inp" placeholder="Filter the list" value={q} onChange={(e) => setQ(e.target.value)} />}
      <div className="respm"><table className="t"><thead><tr><th>Responsibility</th>{cols.map(([k, l]) => <th key={k} className="c">{l}</th>)}</tr></thead>
        <tbody>{shown.map((x) => {
          const cur = m.includes(x.id) ? 'main' : s.includes(x.id) ? 'sec' : '';
          return (
            <tr key={x.id}><td>{x.name}{x.category && <div className="fine">{x.category}</div>}</td>
              {cols.map(([k, l]) => <td key={k} className="c"><input type="radio" name={`cresp_${rowKey}_${x.id}`} checked={cur === k} onChange={() => setOne(x.id, k)} disabled={disabled} aria-label={`${x.name}: ${l}`} /></td>)}</tr>
          );
        })}</tbody></table></div>
      <small>{m.length} main, {s.length} secondary</small>
    </div>
  );
}

const asForm = (r) => ({ education: [], prevJobs: [], references: [], family: [], skillLevels: {}, ...r.data, awards: (r.data && r.data.awards) || [] });

function FormPage({ initial, onSignOut, onSessionEnded, embedded }) {
  const [info, setInfo] = useState(initial);
  const [d, setD] = useState(() => asForm(initial));
  const [msg, setMsg] = useState({ text: '', err: false });
  const [busy, setBusy] = useState(false);
  const [cv, setCv] = useState(null);
  const [pwOpen, setPwOpen] = useState(false);
  const top = useRef(null);

  const ro = !info.editable;
  const set = (k) => (v) => setD({ ...d, [k]: v });
  const setRow = (list, i, k) => (v) => setD({ ...d, [list]: d[list].map((r, j) => (j === i ? { ...r, [k]: v } : r)) });
  /* 2.13: HR's field settings: what must be filled in (the software always needs the first set) and the longest entry */
  const rules = info.rules || {};
  const ALWAYS = ['firstName', 'dob', 'gender', 'phone', 'address', 'addrCity', 'emergencyName', 'emergencyPhone'];
  const isReq = (k) => ALWAYS.includes(k) || !!(rules[k] && rules[k].req);
  const F = (k, label, type, extra = {}) => <Field label={label} type={type} value={d[k]} onChange={set(k)} disabled={ro} req={isReq(k)} maxLength={(rules[k] && rules[k].max) || undefined} {...extra} />;
  const states = [['', 'Choose'], ...E.IN_STATES.map((x) => [x, x]), ['Outside India', 'Outside India']];
  const lists = { employers: [], designations: [], responsibilities: [], cities: [], leaveReasons: [], ...(info.lists || {}) };
  const skills = info.skills || [];
  const levels = Object.entries(info.levels || { 0: 'None', 1: 'Basic', 2: 'Working', 3: 'Advanced', 4: 'Expert' });
  const lv = d.skillLevels || {};
  const setLevel = (id, v) => { const next = { ...lv }; if (v === '') delete next[id]; else next[id] = +v; setD({ ...d, skillLevels: next }); };

  const pickCv = (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    if (f.size > 2 * 1024 * 1024) { setMsg({ text: 'The CV is larger than 2 MB.', err: true }); ev.target.value = ''; return; }
    const fr = new FileReader(); fr.onload = () => setCv({ name: f.name, type: f.type || 'application/pdf', size: f.size, data: fr.result }); fr.readAsDataURL(f);
  };
  const send = async (submit) => {
    setBusy(true); setMsg({ text: '', err: false });
    try {
      const r = await api.post('/api/candidate/form', { data: d, cv, submit });
      setInfo(r); setCv(null);
      setMsg({ text: submit ? 'Thank you. Your details have been sent.' : 'Saved. Sign in again any time to finish.', err: false });
    } catch (x) {
      if (x.status === 401) { onSessionEnded(x.message); return; }
      setMsg({ text: x.message, err: true });
    }
    finally { setBusy(false); if (top.current) top.current.scrollIntoView({ behavior: 'smooth' }); }
  };

  const listCard = (list) => {
    const [title, one, sub] = LIST_TITLES[list];
    return (
      <div className="card" key={list}><div className="hd"><div><h2>{title}</h2><p className="sub">{sub}</p></div>
        {!ro && <button type="button" className="btn" onClick={() => setD({ ...d, [list]: [...d[list], { ...BLANK_ROW[list] }] })}>Add {one}</button>}</div>
        {d[list].length ? d[list].map((r, i) => (
          <div key={r.id || i} className="apply-row"><div className="form">
            {LIST_FIELDS[list].map(([k, label, type, opts]) => (type === 'pick'
              ? <PickField key={k} label={label} names={lists[opts] || []} value={r[k]} onChange={setRow(list, i, k)} disabled={ro} />
              : type === 'resp'
                ? <RespMatrix key={k} rowKey={r.id || i} list={lists.responsibilities} main={r.mainResp} sec={r.secResp} disabled={ro}
                    onChange={(mainResp, secResp) => setD({ ...d, [list]: d[list].map((x, j) => (j === i ? { ...x, mainResp, secResp } : x)) })} />
                : <Field key={k} label={label} type={type} opts={opts && opts()} value={r[k]} onChange={setRow(list, i, k)} disabled={ro} wide={type === 'textarea'} />))}</div>
            {!ro && <button type="button" className="btn sm ghost" onClick={() => setD({ ...d, [list]: d[list].filter((_x, j) => j !== i) })}>Remove</button>}</div>
        )) : <p className="fine">None added.</p>}
      </div>
    );
  };

  return (
    <div className={embedded ? '' : 'apply'} ref={top}>
      {!embedded && <div className="apply-head"><span className="logo"><img src="/aequm-mark.png" alt="" /></span>
        <div><b>{info.company}</b><small>Your details{info.jobs.length ? ` for ${info.jobs.join(', ')}` : ''}</small></div>
        <div className="apply-who"><small>Signed in as a candidate: {info.login}</small>
          <button type="button" className="btn sm ghost" onClick={() => setPwOpen(!pwOpen)}>Change password</button>
          <button type="button" className="btn sm" onClick={onSignOut}>Sign out</button></div></div>}
      {!embedded && pwOpen && <ChangePassword onDone={() => setPwOpen(false)} onSessionEnded={onSessionEnded} />}
      {info.jobs.length > 0 && !ro && <div className="note">You are applying for <b>{info.jobs.join(', ')}</b>. You do not need a CV to start: fill in your experience, education{skills.length ? ', your level in the skills the job needs' : ''} and the rest, and attach a CV later if you have one.</div>}
      <div className="card"><h2>Hello {info.name.split(' ')[0]}</h2>
        <p className="sub">{ro ? (info.status === 'submitted' ? 'Your details have been sent to HR. If something needs to change, HR will contact you.' : 'This form is closed.')
          : 'Please fill in your details and attach your CV. You can save, sign out and sign in again to finish before you send it. When you join, these details go into your employee record, so you do not need to enter them again. Fields marked * must be filled in before you send the form.'}</p>
        {info.note && !ro && <div className="note warn">HR asked you to change: {info.note}</div>}
        {msg.text && <div className={`note ${msg.err ? 'bad' : 'ok'}`} role="alert">{msg.text}</div>}
      </div>

      <div className="card"><h2>About you</h2><div className="form">
        {F('firstName', 'First name')}{F('lastName', 'Last name')}{F('gender', 'Gender', 'select', { opts: [['', 'Choose'], ...GENDERS] })}{F('dob', 'Date of birth', 'date')}
        {F('marital', 'Marital status', 'select', { opts: [['', '—'], ...MARITAL] })}{d.marital === 'married' && F('anniversary', 'Wedding anniversary', 'date')}
        {F('fatherName', 'Father’s or husband’s name', 'text', { help: 'As on your PF and identity records' })}{F('blood', 'Blood group', 'select', { opts: [['', 'Not known'], ...E.BLOOD_GROUPS.map((x) => [x, x])] })}
        {F('nationality', 'Nationality')}{F('phone', 'Mobile')}{F('altPhone', 'Other phone')}
        <Field label="E-mail" value={info.email} onChange={() => {}} disabled help="To change it, ask HR" />
        {F('languages', 'Languages you speak')}{F('linkedin', 'LinkedIn profile')}</div></div>

      <div className="card"><h2>Address and emergency contact</h2><div className="form">
        {F('address', 'Current address: house, street and area', 'textarea', { wide: true })}{F('addrCity', 'City')}{F('addrState', 'State or union territory', 'select', { opts: states })}
        {F('addrPin', 'PIN code')}{F('addrCountry', 'Country', 'select', { opts: E.COUNTRIES.map((x) => [x, x]) })}{F('permAddress', 'Permanent address, if different', 'textarea', { wide: true })}
        {F('emergencyName', 'Emergency contact: name')}{F('emergencyRelation', 'Relationship', 'select', { opts: [['', 'Choose'], ...E.EMERGENCY_RELATIONS.map((x) => [x, x])] })}{F('emergencyPhone', 'Emergency contact: phone')}</div></div>

      <div className="card"><h2>Your current job</h2><div className="form">
        {F('currentCompany', 'Current or last employer')}{F('currentTitle', 'Current role')}{F('expYears', 'Total experience (years)', 'number')}
        {F('currentCtc', 'Current annual CTC (₹)', 'number')}{F('expectedCtc', 'Expected annual CTC (₹)', 'number')}{F('noticeDays', 'Notice period (days)', 'number')}
        {F('skills', skills.length ? 'Other skills' : 'Key skills', 'text', { wide: true })}{F('about', 'Anything else you would like us to know', 'textarea', { wide: true })}</div></div>

      {skills.length > 0 && (
        <div className="card"><h2>Your skills</h2>
          <p className="sub">Choose your level in each skill the job needs. Be accurate: HR checks your levels at the interview. Choose None if you do not have the skill.</p>
          {[['primary', 'Most important for the job'], ['secondary', 'Also useful']].map(([need, title]) => {
            const list = skills.filter((s) => s.need === need); if (!list.length) return null;
            return (
              <div key={need}><h3 style={{ margin: '12px 0 6px' }}>{title}</h3>
                <div className="form">{list.map((s) => (
                  <label key={s.id} className="field">{s.name}
                    <select className="inp" value={lv[s.id] ?? ''} onChange={(e) => setLevel(s.id, e.target.value)} disabled={ro}>
                      <option value="">Choose your level</option>{levels.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                  </label>
                ))}</div>
              </div>
            );
          })}
          <p className="fine">Basic: you know the essentials with help. Working: you use it on your own in daily work. Advanced: you handle complex work and guide others. Expert: others come to you; you set the standard.</p>
        </div>
      )}

      {listCard('education')}{listCard('prevJobs')}{listCard('awards')}{listCard('references')}{listCard('family')}

      <div className="card"><h2>CV</h2>
        <p className="sub">{info.cv ? `Attached: ${info.cv.name}.` : 'No CV attached yet.'}{cv ? ` Ready to save: ${cv.name}.` : ''}</p>
        {!ro && <label className="field">{info.cv ? 'Replace it' : 'Attach your CV'} (PDF or Word, up to 2 MB)<input className="inp" type="file" accept=".pdf,.doc,.docx,.rtf,.txt" onChange={pickCv} /></label>}
      </div>

      {!ro && (
        <div className="card">
          <label className="chk"><input type="checkbox" checked={!!d.declaration} onChange={(e) => set('declaration')(e.target.checked)} /> I declare that these details are true and complete. I understand that the company may check them, and that false details may lead to the offer being withdrawn or my employment ending.</label>
          <div className="btns" style={{ justifyContent: 'flex-start' }}>
            <button className="btn" disabled={busy} onClick={() => send(false)}>{busy ? 'Saving…' : 'Save and finish later'}</button>
            <button className="btn pri" disabled={busy} onClick={() => send(true)}>Send my details</button>
          </div>
          {msg.text && <p className={msg.err ? 'err' : 'fine'} role="alert">{msg.text}</p>}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- 2.17: getting in */
function ChangePassword({ onDone, onSessionEnded }) {
  const [cur, setCur] = useState(''); const [pw, setPw] = useState(''); const [pw2, setPw2] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const go = async (e) => {
    e.preventDefault(); setErr('');
    if (pw.length < 10) { setErr('Use a new password of at least 10 characters.'); return; }
    if (pw !== pw2) { setErr('The two new passwords are not the same.'); return; }
    setBusy(true);
    try { await api.post('/api/candidate/password', { current: cur, new: pw }); E.toast('Password changed'); onDone(); }
    catch (x) { if (x.status === 401) onSessionEnded(x.message); else setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <form className="card" onSubmit={go} noValidate><h2>Change your password</h2><div className="form">
      <label className="field">Current password<input className="inp" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
      <label className="field">New password<input className="inp" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
      <label className="field">New password again<input className="inp" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></label></div>
      <p className="err" role="alert">{err}</p>
      <div className="btns" style={{ justifyContent: 'flex-start' }}><button className="btn pri" disabled={busy}>{busy ? 'Saving…' : 'Change password'}</button><button type="button" className="btn ghost" onClick={onDone}>Cancel</button></div>
    </form>
  );
}

/* The link page before the form: create a candidate sign-in, or sign in. Shows nothing the candidate entered. */
function Gate({ token, view, onIn, onSignOutOther }) {
  const [want, setWant] = useState(view.hasAccount ? 'signin' : 'create');   // signin | create (also: set a new password)
  const [pw, setPw] = useState(''); const [pw2, setPw2] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const first = (view.name || '').split(' ')[0];
  const head = (
    <div className="apply-head"><span className="logo"><img src="/aequm-mark.png" alt="" /></span>
      <div><b>{view.company}</b><small>Candidate sign-in{view.jobs.length ? ` · ${view.jobs.join(', ')}` : ''}</small></div></div>
  );
  if (view.closed) return (
    <div className="apply">{head}<div className="card"><h2>Welcome aboard</h2>
      <p className="sub">You have joined the company, so your details are on your employee record now. Sign in as an employee to see them.</p>
      <button className="btn pri" onClick={() => { window.location.hash = ''; window.location.reload(); }}>Go to the sign-in page</button></div></div>
  );
  if (view.signedIn && view.signedIn !== 'this') {
    const as = { employee: 'an employee', contractor: 'a contractor', candidate: 'another candidate' }[view.signedIn];
    return (
      <div className="apply">{head}<div className="card"><h2>This form is for the candidate</h2>
        <p className="sub">This browser is signed in as {as}. The candidate form is filled in by the candidate, signed in as a candidate: an employee cannot fill it in for them.</p>
        <p className="sub">If you are {view.name}, sign out here and continue with your candidate sign-in. If you are from HR, send the link to the candidate instead.</p>
        <button className="btn pri" onClick={onSignOutOther}>Sign out and continue as {first}</button></div></div>
    );
  }
  const create = want === 'create';
  const go = async (e) => {
    e.preventDefault(); setErr('');
    if (create) {
      if (pw.length < 10) { setErr('Use a password of at least 10 characters.'); return; }
      if (pw !== pw2) { setErr('The two passwords are not the same.'); return; }
    } else if (!pw) { setErr('Enter your password.'); return; }
    setBusy(true);
    try {
      if (create) await api.post('/api/apply/account', { token, password: pw });
      else {
        const r = await api.post('/api/auth/login', { email: view.login, password: pw });
        if (r.kind !== 'candidate') { await api.post('/api/auth/logout').catch(() => {}); throw new Error('That is not a candidate sign-in.'); }
      }
      await onIn();
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="apply">{head}
      <form className="card cand-gate" onSubmit={go} noValidate>
        <h2>{create ? (view.hasAccount ? 'Set a new password' : `Hello ${first}: create your candidate sign-in`) : `Hello ${first}: sign in to your form`}</h2>
        <p className="sub">{create
          ? (view.hasAccount ? 'Choose a new password for your candidate sign-in. This link sets a password once.'
            : `${view.company} has asked you to fill in your details${view.jobs.length ? ` for ${view.jobs.join(', ')}` : ''}. First, create a candidate sign-in with a password of your own, so that only you can open and fill in your form. Afterwards, sign in with it from this link or from the sign-in page (Candidate? Sign in).`)
          : 'Sign in with the password you chose for your candidate sign-in.'}</p>
        <label className="field">You sign in with<input className="inp" type="text" autoComplete="username" value={view.login} readOnly /><small>To change it, ask HR.</small></label>
        <label className="field">{create ? 'Choose a password' : 'Password'}<input className="inp" type="password" autoFocus autoComplete={create ? 'new-password' : 'current-password'} value={pw} onChange={(e) => setPw(e.target.value)} />{create && <small>At least 10 characters.</small>}</label>
        {create && <label className="field">The password again<input className="inp" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></label>}
        <button className="btn pri lg" disabled={busy}>{busy ? 'Please wait…' : create ? (view.hasAccount ? 'Set the new password' : 'Create my sign-in') : 'Sign in'}</button>
        <p className="err" role="alert">{err}</p>
        {!create && view.canSetPassword && <button type="button" className="btn ghost" onClick={() => { setWant('create'); setErr(''); setPw(''); }}>Forgot your password? Set a new one with this link</button>}
        {!create && !view.canSetPassword && <p className="fine">Forgot your password? Ask HR to send you the link again; a new link lets you set a new one.</p>}
        {create && view.hasAccount && <button type="button" className="btn ghost" onClick={() => { setWant('signin'); setErr(''); setPw(''); setPw2(''); }}>I remember it: sign in</button>}
      </form>
    </div>
  );
}

/* mode "link": opened from HR's link; mode "session": a candidate signed in from the sign-in page */
export default function CandidateForm({ mode = 'link', onDone, onSignedOut, onSessionEnded }) {
  const token = mode === 'link' ? applyToken() : '';
  const [stage, setStage] = useState('loading');      // loading | gate | form | bad
  const [view, setView] = useState(null);
  const [form, setForm] = useState(null);
  const [bad, setBad] = useState('');

  const openLink = async () => {
    setStage('loading');
    try {
      const v = await api.post('/api/apply/open', { token });
      setView(v);
      if (v.signedIn === 'this' && !v.closed) await loadForm(); else setStage('gate');
    } catch (e) { setBad(e.message); setStage('bad'); }
  };
  const loadForm = async () => {
    try { setForm(await api.get('/api/candidate/form')); setStage('form'); }
    catch (e) {
      if (mode === 'link' && (e.status === 401 || e.status === 403)) { setStage('gate'); return; }
      if (mode === 'session') { onSessionEnded(e.message); return; }
      setBad(e.message); setStage('bad');
    }
  };
  useEffect(() => {
    if (mode === 'session') { loadForm(); return; }
    if (!token) { setBad('This link is not complete. Open it again from the message you were sent.'); setStage('bad'); return; }
    openLink();
  }, [token, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const signOut = async () => {
    await api.post('/api/auth/logout').catch(() => {});
    if (mode === 'session') onSignedOut(); else openLink();
  };
  const ended = (m) => { if (mode === 'session') onSessionEnded(m); else { E.toast(m || 'Sign in again.'); openLink(); } };

  if (stage === 'bad') return (
    <div className="apply"><div className="card"><h2>This link cannot be used</h2><p className="sub">{bad}</p>
      <p className="fine">Already created your candidate sign-in? You can sign in from the sign-in page: choose Candidate? Sign in.</p>
      {onDone && <button className="btn" onClick={onDone}>Go to the sign-in page</button>}</div></div>
  );
  if (stage === 'loading') return <div className="boot">Loading…</div>;
  if (stage === 'gate') return <Gate token={token} view={view} onIn={loadForm} onSignOutOther={signOut} />;
  // 2.19: signed in, the candidate has their portal: applications, messages, and this form as My details
  return (
    <CandidatePortal login={form.login} onSignOut={signOut} onSessionEnded={ended}
      changePassword={(done) => <ChangePassword onDone={done} onSessionEnded={ended} />}
      details={<FormPage key={form.submittedAt || 'f'} initial={form} onSignOut={signOut} onSessionEnded={ended} embedded />} />
  );
}
