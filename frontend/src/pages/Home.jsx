import { useEffect, useState } from 'react';
import * as E from '../engine/engine.js';

const clockText = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });

/* Buttons with data-act are handled by the engine (punch, apply for leave, kudos…), which
   saves and then asks React to redraw. */
export default function Home() {
  const S = E.getS(), me = E.getMe(), CO = E.getCO();
  const [clock, setClock] = useState(clockText);
  useEffect(() => { const t = setInterval(() => setClock(clockText()), 10000); return () => clearInterval(t); }, []);

  const t = E.todayISO(), now = new Date();
  const sf = E.shiftFor(me, t), p = E.punchOf(me.id, t), lv = E.leaveOn(me, t), hol = E.holidayOn(me, t);
  const week = Array.from({ length: 7 }, (_, i) => E.addDays(t, i - ((E.D(t).getDay() + 6) % 7)));
  const status = hol ? `Holiday: ${hol.name}` : lv && !lv.half ? `On ${(E.ltById(lv.typeId) || {}).name || 'leave'} today` : sf.off ? 'Weekly off today'
    : p && p.in ? (p.out ? `Punched out at ${E.hm(p.out)}, ${E.num((p.out - p.in) / 3600000, 1)} hours` : `Punched in at ${E.hm(p.in)}`)
      : sf.shift ? `${sf.shift.name} shift ${sf.shift.start}–${sf.shift.end}` : '';
  const canPunch = !(lv && !lv.half) && !(p && p.out) && !hol;
  const punchedIn = !!(p && p.in);
  const bal = E.leaveTypesFor(me).filter((lt) => lt.credit !== 'none').map((lt) => ({ lt, b: E.leaveBalance(me, lt) }));
  const up = S.holidays.filter((h) => h.companyId === me.companyId && h.date >= t && (!h.locationId || h.locationId === me.locationId))
    .sort((a, b) => (a.date < b.date ? -1 : 1)).slice(0, 4);
  const md = (iso) => (iso ? iso.slice(5) : '');
  const soon = (iso) => { if (!iso) return false; for (let i = 0; i < 7; i++) if (md(E.addDays(t, i)) === md(iso)) return true; return false; };
  const cel = E.coEmployees(me.companyId).filter((e) => soon(e.dob) || (soon(e.doj) && e.doj.slice(0, 4) < t.slice(0, 4)));
  const posts = [
    ...S.posts.filter((x) => x.companyId === me.companyId).map((x) => ({ ...x, kind: 'post' })),
    ...S.feedback.filter((f) => f.type === 'kudos' && !f.private && (E.empById(f.to) || {}).companyId === me.companyId).map((f) => ({ ...f, kind: 'kudos' })),
  ].sort((a, b) => b.at - a.at).slice(0, 8);
  const tasks = E.pendingForMe();

  let hr = null;
  if (E.isHR()) {
    const emps = E.coEmployees(); const ym = t.slice(0, 7); const last = E.ymAdd(ym, -1);
    const joiners = emps.filter((e) => (e.doj || '').startsWith(ym)).length;
    const leavers = S.employees.filter((e) => e.companyId === CO && e.exit && (e.exit.lwd || '').startsWith(ym)).length;
    const run = S.payRuns.find((r) => r.companyId === CO && r.month === last);
    hr = (
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="kpi"><span>Headcount, {E.company().code}</span><b>{emps.length}</b><small>{joiners} joined, {leavers} leaving this month</small></div>
        <div className="kpi"><span>Punched in today</span><b>{emps.filter((e) => E.punchOf(e.id, t)).length}</b><small>{emps.filter((e) => E.leaveOn(e, t)).length} on leave</small></div>
        <div className="kpi"><span>Payroll, {E.monthName(last)}</span><b>{run ? (run.status === 'locked' ? 'Locked' : 'Draft') : 'Not run'}</b><small><a href="#/payroll">Payroll runs</a></small></div>
        <div className="kpi"><span>Waiting for approval</span><b>{tasks.length}</b><small><a href="#/inbox">Open approvals</a></small></div>
      </div>
    );
  }

  const greeting = now.getHours() < 12 ? 'morning' : now.getHours() < 17 ? 'afternoon' : 'evening';
  return (
    <>
      <section className="dayband">
        <div className="clock" id="clock">{clock}</div>
        <div>
          <p className="hello">Good {greeting}, {me.firstName}</p>
          <div className="meta">{now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}. {status}</div>
          <div className="week">
            {week.map((d) => {
              const s = E.shiftFor(me, d), l = E.leaveOn(me, d), h = E.holidayOn(me, d);
              const cls = [d === t && 'today', (s.off || h) && 'off', l && 'lv'].filter(Boolean).join(' ');
              return (
                <div key={d} className={cls} title={h ? h.name : l ? 'On leave' : s.off ? 'Weekly off' : s.shift ? s.shift.name : ''}>
                  {E.D(d).toLocaleDateString('en-IN', { weekday: 'short' })}<b>{+d.slice(8)}</b>
                  {h ? 'Holiday' : l ? 'Leave' : s.off ? 'Off' : s.shift ? s.shift.start : ''}
                </div>
              );
            })}
          </div>
        </div>
        <div>
          {canPunch && (
            <button className={`btn lg${punchedIn ? '' : ' pri'}`} data-act="punch" id="punchBtn"
              style={punchedIn ? undefined : { background: 'var(--mari-strong)', borderColor: 'var(--mari-strong)', color: '#2B1D00' }}>
              {punchedIn ? 'Punch out' : 'Punch in'}
            </button>
          )}
        </div>
      </section>

      {hr}

      <div className="grid g21">
        <div>
          {tasks.length > 0 && (
            <div className="card">
              <div className="hd"><div><h2>Waiting for your approval</h2></div><a className="btn sm" href="#/inbox">Open approvals</a></div>
              {tasks.slice(0, 6).map((it, i) => (
                <div key={i} className="fine" style={{ padding: '5px 0', borderBottom: '1px solid var(--rule)' }}>
                  <b style={{ color: 'var(--ink)' }}>{it.r.cand || E.nameOf(it.r.empId)}</b>:{' '}
                  {it.link ? <a href={it.link}>{it.what}</a>
                    : it.kind === 'leave' ? `${E.ltById(it.r.typeId).name}, ${E.dShort(it.r.from)}, ${E.num(it.r.days)} days`
                      : it.kind === 'reg' ? `attendance correction for ${E.dShort(it.r.date)}` : 'goal sheet'}
                </div>
              ))}
            </div>
          )}

          <div className="card">
            <div className="hd"><div><h2>Leave balance</h2></div>
              <div className="tools"><button className="btn sm pri" data-act="leaveApply">Apply for leave</button><button className="btn sm" data-act="regNew">Correct attendance</button></div>
            </div>
            <div className="grid g3">
              {bal.length ? bal.map(({ lt, b }) => (
                <div className="kpi" key={lt.id}><span>{lt.name}</span><b>{E.num(b.available)}</b><small>{b.pending ? `${E.num(b.pending)} pending, ` : ''}{E.num(b.used)} taken</small></div>
              )) : <p className="mut">No leave types.</p>}
            </div>
          </div>

          <div className="card feed">
            <div className="hd"><div><h2>Company feed</h2><p className="sub">Announcements and kudos.</p></div>
              <div className="tools">{E.isHR() && <button className="btn sm" data-act="postNew">Post announcement</button>}<button className="btn sm" data-act="kudosNew">Give kudos</button></div>
            </div>
            {posts.length ? posts.map((x) => (x.kind === 'post' ? (
              <div className="post" key={x.id}><div className="av">{E.initials(E.nameOf(x.by))}</div>
                <div><b>{x.title}</b><div>{x.text}</div><div className="fine">{E.nameOf(x.by)}, {E.dt(x.at)}</div></div></div>
            ) : (
              <div className="post" key={x.id}><div className="av" style={{ background: 'var(--mari-soft)', color: 'var(--warn)' }}>★</div>
                <div><b>{E.nameOf(x.from)}</b> recognised <b>{E.nameOf(x.to)}</b>{x.value ? ` for ${x.value}` : ''}<div>{x.text}</div><div className="fine">{E.dt(x.at)}</div></div></div>
            ))) : <div className="empty">No posts yet.</div>}
          </div>
        </div>

        <div>
          <div className="card"><h2>Upcoming holidays</h2>
            {up.length ? up.map((h) => (
              <div key={h.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--rule)' }}>
                <span>{h.name}</span><span className="mut">{E.D(h.date).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</span>
              </div>
            )) : <p className="mut">None in the calendar.</p>}
          </div>
          <div className="card"><h2>Celebrations this week</h2>
            {cel.length ? cel.map((e) => (
              <div key={e.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '5px 0' }}>
                <div className="av">{E.initials(E.fullName(e))}</div>
                <div><b>{E.fullName(e)}</b><div className="fine">{soon(e.dob) ? `Birthday, ${E.dShort(`${t.slice(0, 4)}-${md(e.dob)}`)}`
                  : `${E.yearsBetween(e.doj, E.addDays(t, 7))} years with us, ${E.dShort(`${t.slice(0, 4)}-${md(e.doj)}`)}`}</div></div>
              </div>
            )) : <p className="mut">No birthdays or work anniversaries this week.</p>}
          </div>
          <div className="card"><h2>Quick links</h2>
            <div className="tools"><a className="btn sm" href="#/payslips">Latest payslip</a><a className="btn sm" href="#/performance">My goals</a><a className="btn sm" href="#/attendance">My attendance</a><a className="btn sm" href="#/org">Organisation chart</a></div>
          </div>
        </div>
      </div>
    </>
  );
}
