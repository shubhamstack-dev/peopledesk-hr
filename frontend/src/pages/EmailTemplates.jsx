import { useEffect, useState } from 'react';
import { api } from '../api.js';
import * as E from '../engine/engine.js';

/* Administration › Email templates.
   Every e-mail PeopleDesk sends (access links, candidate-form links, reimbursement notices, approval
   notifications, trainer reports and scheduled-report deliveries) has a built-in wording. HR can
   override the subject and/or body here, per company (or, for a group administrator, for every
   company at once by leaving "This company only" off). The server (backend/app/email_templates.py)
   renders {{ merge tags }} the same way whichever wording is used, so nothing breaks if a template is
   only partly customised. */

const LABELS = {
  'access.invite': 'Access link: a new sign-in is given to an employee or a contractor’s portal user',
  'candidate.link': 'Candidate form link: HR sends a candidate the application-form link',
  'reimb.paid': 'Reimbursement paid: expense claims paid out in a reimbursement run',
  'statutory.submitted': 'Statutory details change – submitted: HR is asked to approve a change',
  'statutory.decided': 'Statutory details change – decided: the employee is told the outcome',
  'comp.launched': 'Salary planning opened: budget holders are told planning has started',
  'comp.submitted': 'Salary plan submitted: the next approver is asked to review it',
  'comp.decided': 'Salary plan decided: the holder (and the next approver) are told the outcome',
  'comp.comment': 'Salary plan comment: everyone on the budget is told about a new comment',
  'training.feedback': 'Trainer feedback report: ratings and comments sent to a trainer',
  'report.scheduled': 'Scheduled report: a saved report e-mailed on its schedule, as an Excel attachment',
};

export default function EmailTemplates() {
  const [cat, setCat] = useState(null);
  const [err, setErr] = useState('');
  const [edit, setEdit] = useState(null);
  useEffect(() => { api.get('/api/email-templates/catalogue').then((d) => setCat(d.templates)).catch((x) => setErr(x.message)); }, []);

  const S = E.getS();
  const cos = E.companiesForMe();
  // prefer a company-specific override over a group-wide one, same as the server does
  const bestOverride = (key) => {
    const mine = (S.emailTemplates || []).filter((t) => t.mailKey === key && t.active !== false);
    return mine.find((t) => t.companyId === E.getCO()) || mine.find((t) => !t.companyId) || null;
  };

  if (edit) return <Editor mailKey={edit} tpl={cat.find((t) => t.mailKey === edit)} existing={bestOverride(edit)} onDone={() => setEdit(null)} />;

  return (
    <div className="card">
      <h2>E-mail templates</h2>
      <p className="sub">What PeopleDesk sends, for each kind of e-mail. Change the wording below; an unedited one keeps sending exactly as it does today.</p>
      {err && <div className="note bad">{err}</div>}
      {!cat ? <div className="empty">Loading…</div> : (
        <div className="scroll"><table className="t">
          <thead><tr><th>E-mail</th><th>Customised</th><th /></tr></thead>
          <tbody>{cat.map((t) => {
            const o = bestOverride(t.mailKey);
            return (
              <tr key={t.mailKey}>
                <td>{LABELS[t.mailKey] || t.mailKey}</td>
                <td>{o ? (o.companyId ? 'This company' : 'Every company') : <span className="fine">Default wording</span>}</td>
                <td><button className="btn sm" onClick={() => setEdit(t.mailKey)}>Edit</button></td>
              </tr>
            );
          })}</tbody>
        </table></div>
      )}
      {cos.length > 1 && <p className="fine">A group administrator's template with no company chosen applies to every company unless that company has its own.</p>}
    </div>
  );
}

function Editor({ mailKey, tpl, existing, onDone }) {
  const S = E.getS();
  const [subject, setSubject] = useState(existing?.subject || tpl.subject);
  const [body, setBody] = useState(existing?.body || tpl.body);
  const [global, setGlobal] = useState(!!existing && !existing.companyId);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const save = () => {
    const rec = { ...(existing || {}), id: existing?.id || E.uid(), mailKey, subject: subject.trim(), body, active: true,
      companyId: E.isSuper() && global ? '' : E.getCO() };
    const i = (S.emailTemplates || []).findIndex((x) => x.id === rec.id);
    if (i >= 0) S.emailTemplates[i] = rec; else S.emailTemplates.push(rec);
    E.audit('E-mail template changed', mailKey, 'admin');
    E.saveNow(); setMsg('Saved.'); E.toast('Template saved');
  };

  const resetDefault = () => {
    if (!existing) { setSubject(tpl.subject); setBody(tpl.body); return; }
    S.emailTemplates = S.emailTemplates.filter((x) => x.id !== existing.id);
    E.audit('E-mail template reset to default', mailKey, 'admin'); E.saveNow();
    setSubject(tpl.subject); setBody(tpl.body); setMsg('Back to the default wording.'); E.toast('Reset to default');
  };

  const sendTest = async () => {
    setBusy(true); setMsg('');
    try { await api.post('/api/email-templates/test', { mailKey }); setMsg('Test e-mail sent to your own address, using the saved wording.'); }
    catch (x) { setMsg(x.message); } finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="hd"><h2>{(tpl && mailKey) || mailKey}</h2><button className="btn ghost" onClick={onDone}>Back to e-mail templates</button></div>
      <div className="form">
        <label className="field wide">Subject<input className="inp" value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
        <label className="field wide">Body<textarea className="inp" rows={10} value={body} onChange={(e) => setBody(e.target.value)} /></label>
        {E.isSuper() && <label className="chk"><input type="checkbox" checked={global} onChange={(e) => setGlobal(e.target.checked)} /> Apply to every company (not just mine)</label>}
      </div>
      <div className="card" style={{ background: 'var(--bg2, #f6f6f6)' }}>
        <h3>Merge tags</h3>
        <p className="fine">Use <code>{'{{ tag }}'}</code> in the subject or body. <code>{'{% if %}'}</code> and <code>{'{% for %}'}</code> also work, for advanced wording.</p>
        <ul className="fine">{(tpl.tags || []).map(([tag, desc]) => <li key={tag}><code>{`{{ ${tag} }}`}</code> — {desc}</li>)}</ul>
      </div>
      {msg && <p className="note">{msg}</p>}
      <div className="btns">
        <button className="btn ghost" disabled={busy} onClick={resetDefault}>Reset to default</button>
        <button className="btn" disabled={busy} onClick={sendTest}>Send a test to me</button>
        <button className="btn pri" disabled={busy} onClick={save}>Save</button>
      </div>
    </div>
  );
}
