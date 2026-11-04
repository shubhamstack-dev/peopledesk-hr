/* Talks to the Python API. The session is an http-only cookie; every request carries
   the x-peopledesk header the server requires for writes. */
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

/* The company (tenant) this browser signs in to: its code is kept here and sent before signing in.
   A link like https://…/?org=acme sets it. */
const ORG_KEY = 'pd-org';
export function getOrg() { try { return localStorage.getItem(ORG_KEY) || ''; } catch { return ''; } }
export function setOrg(v) { try { if (v) localStorage.setItem(ORG_KEY, v.trim().toLowerCase()); else localStorage.removeItem(ORG_KEY); } catch { /* private mode */ } }
try { const q = new URLSearchParams(window.location.search).get('org'); if (q) setOrg(q); } catch { /* ignore */ }

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: { 'x-peopledesk': '1', 'x-pd-org': getOrg(), ...(body !== undefined ? { 'content-type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, 'The server cannot be reached. Check your connection and try again.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : `The server returned ${res.status}`;
    throw new ApiError(res.status, msg);
  }
  return data;
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b = {}) => request('POST', p, b),
};
