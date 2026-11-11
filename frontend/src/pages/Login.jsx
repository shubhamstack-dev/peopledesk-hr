import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

export default function Login({ boot, message, onSignedIn, onRegister }) {
  const s = (boot && boot.settings) || {};
  const googleOK = !!s.googleClientId && /^https?:/.test(window.location.protocol);
  const msOK = !!(s.msClientId && s.msTenantId) && /^https?:/.test(window.location.protocol);
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(message || '');
  const [busy, setBusy] = useState(false);
  const [msBusy, setMsBusy] = useState(false);
  const [showPw, setShowPw] = useState(false);       // passwords off for staff: contract workers and contractors still use one
  const [cand, setCand] = useState(false);           // 2.17: a candidate signing in to fill in their form
  const gRef = useRef(null);

  useEffect(() => { setErr(message || ''); }, [message]);

  // Google Identity Services: the browser gets an ID token, the server verifies it
  useEffect(() => {
    if (!googleOK || cand) return;
    E.loadGsi().then(() => {
      window.google.accounts.id.initialize({
        client_id: s.googleClientId, auto_select: false, ux_mode: 'popup',
        callback: async (resp) => {
          try { await api.post('/api/auth/google', { credential: resp.credential }); onSignedIn(); }
          catch (e) { setErr(e.message); }
        },
      });
      if (gRef.current) window.google.accounts.id.renderButton(gRef.current, { theme: 'outline', size: 'large', width: 400, text: 'signin_with' });
    }).catch((e) => setErr(e.message));
  }, [googleOK, s.googleClientId, onSignedIn, cand]);   // cand: the button is drawn again on returning from the candidate sign-in

  const run = async (fn) => {
    setBusy(true); setErr('');
    try { await fn(); await onSignedIn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const microsoft = async () => {
    setMsBusy(true);
    try {
      await run(async () => {
        const credential = await E.msLogin(s.msClientId, s.msTenantId);
        await api.post('/api/auth/microsoft', { credential });
      });
    } finally { setMsBusy(false); }
  };
  const submit = (e) => {
    e.preventDefault();
    if (!email.trim() || !pw) { setErr(cand ? 'Enter the e-mail address (or mobile number) HR has for you, and your password.' : 'Enter your e-mail or mobile number, and your password.'); return; }
    run(() => api.post('/api/auth/login', { email: email.trim(), password: pw }));
  };

  const group = (boot && boot.group) || 'Aequm India Private Limited';
  const n = (boot && boot.companies) || 0;
  return (
    <div className="login">
      <div className="art">
        <div className="brand" style={{ padding: 0 }}>
          <span className="logo"><img src="/aequm-mark.png" alt="Aequm" /></span>
          <div><b>{group}</b><small>HR</small></div>
        </div>
        <div>
          <h1>Your work, leave and pay in one place.</h1>
          <p>Sign in with your company Google or Microsoft account. Your administrator adds you from Google Workspace or Microsoft Entra ID; you do not need a separate password.</p>
        </div>
        <p className="fine" style={{ color: '#6F8C83' }}>Personnel, leave, time and shifts, performance and payroll</p>
      </div>

      {cand ? (
        <form onSubmit={submit} noValidate>
          <h2>Candidate sign-in</h2>
          <p className="sub" style={{ margin: 0 }}>For people HR has asked to fill in their details. Sign in to open your form: fill it in, save it, or send it.</p>
          <label className="field">E-mail address or mobile number<input className="inp" type="text" inputMode="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /><small>The one HR has for you, on the link HR sent.</small></label>
          <label className="field">Password<input className="inp" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
          <button className="btn pri lg" disabled={busy}>{busy ? 'Signing in…' : 'Sign in as a candidate'}</button>
          <p className="fine" style={{ margin: 0 }}>First time? Open the link HR sent you to create your candidate sign-in. Forgot your password? Ask HR to send the link again.</p>
          <p className="err" role="alert">{err}</p>
          <button type="button" className="btn ghost" onClick={() => { setCand(false); setErr(''); }}>Back: employee sign-in</button>
        </form>
      ) : (
      <form onSubmit={submit} noValidate>
        <h2>Sign in</h2>
        {googleOK ? <div ref={gRef} /> : s.googleClientId ? <p className="note warn">Google sign-in works when this page is opened from a web address (https).</p> : null}
        {msOK && (
          <button type="button" className="msbtn" disabled={busy} onClick={microsoft}>
            {/* Microsoft's official logo file, if placed in frontend/public/ms-logo.png */}
            <img src="/ms-logo.png" alt="" width="20" height="20" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
            <span>{msBusy ? 'Opening Microsoft…' : 'Sign in with Microsoft'}</span>
          </button>
        )}
        {s.allowPassword === false && !showPw && (
          <button type="button" className="btn" onClick={() => setShowPw(true)}>Contract worker or contractor? Sign in with a password</button>
        )}
        {(s.allowPassword !== false || showPw) && (
          <>
            {(googleOK || msOK) && <div className="or">or with a password</div>}
            <label className="field">E-mail or mobile number<input className="inp" type="text" inputMode="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <label className="field">Password<input className="inp" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
            <button className="btn pri lg" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
            <p className="fine" style={{ margin: 0 }}>First time? Open the access link you were sent to set your password.</p>
          </>
        )}
        <p className="err" role="alert">{err}</p>
        <div className="or">applying for a job?</div>
        <button type="button" className="btn lg" onClick={() => { setCand(true); setErr(''); setPw(''); }}>Candidate? Sign in to fill in your details</button>
        <div className="or">new here?</div>
        <button type="button" className="btn lg" onClick={onRegister}>Register your company</button>
      </form>
      )}
    </div>
  );
}
