import { useLayoutEffect, useRef } from 'react';

/* Shows one of the feature screens carried over from the original app.
   Each screen is a function that returns { title, html, after }: the HTML is put in place,
   then after() wires up its forms. Buttons inside use data-act="…" and are handled by the
   engine's document-level listeners, so they work the same as before.
   To move a screen to React, add a component for it and list it in App.jsx and in
   REACT_PAGES (scripts/build-engine.py), as was done for Home, Approvals and Settings. */
export default function PageHost({ view }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const a = document.activeElement;
    if (a && el.contains(a)) a.blur();
    el.innerHTML = view ? view.html : '';
    if (view && view.after) view.after();
  }, [view]);
  return <div ref={ref} style={{ display: 'contents' }} />;
}
