import { useState } from 'react';
import { api, setOrg } from '../api.js';
import * as E from '../engine/engine.js';

/* existing: a registered company whose data was erased is set up again; otherwise a new company registers */
export default function Setup({ onSignedIn, onSignIn, existing }) {
  const [f, setF] = useState({ group: existing ? existing.name || '' : '', coName: '', coCode: '', org: '', state: '29', name: '', email: '', pw: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (!f.group.trim() || !f.coName.trim() || !f.coCode.trim() || !f.name.trim()) return setErr('Fill in the group, company, code and your name.');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) return setErr('Enter a valid e-mail address.');
    if (f.pw.length < 10) return setErr('Use a back-up password of at least 10 characters.');
    const org = (f.org || f.coCode).trim().toLowerCase();
    if (!existing && !/^[a-z][a-z0-9-]{2,29}$/.test(org)) return setErr('Company code for sign-in: 3 to 30 characters, starting with a letter; letters, digits and hyphens only.');
    setBusy(true); setErr('');
    try {
      const { state, adminId } = E.buildSetupState(f);
      if (existing) await api.post('/api/setup', { state, adminId, password: f.pw });
      else { setOrg(org); const r = await api.post('/api/register', { org, state, adminId, password: f.pw }).catch((x) => { setOrg(''); throw x; }); setOrg(r.org.slug); }
      await onSignedIn();
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="art">
        <div className="brand" style={{ padding: 0 }}><span className="logo"><img src="/aequm-mark.png" alt="Aequm" /></span><div><b>PeopleDesk HR</b><small>{existing ? `Set up ${existing.slug}` : 'Registration'}</small></div></div>
        <div>
          <h1>Register your company.</h1>
          <p>Your company gets its own private space: nobody from another company can see your people or data. More companies of your group can be added later. Employees are then brought in from Google Workspace or Microsoft.</p>
        </div>
        <span />
      </div>
      <form onSubmit={submit} noValidate>
        <h2>Register</h2>
        <p className="fine" style={{ margin: '-6px 0 4px', textAlign: 'center' }}>Create your company and the administrator account.</p>
        <label className="field">Organisation name<input className="inp" value={f.group} onChange={set('group')} placeholder="Your group or company name" autoFocus /></label>
        <label className="field">First company<input className="inp" value={f.coName} onChange={set('coName')} placeholder="Legal name of the company" /></label>
        <div className="form" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <label className="field">Short code<input className="inp" value={f.coCode} onChange={set('coCode')} maxLength={6} placeholder="e.g. AIPL" /><small>Used in employee numbers</small></label>
          <label className="field">State
            <select className="inp" value={f.state} onChange={set('state')}>
              {Object.entries(E.STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        {!existing && <label className="field">Company code for sign-in<input className="inp" value={f.org} onChange={set('org')} placeholder={(f.coCode || 'e.g. aequm').toLowerCase()} autoCapitalize="none" spellCheck={false} /><small>Everyone in your company enters this to sign in. Letters, digits and hyphens.</small></label>}
        <label className="field">Your name<input className="inp" value={f.name} onChange={set('name')} /></label>
        <label className="field">Your work e-mail (Google or Microsoft)<input className="inp" type="email" value={f.email} onChange={set('email')} /></label>
        <label className="field">Back-up password
          <input className="inp" type="password" autoComplete="new-password" value={f.pw} onChange={set('pw')} />
          <small>For signing in until Google or Microsoft sign-in is set up. At least 10 characters.</small>
        </label>
        <p className="err" role="alert">{err}</p>
        <button className="btn pri lg" disabled={busy}>Register and sign in</button>
        {onSignIn && <p className="fine" style={{ textAlign: 'center', margin: '4px 0 0' }}>Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); onSignIn(); }}>Sign in</a></p>}
      </form>
    </div>
  );
}
