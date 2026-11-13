import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from './api.js';
import { allowShared } from './engine/sync.js';
import * as E from './engine/engine.js';
import { useHash } from './useHash.js';
import Shell from './components/Shell.jsx';
import PageHost from './components/PageHost.jsx';
import Login from './pages/Login.jsx';
import Setup from './pages/Setup.jsx';
import Home from './pages/Home.jsx';
import Approvals from './pages/Approvals.jsx';
import Settings from './pages/Settings.jsx';
import DocTemplates from './pages/DocTemplates.jsx';
import EmailTemplates from './pages/EmailTemplates.jsx';
import Reports from './pages/Reports.jsx';
import FieldMasking from './pages/FieldMasking.jsx';
import ContractorPortal from './pages/ContractorPortal.jsx';
import Welcome, { welcomeToken } from './pages/Welcome.jsx';
import CandidateForm from './pages/CandidateForm.jsx';

const SESSION_ENDED = 'Your session has ended. Sign in again.';

export default function App() {
  const [phase, setPhase] = useState('loading');       // loading | setup | login | welcome | apply | candidate | app | contractor | down
  const [boot, setBoot] = useState(null);
  const [message, setMessage] = useState('');
  const [version, refresh] = useReducer((x) => x + 1, 0);
  const hash = useHash();

  /* ------------------------------------------------ getting in and out */
  const toSignIn = useCallback(async (msg = '') => {
    try {
      const b = await api.get('/api/bootstrap');
      setBoot(b); setMessage(msg);
      setPhase(b.needsSetup ? 'setup' : 'login');
    } catch (e) { setMessage(e.message); setPhase('down'); }
  }, []);

  const loadState = useCallback(async () => {
    const res = await api.get('/api/state');
    if (!E.loadServerState(res.state, res.me)) throw new Error('Your employee record was not found.');
    allowShared(E.isSuper());
    E.sync.state.rev = res.rev;
  }, []);

  // After signing in, start at Home (as the original did); on a page reload, stay where you were
  const enter = useCallback(async (fromSignIn = true) => {
    try {
      // a contractor's portal user has the contractor portal instead of the main app
      const who = await api.get('/api/session');
      if (who.kind === 'contractor') { E.clearSession(); setPhase('contractor'); return; }
      // 2.17: a candidate has only their own form
      if (who.kind === 'candidate') { E.clearSession(); setPhase('candidate'); return; }
      await loadState(); setPhase('app'); refresh(); if (fromSignIn || !window.location.hash) window.location.hash = '#/home';
      setTimeout(() => E.showLoginNotices(), 400);   // birthday, anniversary and shift-change greetings, once a day
    }
    catch (e) { await toSignIn(e.status === 401 ? '' : e.message); }
  }, [loadState, toSignIn]);

  const signingOut = useRef(false);
  const signOut = useCallback(async (msg = '') => {
    if (signingOut.current) return;
    signingOut.current = true;
    try {
      await E.sync.flush();
      E.sync.stop(); E.clearSession();
      await api.post('/api/auth/logout').catch(() => {});
      await toSignIn(msg);
    } finally { signingOut.current = false; }
  }, [toSignIn]);

  const reload = useCallback(async () => {
    try { await loadState(); refresh(); }
    catch (e) { if (e.status === 401) signOut(SESSION_ENDED); else E.toast(e.message); }
  }, [loadState, signOut]);

  /* The engine calls these: redraw after a change, sign out, a refused or failed save */
  E.hooks.refresh = refresh;
  E.hooks.reload = reload;
  E.hooks.logout = () => signOut();
  E.hooks.onSessionEnded = () => signOut(SESSION_ENDED);
  E.hooks.onSyncRejected = (msg) => { E.toast(msg); reload(); };

  useEffect(() => {
    (async () => {
      try {
        // a candidate opening HR's link: they create their candidate sign-in, or sign in, on that page (2.17)
        if ((window.location.hash || '').startsWith('#/apply')) { setPhase('apply'); return; }
        const b = await api.get('/api/bootstrap');
        setBoot(b);
        if (b.needsSetup) { setPhase('setup'); return; }
        if (welcomeToken() !== '' || (window.location.hash || '').startsWith('#/welcome')) { setPhase('welcome'); return; }   // an access link
        await enter(false);
      } catch (e) { setMessage(e.message); setPhase('down'); }
    })();
  }, [enter]);

  /* Pick up changes other people saved: on returning to the tab and every minute,
     unless something is being edited here */
  useEffect(() => {
    if (phase !== 'app') return undefined;
    const check = async () => {
      if (document.hidden || E.sync.busy() || document.getElementById('dlg')?.open) return;
      const a = document.activeElement;
      if (a && a.closest && a.closest('#content') && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName)) return;
      try { const { rev } = await api.get('/api/rev'); if (rev !== E.sync.state.rev) await reload(); }
      catch (e) { if (e.status === 401) signOut(SESSION_ENDED); }
    };
    const t = setInterval(check, 60000);
    window.addEventListener('focus', check);
    const leave = (e) => { if (E.sync.pending()) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', leave);
    return () => { clearInterval(t); window.removeEventListener('focus', check); window.removeEventListener('beforeunload', leave); };
  }, [phase, reload, signOut]);

  /* A new page closes any open dialog and starts at the top */
  useEffect(() => { E.closeDlg(); window.scrollTo(0, 0); }, [hash]);
  // A candidate or access link pasted into a tab where PeopleDesk is already open changes only the address's #part,
  // so the page does not load again: start over, as if the link were opened fresh.
  useEffect(() => {
    const h = hash || '';
    if (phase === 'loading') return;
    if ((h.startsWith('#/apply') && phase !== 'apply') || (h.startsWith('#/welcome') && phase !== 'welcome') || (phase === 'apply' && !h.startsWith('#/apply'))) window.location.reload();
  }, [hash]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Views are run here, before the shell draws, because they set the route the menu highlights
  const resolved = useMemo(() => (phase === 'app' && E.getMe() ? E.resolvePage(hash) : null), [phase, hash, version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (phase === 'loading') return <div className="boot">Loading…</div>;
  if (phase === 'down') return (
    <div className="boot"><div className="card" style={{ maxWidth: 460 }}><h2>The server is not answering</h2>
      <p className="sub">{message}</p><button className="btn pri" onClick={() => window.location.reload()}>Try again</button></div></div>
  );
  if (phase === 'apply') return <CandidateForm mode="link" onDone={() => { window.history.replaceState(null, '', window.location.pathname); window.location.reload(); }} />;
  if (phase === 'candidate') return (
    <CandidateForm mode="session"
      onSignedOut={() => { window.location.hash = ''; toSignIn(); }}
      onSessionEnded={(m) => { window.location.hash = ''; toSignIn(m || SESSION_ENDED); }} />
  );
  if (phase === 'welcome') return <Welcome onSignedIn={() => enter(true)} onSignIn={() => toSignIn()} />;
  if (phase === 'contractor') return (
    <ContractorPortal
      onSignOut={async () => { await api.post('/api/auth/logout').catch(() => {}); window.location.hash = ''; toSignIn(); }}
      onSessionEnded={() => toSignIn(SESSION_ENDED)} />
  );
  if (phase === 'setup' || phase === 'register') return <Setup mode={phase === 'setup' ? 'first' : 'register'} onSignedIn={() => enter(true)} onSignIn={boot && !boot.needsSetup ? () => { setMessage(''); setPhase('login'); } : null} />;
  if (phase === 'login' || !resolved) return <Login boot={boot} message={message} onSignedIn={() => enter(true)} onRegister={() => setPhase(boot && boot.needsSetup ? 'setup' : 'register')} />;

  let page;
  if (resolved.page === 'home') page = <Home />;
  else if (resolved.page === 'inbox') page = <Approvals />;
  else if (resolved.page === 'settings') page = <Settings onSignedOut={signOut} onWiped={() => { E.sync.stop(); E.clearSession(); toSignIn(); }} />;
  else if (resolved.page === 'doctemplates') page = <DocTemplates key={hash} />;
  else if (resolved.page === 'emailtemplates') page = <EmailTemplates key={hash} />;
  else if (resolved.page === 'reports') page = <Reports key={hash} />;
  else if (resolved.page === 'fieldmasking') page = <FieldMasking key={hash} />;
  else page = <PageHost view={resolved.view} />;

  return (
    <Shell resolved={resolved} onSignOut={() => signOut()} onSwitchCompany={(id) => { E.switchCompany(id); refresh(); }}>
      {page}
    </Shell>
  );
}
