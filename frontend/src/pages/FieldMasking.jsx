import { useEffect, useState } from 'react';
import { api } from '../api.js';

/* Administration › Personal field masking.
   Which employee personal/statutory fields (PAN, Aadhaar, bank details, address, family, etc.)
   show masked by default on the profile page, until someone verifies with an e-mailed code. See
   backend/app/security_fields.py -- toggling here takes effect immediately, no redeploy. */
const API = '/api/security/admin/masked-fields';

export default function FieldMasking() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(null);

  const load = () => api.get(API).then((d) => setRows(d)).catch((x) => setErr(x.message));
  useEffect(() => { load(); }, []);

  const toggle = async (row) => {
    setBusy(row.field);
    setErr('');
    try {
      await api.post(`${API}`, { field: row.field, masked: !row.masked });
      setRows((list) => list.map((r) => (r.field === row.field ? { ...r, masked: !r.masked, updatedAt: new Date().toISOString() } : r)));
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card">
      <h2>Personal field masking</h2>
      <p className="sub">Which employee fields show masked by default on the profile page, until someone verifies with an e-mailed code. Turning one off removes the mask for everyone immediately.</p>
      {err && <div className="note bad">{err}</div>}
      {!rows ? <div className="empty">Loading…</div> : (
        <div className="scroll"><table className="t">
          <thead><tr><th>Field</th><th>Masked</th><th>Last changed</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.field}>
              <td>{r.label}</td>
              <td><label className="chk"><input type="checkbox" checked={r.masked} disabled={busy === r.field} onChange={() => toggle(r)} /> Masked</label></td>
              <td className="fine">{r.updatedAt ? `${new Date(r.updatedAt).toLocaleString()}${r.updatedBy ? ` · ${r.updatedBy}` : ''}` : '—'}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}
