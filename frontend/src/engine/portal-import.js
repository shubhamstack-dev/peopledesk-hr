/* PeopleDesk 2.18: reading candidate lists exported from job portals (Naukri, LinkedIn, Indeed, foundit, Shine,
   Instahyre, apna and others). Every portal names its columns differently and writes experience, salary and
   notice period as text ("5 Yrs 3 Months", "12.5 Lacs", "1 Month"), so the columns are matched by name and
   the values turned into numbers here. Pure functions: no screen, no state. */

export const PORTALS = ['Naukri', 'LinkedIn', 'Indeed', 'foundit (Monster)', 'Shine', 'Instahyre', 'apna', 'iimjobs / hirist', 'Other portal'];

/* field -> [label, names the portals use, words that rule a column out] */
export const PI_FIELDS = {
  name: ['Full name', ['name', 'candidate name', 'full name', 'applicant name', 'candidate', 'applicant'], ['first', 'last', 'company', 'employer', 'father', 'institute', 'college']],
  firstName: ['First name', ['first name', 'firstname', 'given name'], []],
  lastName: ['Last name', ['last name', 'lastname', 'surname', 'family name'], []],
  email: ['E-mail', ['email', 'e mail', 'email id', 'email address', 'emailid', 'mail id'], ['alternate', 'secondary']],
  phone: ['Mobile', ['mobile', 'phone', 'mobile no', 'mobile number', 'phone number', 'contact number', 'contact no', 'contact', 'cell'], ['alternate', 'landline', 'secondary', 'person']],
  expYears: ['Experience (years)', ['total experience', 'experience', 'work experience', 'total exp', 'exp', 'years of experience', 'overall experience'], ['relevant', 'month', 'company']],
  currentCompany: ['Current employer', ['current company', 'current employer', 'current organisation', 'current organization', 'company', 'employer', 'company name'], ['previous', 'past', 'designation']],
  currentTitle: ['Current designation', ['current designation', 'designation', 'current title', 'job title', 'title', 'current role', 'role', 'headline'], ['previous', 'past', 'applied', 'job applied']],
  location: ['Current location', ['current location', 'location', 'city', 'current city'], ['preferred', 'job location']],
  currentCtc: ['Current CTC', ['current ctc', 'ctc', 'current salary', 'annual salary', 'salary', 'current annual salary', 'present ctc'], ['expected', 'preferred']],
  expectedCtc: ['Expected CTC', ['expected ctc', 'expected salary', 'expected annual salary', 'salary expectation'], []],
  noticeDays: ['Notice period', ['notice period', 'notice', 'availability to join', 'joining availability'], []],
  skills: ['Skills', ['key skills', 'skills', 'skill set', 'skillset', 'it skills'], []],
  education: ['Education', ['highest qualification', 'education', 'qualification', 'ug degree', 'degree', 'pg degree'], ['institute', 'college', 'university', 'year']],
  gender: ['Gender', ['gender', 'sex'], []],
  profileUrl: ['Profile or CV link', ['profile link', 'profile url', 'linkedin profile', 'linkedin', 'resume link', 'cv link', 'resume url', 'url'], []],
  applied: ['Applied on', ['applied on', 'date applied', 'application date', 'applied date'], []],
};

const norm = (s) => String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/* how well a column heading names a field: 3 exact, 2 starts with, 1 contains, 0 not at all */
function headScore(head, key) {
  const h = norm(head); if (!h) return 0;
  const [, syns, excl] = PI_FIELDS[key];
  if (excl.some((x) => h.includes(x))) return 0;
  let best = 0;
  syns.forEach((s) => { const v = h === s ? 3 : h.startsWith(s + ' ') || h.endsWith(' ' + s) ? 2 : (` ${h} `).includes(` ${s} `) ? 1 : 0; if (v > best) best = v; });
  return best;
}

/* the heading row: the first of the top 15 rows that names at least three fields (exports often start with a title) */
export function findHeaderRow(rows) {
  for (let i = 0; i < Math.min(15, rows.length); i++) {
    const hits = new Set();
    (rows[i] || []).forEach((c) => Object.keys(PI_FIELDS).forEach((k) => { if (headScore(c, k)) hits.add(k); }));
    if (hits.size >= 3) return i;
  }
  return 0;
}

/* field -> column index (or -1), each column used once, best matches first */
export function autoMap(headers) {
  const pairs = [];
  headers.forEach((h, i) => Object.keys(PI_FIELDS).forEach((k) => { const s = headScore(h, k); if (s) pairs.push({ k, i, s }); }));
  pairs.sort((a, b) => b.s - a.s || a.i - b.i);
  const map = Object.fromEntries(Object.keys(PI_FIELDS).map((k) => [k, -1])); const used = new Set();
  pairs.forEach(({ k, i }) => { if (map[k] === -1 && !used.has(i)) { map[k] = i; used.add(i); } });
  return map;
}

const nums = (s) => (String(s).replace(/,/g, '').match(/\d+(\.\d+)?/g) || []).map(Number);

/* "5 Yrs 3 Months", "5y 3m", "5.5 years", "60 months", "Fresher", "5" -> years */
export function parseExp(v) {
  const s = String(v ?? '').toLowerCase().trim(); if (!s) return '';
  if (/fresher|no experience/.test(s)) return 0;
  const y = s.match(/(\d+(?:\.\d+)?)\s*(?:\+\s*)?(?:years?|yrs?|y\b)/), m = s.match(/(\d+(?:\.\d+)?)\s*(?:months?|mons?|mths?|m\b)/);
  if (y || m) return Math.round(((y ? +y[1] : 0) + (m ? +m[1] / 12 : 0)) * 10) / 10;
  const n = nums(s); return n.length ? n[0] : '';
}

/* rupees a year from "12 Lacs", "12.5 LPA", "12 Lacs 50 Thousand", "INR 12,00,000", "1.2 Cr", "50,000 per month", "12" (lakhs) */
export function parseCtc(v) {
  let s = String(v ?? '').toLowerCase().replace(/₹|inr|rs\.?/g, ' ').trim(); if (!s || /not disclosed|confidential/.test(s)) return '';
  const monthly = /per month|p\.?\s?m\b|monthly|\/\s?month/.test(s);
  s = s.replace(/\s+to\s+|\s*-\s*/g, ' - ').split(' - ')[0];                 // a range: the lower figure
  let n = 0; let unit = false;
  const cr = s.match(/(\d+(?:\.\d+)?)\s*(?:crores?|cr)\b/); const lk = s.match(/(\d+(?:\.\d+)?)\s*(?:lakhs?|lacs?|lpa|l)\b/); const th = s.match(/(\d+(?:\.\d+)?)\s*(?:thousands?|k)\b/);
  if (cr) { n += +cr[1] * 1e7; unit = true; } if (lk) { n += +lk[1] * 1e5; unit = true; } if (th) { n += +th[1] * 1e3; unit = true; }
  if (!unit) { const x = nums(s); if (!x.length) return ''; n = x[0]; if (n > 0 && n < 200 && !monthly) n *= 1e5; }
  if (monthly) n *= 12;
  return Math.round(n);
}

/* days from "Immediate", "15 Days or less", "1 Month", "2 Months", "More than 3 Months", "Serving notice period", "60" */
export function parseNotice(v) {
  const s = String(v ?? '').toLowerCase().trim(); if (!s) return '';
  if (/immediate|serving|currently not|not working|available now/.test(s)) return 0;
  const x = nums(s); if (!x.length) return '';
  const n = x[x.length - 1];
  const days = /month/.test(s) ? n * 30 : /week/.test(s) ? n * 7 : n;
  return /more than|over|\+/.test(s) ? days + 30 : days;
}

/* an Indian mobile as 10 digits (+91, 0 or 91 in front taken off); anything else kept as written */
export function parsePhone(v) {
  const s = String(v ?? '').split(/[,/;]| or /)[0].trim(); const d = s.replace(/\D/g, '');
  if (d.length === 12 && d.startsWith('91')) return d.slice(2);
  if (d.length === 11 && d.startsWith('0')) return d.slice(1);
  return d.length >= 10 ? d : s;
}

const GENDER = { m: 'M', male: 'M', f: 'F', female: 'F', o: 'O', other: 'O', others: 'O' };

/* one row of the sheet -> the candidate's fields (blank where the column is not mapped or empty) */
export function rowToCand(row, map) {
  const get = (k) => (map[k] >= 0 ? String(row[map[k]] ?? '').trim() : '');
  let name = get('name').replace(/\s+/g, ' ');
  if (!name) name = `${get('firstName')} ${get('lastName')}`.replace(/\s+/g, ' ').trim();
  const email = (get('email').match(/[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+/) || [''])[0].toLowerCase();
  return { name, email, phone: parsePhone(get('phone')), expYears: parseExp(get('expYears')), currentCompany: get('currentCompany'), currentTitle: get('currentTitle'),
    location: get('location').split(/[,/(]/)[0].trim(), currentCtc: parseCtc(get('currentCtc')), expectedCtc: parseCtc(get('expectedCtc')), noticeDays: parseNotice(get('noticeDays')),
    skills: get('skills').replace(/\s*[|;]\s*/g, ', '), education: get('education'), gender: GENDER[norm(get('gender'))] || '', profileUrl: get('profileUrl'), applied: get('applied') };
}

const last10 = (p) => String(p || '').replace(/\D/g, '').slice(-10);
/* the candidate a CV file belongs to: by e-mail or mobile in the file name, else by every part of the name.
   Returns the index in cands, or -1 when none or more than one fit. */
export function matchCvFile(fileName, cands) {
  const base = String(fileName || '').toLowerCase().replace(/\.[a-z0-9]+$/, '');
  const flat = base.replace(/[^a-z]/g, ''); const digits = base.replace(/\D/g, '');
  const hit = (pred) => { const ix = cands.map((c, i) => (pred(c) ? i : -1)).filter((i) => i >= 0); return ix.length === 1 ? ix[0] : ix.length > 1 ? -2 : -1; };
  let i = hit((c) => c.email && base.includes(c.email.toLowerCase())); if (i !== -1) return i < 0 ? -1 : i;
  i = hit((c) => last10(c.phone).length === 10 && digits.includes(last10(c.phone))); if (i !== -1) return i < 0 ? -1 : i;
  i = hit((c) => { const parts = String(c.name || '').toLowerCase().split(/[^a-z]+/).filter((p) => p.length > 1); return parts.length > 0 && (flat.includes(parts.join('')) || parts.every((p) => flat.includes(p))); });
  return i < 0 ? -1 : i;
}
