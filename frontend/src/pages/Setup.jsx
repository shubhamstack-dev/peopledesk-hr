import { useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* mode "first": the very first sign-up on this server; that company runs the platform (group administrator).
   mode "register": any other company registers; it gets its own company and an administrator who sees only it. */
export default function Setup({ mode = 'register', onSignedIn, onSignIn }) {
  const first = mode === 'first';
  const [f, setF] = useState({ group: first ? 'Aequm India Private Limited' : '', coName: '', coCode: '', state: '29', name: '', email: '', pw: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if ((first && !f.group.trim()) || !f.coName.trim() || !f.coCode.trim() || !f.name.trim()) return setErr(first ? 'Fill in the group, company, code and your name.' : 'Fill in the company, code and your name.');
    if (!/^[A-Za-z0-9]{2,6}$/.test(f.coCode.trim())) return setErr('Short code: 2 to 6 letters or digits.');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) return setErr('Enter a valid e-mail address.');
    if (f.pw.length < 10) return setErr('Use a password of at least 10 characters.');
    setBusy(true); setErr('');
    try {
      if (first) {
        const { state, adminId } = E.buildSetupState(f);
        await api.post('/api/setup', { state, adminId, password: f.pw });
      } else {
        const { records, adminId } = E.buildRegisterRecords(f);
        await api.post('/api/register', { records, adminId, password: f.pw });
      }
      await onSignedIn();
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="art">
        <div className="brand" style={{ padding: 0 }}><span className="logo"><img src="/aequm-mark.png" alt="Aequm" /></span><div><b>Aequm India Private Limited</b><small>{first ? 'First-time setup' : 'Registration'}</small></div></div>
        <div>
          <h1>{first ? 'Set up the platform.' : 'Register your company.'}</h1>
          <p>{first
            ? 'This company runs the platform: its administrator sees every company that registers.'
            : 'Your company gets its own private space: your people, attendance, payroll and documents are seen only by your company. Employees are then added by you or brought in from Google Workspace or Microsoft.'}</p>
        </div>
        <span />
      </div>
      <form onSubmit={submit} noValidate>
        <h2>Register</h2>
        <p className="fine" style={{ margin: '-6px 0 4px', textAlign: 'center' }}>{first ? 'Create the platform company and its administrator.' : 'Create your company and your administrator account.'}</p>
        {first && <label className="field">Group name<input className="inp" value={f.group} onChange={set('group')} autoFocus /></label>}
        <label className="field">Company name<input className="inp" value={f.coName} onChange={set('coName')} placeholder="Legal name of the company" autoFocus={!first} /></label>
        <div className="form" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <label className="field">Short code<input className="inp" value={f.coCode} onChange={set('coCode')} maxLength={6} placeholder="e.g. AIPL" /><small>Used in employee numbers</small></label>
          <label className="field">State
            <select className="inp" value={f.state} onChange={set('state')}>
              {Object.entries(E.STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <label className="field">Your name<input className="inp" value={f.name} onChange={set('name')} /></label>
        <label className="field">Your work e-mail (this is your user ID)<input className="inp" type="email" value={f.email} onChange={set('email')} /></label>
        <label className="field">Password
          <input className="inp" type="password" autoComplete="new-password" value={f.pw} onChange={set('pw')} />
          <small>At least 10 characters.</small>
        </label>
        <p className="err" role="alert">{err}</p>
        <button className="btn pri lg" disabled={busy}>{busy ? 'Registering…' : 'Register and sign in'}</button>
        {onSignIn && <p className="fine" style={{ textAlign: 'center', margin: '4px 0 0' }}>Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); onSignIn(); }}>Sign in</a></p>}
      </form>
    </div>
  );
}
