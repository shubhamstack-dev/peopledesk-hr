import { useEffect, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* Settings and data › E-mail sending (group administrator). The server keeps the password and the client secret
   encrypted and never sends them back: an empty box keeps the saved one. */
const PRESETS = {
  m365: { label: 'Microsoft 365', host: 'smtp.office365.com', port: 587, security: 'starttls' },
  google: { label: 'Google Workspace / Gmail', host: 'smtp.gmail.com', port: 587, security: 'starttls' },
  zoho: { label: 'Zoho Mail (India)', host: 'smtppro.zoho.in', port: 587, security: 'starttls' },
};

export default function MailSettings() {
  const [f, setF] = useState(null);
  const [saved, setSaved] = useState(null);
  const [testTo, setTestTo] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ ok: '', err: '' });
  useEffect(() => {
    api.get('/api/admin/mail').then((d) => { setSaved(d); setF({ ...d, password: '', clientSecret: '' }); }).catch((x) => setMsg({ ok: '', err: x.message }));
  }, []);
  if (!f) return <div className="card"><h2>E-mail sending</h2><p className="fine">{msg.err || 'Loading…'}</p></div>;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'number' ? +e.target.value : e.target.value });
  const preset = (k) => { const p = PRESETS[k]; setF({ ...f, host: p.host, port: p.port, security: p.security, auth: k === 'm365' && f.auth !== 'password' ? 'm365' : f.auth }); };
  const save = async (e) => {
    if (e) e.preventDefault();
    setBusy(true); setMsg({ ok: '', err: '' });
    try { const d = await api.post('/api/admin/mail', f); setSaved(d); setF({ ...d, password: '', clientSecret: '' }); setMsg({ ok: 'Saved', err: '' }); E.toast('E-mail settings saved'); return true; }
    catch (x) { setMsg({ ok: '', err: x.message }); return false; } finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMsg({ ok: '', err: '' });
    try { await api.post('/api/admin/mail/test', { to: testTo || f.fromAddr || f.user }); setMsg({ ok: `Test sent to ${testTo || f.fromAddr || f.user}. Check the inbox (and spam).`, err: '' }); }
    catch (x) { setMsg({ ok: '', err: x.message }); } finally { setBusy(false); }
  };
  const status = saved.source === 'app' ? 'Ready' : saved.source === 'env' ? 'From the server settings (.env)' : 'Not set up';
  return (
    <form className="card" onSubmit={save}>
      <div className="hd"><div><h2>E-mail sending: SMTP <span className={`badge ${saved.source === 'none' ? 'warn' : 'ok'}`}>{status}</span></h2>
        <p className="sub">Used for candidate links, access links, approvals and reports. Fill in the servers for:</p></div></div>
      <div className="tools" style={{ marginBottom: 10 }}>{Object.entries(PRESETS).map(([k, p]) => <button key={k} type="button" className="btn sm" onClick={() => preset(k)}>{p.label}</button>)}</div>
      <div className="form">
        <label className="field">Server<input className="inp" value={f.host} onChange={set('host')} placeholder="smtp.office365.com" /></label>
        <label className="field">Port<input className="inp" type="number" value={f.port} onChange={set('port')} /></label>
        <label className="field">Security
          <select className="inp" value={f.security} onChange={set('security')}><option value="starttls">STARTTLS (port 587)</option><option value="ssl">SSL/TLS (port 465)</option><option value="none">None (a relay inside the network)</option></select></label>
        <label className="field">Sign-in
          <select className="inp" value={f.auth} onChange={set('auth')}><option value="password">User name and password</option><option value="m365">Microsoft 365 (OAuth, no password)</option><option value="none">None (relay)</option></select></label>
        <label className="field">User (mailbox)<input className="inp" value={f.user} onChange={set('user')} placeholder="hr@company.in" autoComplete="off" /></label>
        <label className="field">From address<input className="inp" value={f.fromAddr} onChange={set('fromAddr')} placeholder="hr@company.in" /></label>
        <label className="field">From name<input className="inp" value={f.fromName} onChange={set('fromName')} placeholder="Aequm HR" /></label>
        {f.auth === 'password' && <label className="field">Password <small>{saved.hasPassword ? 'set: leave empty to keep it' : ''}</small><input className="inp" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} /></label>}
      </div>
      {f.auth === 'm365' && (
        <>
          <h3 style={{ margin: '14px 0 4px' }}>Microsoft 365 app (OAuth)</h3>
          <p className="fine" style={{ marginTop: 0 }}>The app needs the Exchange Online application permission <b>SMTP.SendAsApp</b> with admin consent, and the mailbox granted to the app in Exchange. Another app of yours that already sends from the same mailbox (same tenant and client ID) can be reused.</p>
          <div className="form">
            <label className="field">Tenant ID<input className="inp mono" value={f.tenant} onChange={set('tenant')} placeholder="Directory (tenant) ID" /></label>
            <label className="field">Client ID<input className="inp mono" value={f.clientId} onChange={set('clientId')} placeholder="Application (client) ID" /></label>
            <label className="field">Client secret <small>{saved.hasSecret ? 'set: leave empty to keep it' : ''}</small><input className="inp" type="password" autoComplete="new-password" value={f.clientSecret} onChange={set('clientSecret')} /></label>
          </div>
        </>
      )}
      <div className="tools" style={{ marginTop: 12, alignItems: 'center' }}>
        <button className="btn pri" disabled={busy}>Save settings</button>
        <input className="inp" style={{ maxWidth: 300 }} value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder={`Send a test to… (${f.fromAddr || f.user || 'an address'})`} />
        <button type="button" className="btn" disabled={busy} onClick={test}>Send test</button>
      </div>
      <p className="fine">Save before Send test. The password and the client secret are stored encrypted with the server's JWT_SECRET; if that key changes, enter them again.</p>
      {msg.ok && <p className="note">{msg.ok}</p>}
      {msg.err && <p className="err" role="alert">{msg.err}</p>}
    </form>
  );
}
