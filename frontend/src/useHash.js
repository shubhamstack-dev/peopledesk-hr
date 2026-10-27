import { useEffect, useState } from 'react';

/* The app uses hash addresses (#/leave, #/profile/abc?tab=bank) like the original, so links
   written inside the feature screens keep working. */
export function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return hash;
}
