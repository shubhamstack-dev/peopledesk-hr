import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

export default function Login({ boot, message, onSignedIn }) {
  const s = (boot && boot.settings) || {};
  const googleOK = !!s.googleClientId && /^https?:/.test(window.location.protocol);
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(message || '');
  const [busy, setBusy] = useState(false);
  const gRef = useRef(null);

  useEffect(() => { setErr(message || ''); }, [message]);

  // Google Identity Services: the browser gets an ID token, the server verifies it
  useEffect(() => {
    if (!googleOK) return;
    E.loadGsi().then(() => {
      window.google.accounts.id.initialize({
        client_id: s.googleClientId, auto_select: false, ux_mode: 'popup',
        callback: async (resp) => {
          try { await api.post('/api/auth/google', { credential: resp.credential }); onSignedIn(); }
          catch (e) { setErr(e.message); }
        },
      });
      if (gRef.current) window.google.accounts.id.renderButton(gRef.current, { theme: 'outline', size: 'large', width: 360, text: 'signin_with' });
    }).catch((e) => setErr(e.message));
  }, [googleOK, s.googleClientId, onSignedIn]);

  const run = async (fn) => {
    setBusy(true); setErr('');
    try { await fn(); await onSignedIn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const submit = (e) => {
    e.preventDefault();
    if (!email.trim() || !pw) { setErr('Enter your work e-mail and password.'); return; }
    run(() => api.post('/api/auth/login', { email: email.trim(), password: pw }));
  };

  const group = (boot && boot.group) || 'Ankit Group';
  const n = (boot && boot.companies) || 0;
  return (
    <div className="login">
      <div className="art">
        <div className="brand stack" style={{ padding: 0 }}>
          <span className="logo"><img src="/ankit-logo.png" alt="Ankit Group" /></span>
          <div><b>{group} HR</b><small>{n} {n === 1 ? 'company' : 'companies'}</small></div>
        </div>
        <div>
          <h1>Your work, leave and pay in one place.</h1>
          <p>Sign in with your company Google account. Your administrator adds you from Google Workspace; you do not need a separate password.</p>
        </div>
        <p className="fine" style={{ color: '#6F8C83' }}>Personnel, leave, time and shifts, performance and payroll</p>
      </div>

      <form onSubmit={submit} noValidate>
        <h2>Sign in</h2>
        {googleOK ? <div ref={gRef} /> : s.googleClientId ? <p className="note warn">Google sign-in works when this page is opened from a web address (https).</p> : null}
        {s.allowPassword !== false && (
          <>
            {googleOK && <div className="or">or with a password</div>}
            <label className="field">Work e-mail<input className="inp" type="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <label className="field">Password<input className="inp" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
            <button className="btn pri lg" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          </>
        )}
        <p className="err" role="alert">{err}</p>
      </form>
    </div>
  );
}
