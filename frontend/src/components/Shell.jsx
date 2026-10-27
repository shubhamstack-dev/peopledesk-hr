import { useEffect, useState } from 'react';
import * as E from '../engine/engine.js';

const readGroups = () => { try { return JSON.parse(sessionStorage.getItem('pd.menu')) || {}; } catch { return {}; } };

export default function Shell({ resolved, onSignOut, onSwitchCompany, children }) {
  const S = E.getS(), me = E.getMe(), CO = E.getCO();
  const [menuOpen, setMenuOpen] = useState(false);       // phone: menu slid in
  const [groups, setGroups] = useState(readGroups);      // groups opened or closed by hand

  const here = resolved.group && resolved.group.grp;
  // Arriving in a group opens it again, even if it was closed by hand earlier
  useEffect(() => {
    if (here && groups[here] === false) { const g = { ...groups }; delete g[here]; setGroups(g); sessionStorage.setItem('pd.menu', JSON.stringify(g)); }
    setMenuOpen(false);
  }, [resolved.page, here]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (e) => { if (!e.target.closest('.side') && !e.target.closest('.burger')) setMenuOpen(false); };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  const toggle = (grp, isOpen) => {
    const g = { ...groups, [grp]: !isOpen };
    setGroups(g); sessionStorage.setItem('pd.menu', JSON.stringify(g));
  };

  const link = (it) => {
    const cnt = it.badge ? it.badge() : 0;
    return (
      <a key={E.itemHref(it)} href={E.itemHref(it)} className={E.itemOn(it) ? 'on' : ''}>
        {it.label}{cnt ? <span className="cnt">{cnt}</span> : null}
      </a>
    );
  };

  const cos = E.companiesForMe();
  const co = E.company();
  const bottom = E.BOTTOM.filter(([id]) => id !== 'inbox' || E.isManager() || E.isHR());

  return (
    <div className={`shell${menuOpen ? ' open' : ''}`} id="shell">
      <aside className="side" aria-label="Menu">
        <div className="brand">
          <div className="mark">{E.initials(S.group.name || 'HR')}</div>
          <div><b>{S.group.name || 'PeopleDesk HR'}</b><small>{co ? co.name : ''}</small></div>
        </div>
        {cos.length > 1 && (
          <select className="cosw" aria-label="Company" value={CO || ''} onChange={(e) => onSwitchCompany(e.target.value)}>
            {cos.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        )}
        <nav className="nav">
          {E.MENU.map((m) => {
            if (!m.items) return E.itemShown(m) ? link(m) : null;
            const its = m.items.filter(E.itemShown);
            if (!its.length) return null;
            const isHere = its.some(E.itemOn) || here === m.grp;
            const isOpen = (isHere && groups[m.grp] !== false) || groups[m.grp] === true;
            return (
              <div className="mgrp" key={m.grp}>
                <button className="mhead" aria-expanded={isOpen} aria-controls={`mg_${m.grp}`} onClick={() => toggle(m.grp, isOpen)}>
                  <span>{m.label}</span><span className="chev" aria-hidden="true" />
                </button>
                <div className="msub" id={`mg_${m.grp}`} hidden={!isOpen}>{its.map(link)}</div>
              </div>
            );
          })}
        </nav>
        <div className="foot">Saved to the company server.</div>
      </aside>

      <div className="main">
        <header className="top">
          <button className="burger" aria-label="Open menu" onClick={() => setMenuOpen((v) => !v)}>☰</button>
          <div className="ttl">{resolved.group ? <small>{resolved.group.label}</small> : null}<h1>{resolved.title}</h1></div>
          <span className="sp" />
          <div className="who">
            <div className="av">{E.initials(E.fullName(me))}</div>
            <div className="txt"><b>{E.fullName(me)}</b><small>{E.ROLES[me.role]}{E.isManager() ? ', manager' : ''}</small></div>
            <button className="btn sm" onClick={onSignOut}>Sign out</button>
          </div>
        </header>
        <main className="content" id="content">{children}</main>
      </div>

      <nav className="bottomnav">
        {bottom.map(([id, label]) => <a key={id} href={`#/${id}`} className={resolved.page === id ? 'on' : ''}>{label}</a>)}
      </nav>
    </div>
  );
}
