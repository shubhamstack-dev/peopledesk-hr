import { useRef, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

export default function Settings({ onSignedOut, onWiped }) {
  const S = E.getS();
  const s = S.settings;
  const [f, setF] = useState({ group: S.group.name || '', idleMin: s.idleMin || 30, allowDemo: !!s.allowDemo });
  const [pw, setPw] = useState({ current: '', next: '', again: '' });
  const [pwErr, setPwErr] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const sup = E.isSuper();

  const saveSettings = (e) => {
    e.preventDefault();
    S.group.name = f.group.trim() || S.group.name;
    s.idleMin = Math.max(5, parseInt(f.idleMin, 10) || 30);
    s.allowDemo = f.allowDemo;
    E.audit('Settings changed', '');
    E.saveNow(); E.toast('Saved'); E.hooks.refresh();
  };

  const changePw = async (e) => {
    e.preventDefault(); setPwErr('');
    if (pw.next.length < 10) return setPwErr('Use at least 10 characters.');
    if (pw.next !== pw.again) return setPwErr('The two new passwords are different.');
    try { await api.post('/api/auth/password', { current: pw.current, new: pw.next }); setPw({ current: '', next: '', again: '' }); E.toast('Password changed'); }
    catch (x) { setPwErr(x.message); }
  };

  const backup = async () => {
    setBusy(true);
    try { await E.sync.flush(); const data = await api.get('/api/admin/backup'); E.downloadText(`peopledesk-backup-${E.todayISO()}.json`, JSON.stringify(data), 'application/json'); }
    catch (x) { E.toast(x.message); } finally { setBusy(false); }
  };

  const restore = (e) => {
    const file = e.target.files[0]; e.target.value = '';
    if (!file) return;
    const fr = new FileReader();
    fr.onload = async () => {
      let d;
      try { d = JSON.parse(fr.result); if (!Array.isArray(d.employees)) throw new Error(); }
      catch { E.toast('That is not a backup from this app.'); return; }
      if (!(await E.confirmBox('Restore this backup?', `It replaces everything on the server with ${d.employees.length} employees in ${(d.companies || []).length} companies. Everyone is signed out.`, 'Restore'))) return;
      setBusy(true);
      try { await api.post('/api/admin/restore', { state: d }); E.toast('Backup restored'); onSignedOut('Backup restored. Sign in again.'); }
      catch (x) { E.toast(x.message); } finally { setBusy(false); }
    };
    fr.readAsText(file);
  };

  const wipe = async () => {
    if (!(await E.confirmBox('Erase all data?', 'Every company, employee, leave, attendance and payroll record on the server is deleted. Download a backup first.', 'Erase everything'))) return;
    try { await api.post('/api/admin/wipe'); E.toast('All data erased'); onWiped(); } catch (x) { E.toast(x.message); }
  };

  return (
    <>
      <form className="card" onSubmit={saveSettings}>
        <h2>App settings</h2>
        <div className="form">
          <label className="field">Group name<input className="inp" value={f.group} onChange={(e) => setF({ ...f, group: e.target.value })} /></label>
          <label className="field">Sign out after minutes without activity<input className="inp" type="number" min={5} value={f.idleMin} onChange={(e) => setF({ ...f, idleMin: e.target.value })} /></label>
          <label className="chk" style={{ gridColumn: '1/-1' }}>
            <input type="checkbox" checked={f.allowDemo} onChange={(e) => setF({ ...f, allowDemo: e.target.checked })} />
            Show &ldquo;try the app as&rdquo; on the sign-in page (demo only: anyone could sign in as anyone; turn off for real use)
          </label>
        </div>
        <div className="btns" style={{ justifyContent: 'flex-start' }}><button className="btn pri">Save</button></div>
      </form>

      <form className="card" onSubmit={changePw}>
        <h2>Your back-up password</h2>
        <p className="sub">For signing in without Google. Leave the current password blank if you have never had one.</p>
        <div className="form">
          <label className="field">Current password<input className="inp" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></label>
          <label className="field">New password<input className="inp" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></label>
          <label className="field">New password again<input className="inp" type="password" autoComplete="new-password" value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} /></label>
        </div>
        <p className="err">{pwErr}</p>
        <div className="btns" style={{ justifyContent: 'flex-start' }}><button className="btn">Change password</button></div>
      </form>

      <div className="card">
        <h2>Data</h2>
        <p className="sub">Everything is stored in the MySQL database on the server and saved as you work. {sup
          ? 'A backup is one JSON file with every company, employee and record, including sign-in data, so keep it safe. A backup from the earlier browser-only version can be restored here too.'
          : 'Backups, restores and erasing are done by the group administrator.'}</p>
        {sup && (
          <div className="tools">
            <button className="btn" disabled={busy} onClick={backup}>Download backup</button>
            <button className="btn" disabled={busy} onClick={() => fileRef.current.click()}>Restore from backup</button>
            <input ref={fileRef} type="file" accept=".json" hidden onChange={restore} />
            <button className="btn danger" disabled={busy} onClick={wipe}>Erase all data</button>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Activity log</h2>
        {S.audit.length ? (
          <div className="scroll" style={{ maxHeight: 360 }}><table className="t">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
            <tbody>{S.audit.slice(0, 200).map((a) => (
              <tr key={a.id || a.at}><td>{E.dt(a.at)}</td><td>{E.nameOf(a.by)}</td><td>{a.what}</td><td>{a.detail}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <div className="empty">Nothing recorded yet.</div>}
      </div>
    </>
  );
}
