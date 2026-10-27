import { useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

export default function Setup({ onSignedIn, onDemoLoaded }) {
  const [f, setF] = useState({ group: '', coName: '', coCode: '', state: '29', name: '', email: '', pw: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (!f.group.trim() || !f.coName.trim() || !f.coCode.trim() || !f.name.trim()) return setErr('Fill in the group, company, code and your name.');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) return setErr('Enter a valid e-mail address.');
    if (f.pw.length < 10) return setErr('Use a back-up password of at least 10 characters.');
    setBusy(true); setErr('');
    try {
      const { state, adminId } = E.buildSetupState(f);
      await api.post('/api/setup', { state, adminId, password: f.pw });
      await onSignedIn();
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  const demo = async () => {
    setBusy(true); setErr('');
    try { await api.post('/api/setup/demo', { state: E.buildDemoState() }); await onDemoLoaded(); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="art">
        <div className="brand" style={{ padding: 0 }}><div className="mark">HR</div><div><b>PeopleDesk HR</b><small>First-time setup</small></div></div>
        <div>
          <h1>Set up your group and first company.</h1>
          <p>More companies can be added later; each has its own policies, payroll and statutory registrations. Employees are then brought in from Google Workspace.</p>
        </div>
        <span />
      </div>
      <form onSubmit={submit} noValidate>
        <h2>Create the group administrator</h2>
        <label className="field">Group name<input className="inp" value={f.group} onChange={set('group')} placeholder="e.g. Nilgiri Group" autoFocus /></label>
        <label className="field">First company<input className="inp" value={f.coName} onChange={set('coName')} placeholder="Legal name of the company" /></label>
        <div className="form" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <label className="field">Company code<input className="inp" value={f.coCode} onChange={set('coCode')} maxLength={6} placeholder="e.g. NTPL" /></label>
          <label className="field">State
            <select className="inp" value={f.state} onChange={set('state')}>
              {Object.entries(E.STATES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <label className="field">Your name<input className="inp" value={f.name} onChange={set('name')} /></label>
        <label className="field">Your Google Workspace e-mail<input className="inp" type="email" value={f.email} onChange={set('email')} /></label>
        <label className="field">Back-up password
          <input className="inp" type="password" autoComplete="new-password" value={f.pw} onChange={set('pw')} />
          <small>For signing in before Google sign-in is configured. At least 10 characters.</small>
        </label>
        <p className="err" role="alert">{err}</p>
        <button className="btn pri lg" disabled={busy}>Create and sign in</button>
        <div className="or">or</div>
        <button type="button" className="btn" disabled={busy} onClick={demo}>Explore with demo data</button>
      </form>
    </div>
  );
}
