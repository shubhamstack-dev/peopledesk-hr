import * as E from '../engine/engine.js';

/* Approve and Reject use data-act; the engine records the decision, saves and redraws. */
function Decide({ act, id }) {
  return (
    <td className="r" style={{ whiteSpace: 'nowrap' }}>
      <button className="btn danger sm" data-act={act} data-id={id} data-ok="0">Reject</button>{' '}
      <button className="btn ok sm" data-act={act} data-id={id} data-ok="1">Approve</button>
    </td>
  );
}

function Row({ it }) {
  const S = E.getS();
  const e = E.empById(it.r.empId);
  if (it.kind === 'leave') {
    const lt = E.ltById(it.r.typeId); const b = E.leaveBalance(e, lt, it.r.from);
    return (
      <tr>
        <td><b>{E.fullName(e)}</b><div className="fine">{e.empNo}</div></td>
        <td>{lt.name}{it.r.status === 'pending-hr' && <> <span className="badge info">HR approval</span></>}
          {it.r.steps && <div className="fine">Step: {(it.r.steps.find((x) => !x.decision) || {}).label}</div>}</td>
        <td>{E.dShort(it.r.from)}{it.r.to !== it.r.from ? ` to ${E.dShort(it.r.to)}` : ''}
          <div className="fine">{E.num(it.r.days)} day{it.r.days === 1 ? '' : 's'}{it.r.half ? ', half day' : ''}</div></td>
        <td>{it.r.reason}<div className="fine">Balance left after this: {E.num(b.available)}</div>
          {(it.r.attachments || []).map((a) => <div key={a.fileId}><a href={`/api/files/${a.fileId}`} target="_blank" rel="noopener noreferrer">📎 {a.name}</a></div>)}</td>
        <Decide act="leaveDecide" id={it.r.id} />
      </tr>
    );
  }
  if (it.kind === 'reg') {
    return (
      <tr>
        <td><b>{E.fullName(e)}</b></td><td>{it.r.type === 'shift' ? 'Shift change' : 'Punch time correction'}
          {it.r.steps && <div className="fine">Step: {(it.r.steps.find((x) => !x.decision) || {}).label}</div>}</td>
        <td>{E.dShort(it.r.date)}<div className="fine" dangerouslySetInnerHTML={{ __html: E.regAsked(it.r) }} /></td>
        <td>{it.r.reason}</td>
        <Decide act="regDecide" id={it.r.id} />
      </tr>
    );
  }
  if (it.link) {
    const when = it.kind === 'ot' ? 'This and last month' : it.kind === 'exit' ? `Last day ${E.dShort(it.r.lwd)}`
      : it.kind === 'offer' ? E.inr0(it.r.ctc) : it.kind === 'req' ? `${it.r.positions} position${it.r.positions > 1 ? 's' : ''}` : '';
    return (
      <tr><td><b>{it.r.cand || E.nameOf(it.r.empId)}</b></td><td>{it.what}</td><td>{when}</td><td />
        <td className="r"><a className="btn sm" href={it.link}>Open</a></td></tr>
    );
  }
  const cyc = S.cycles.find((c) => c.id === it.r.cycleId);
  return (
    <tr><td><b>{E.fullName(e)}</b></td><td>Goals for approval</td><td>{cyc ? cyc.name : ''}</td>
      <td>{S.goals.filter((g) => g.empId === e.id && g.cycleId === it.r.cycleId).length} goals</td>
      <td className="r"><a className="btn sm" href={`#/performance?emp=${e.id}`}>Review goals</a></td></tr>
  );
}

export default function Approvals() {
  const items = E.pendingForMe();
  return (
    <div className="card">
      <h2>Waiting for you</h2>
      <p className="sub">Leave, attendance corrections, goal sheets, resignations and clearances, job requisitions, offers and interview feedback, expense claims, leave encashment, promotion proposals, statutory detail changes, and enrolment tasks for new joiners.</p>
      {items.length ? (
        <div className="scroll"><table className="t">
          <thead><tr><th>Employee</th><th>Request</th><th>When</th><th>Details</th><th /></tr></thead>
          <tbody>{items.map((it, i) => <Row key={`${it.kind}-${it.r.id || i}-${i}`} it={it} />)}</tbody>
        </table></div>
      ) : <div className="empty">Nothing is waiting for you.</div>}
    </div>
  );
}
