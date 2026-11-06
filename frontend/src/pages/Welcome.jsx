import { useEffect, useState } from 'react';
import { api } from '../api.js';

/* Opened from an access link (#/welcome?t=…): a contract worker, a contractor's portal user, or anyone HR gave a
   link to sets their password, and is signed in. The link works once, for 7 days. */
export const welcomeToken = () => {
  const h = window.location.hash || '';
  if (!h.startsWith('#/welcome')) return '';
  return new URLSearchParams(h.split('?')[1] || '').get('t') || '';
};

export default function Welcome({ onSignedIn, onSignIn }) {
  const token = welcomeToken();
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState('');
  const [bad, setBad] = useState('');
  const [f, setF] = useState({ pw: '', again: '' });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) { setBad('This link is not complete. Open it again from the message you were sent.'); return; }
    api.post('/api/auth/invite/check', { token }).then(setInfo).catch((e) => setBad(e.message));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (f.pw.length < 10) { setErr('Use a password of at least 10 characters.'); return; }
    if (f.pw !== f.again) { setErr('The two passwords are different.'); return; }
    setBusy(true); setErr('');
    try {
      await api.post('/api/auth/invite/accept', { token, password: f.pw });
      window.history.replaceState(null, '', window.location.pathname);
      await onSignedIn();
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="art">
        <div className="brand" style={{ padding: 0 }}>
          <span className="logo"><img src="/aequm-mark.png" alt="Aequm" /></span>
          <div><b>{(info && info.company) || 'PeopleDesk'}</b><small>HR</small></div>
        </div>
        <div>
          <h1>{info && info.kind === 'contractor' ? 'Add and look after your workers.' : 'Your work, leave and attendance in one place.'}</h1>
          <p>Set a password to start. Afterwards, sign in with your e-mail address or mobile number and this password.</p>
        </div>
        <span />
      </div>
      {bad ? (
        <div className="card" style={{ alignSelf: 'center', justifySelf: 'center', width: 'min(400px,92vw)' }}>
          <h2>This link cannot be used</h2><p className="sub">{bad}</p>
          <button className="btn pri" onClick={() => { window.history.replaceState(null, '', window.location.pathname); onSignIn(); }}>Go to sign in</button>
        </div>
      ) : (
        <form onSubmit={submit} noValidate>
          <h2>{info ? `Welcome, ${info.name.split(' ')[0]}` : 'Checking the link…'}</h2>
          {info && <p className="sub" style={{ textAlign: 'center', margin: 0 }}>You will sign in as <b>{info.login}</b>.</p>}
          <label className="field">New password<input className="inp" type="password" autoComplete="new-password" autoFocus value={f.pw} onChange={(e) => setF({ ...f, pw: e.target.value })} disabled={!info} /><small>At least 10 characters</small></label>
          <label className="field">The same password again<input className="inp" type="password" autoComplete="new-password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} disabled={!info} /></label>
          <button className="btn pri lg" disabled={!info || busy}>{busy ? 'Saving…' : 'Set password and sign in'}</button>
          <p className="err" role="alert">{err}</p>
        </form>
      )}
    </div>
  );
}
