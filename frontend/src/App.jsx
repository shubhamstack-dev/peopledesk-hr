import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from './api.js';
import * as E from './engine/engine.js';
import { useHash } from './useHash.js';
import Shell from './components/Shell.jsx';
import PageHost from './components/PageHost.jsx';
import Login from './pages/Login.jsx';
import Setup from './pages/Setup.jsx';
import Home from './pages/Home.jsx';
import Approvals from './pages/Approvals.jsx';
import Settings from './pages/Settings.jsx';

const SESSION_ENDED = 'Your session has ended. Sign in again.';

export default function App() {
  const [phase, setPhase] = useState('loading');       // loading | setup | login | app | down
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
    E.sync.state.rev = res.rev;
  }, []);

  // After signing in, start at Home (as the original did); on a page reload, stay where you were
  const enter = useCallback(async (fromSignIn = true) => {
    try { await loadState(); setPhase('app'); refresh(); if (fromSignIn || !window.location.hash) window.location.hash = '#/home'; }
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
  E.hooks.logout = () => signOut();
  E.hooks.onSessionEnded = () => signOut(SESSION_ENDED);
  E.hooks.onSyncRejected = (msg) => { E.toast(msg); reload(); };

  useEffect(() => {
    (async () => {
      try {
        const b = await api.get('/api/bootstrap');
        setBoot(b);
        if (b.needsSetup) { setPhase('setup'); return; }
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

  // Views are run here, before the shell draws, because they set the route the menu highlights
  const resolved = useMemo(() => (phase === 'app' && E.getMe() ? E.resolvePage(hash) : null), [phase, hash, version]); // eslint-disable-line react-hooks/exhaustive-deps

  if (phase === 'loading') return <div className="boot">Loading…</div>;
  if (phase === 'down') return (
    <div className="boot"><div className="card" style={{ maxWidth: 460 }}><h2>The server is not answering</h2>
      <p className="sub">{message}</p><button className="btn pri" onClick={() => window.location.reload()}>Try again</button></div></div>
  );
  if (phase === 'setup') return <Setup onSignedIn={() => enter(true)} onDemoLoaded={() => toSignIn('Demo data loaded. Choose someone below to try the app.')} />;
  if (phase === 'login' || !resolved) return <Login boot={boot} message={message} onSignedIn={() => enter(true)} />;

  let page;
  if (resolved.page === 'home') page = <Home />;
  else if (resolved.page === 'inbox') page = <Approvals />;
  else if (resolved.page === 'settings') page = <Settings onSignedOut={signOut} onWiped={() => { E.sync.stop(); E.clearSession(); toSignIn(); }} />;
  else page = <PageHost view={resolved.view} />;

  return (
    <Shell resolved={resolved} onSignOut={() => signOut()} onSwitchCompany={(id) => { E.switchCompany(id); refresh(); }}>
      {page}
    </Shell>
  );
}
