# PeopleDesk 2.9: contractor portal and contract workers' access

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages. The API creates one table
(`contractor_credentials`, the passwords of contractors' portal users) when it starts; if its database user cannot
create tables, run `database/migrations/2026-11-v2-9.sql` once as a MySQL administrator.

Set `APP_URL` in `.env` (for example `https://peopledesk.example.com`): access links are made with it. Without it,
links use the address the request came in on. With SMTP set up, links are also sent by e-mail.

## The contractor portal

Contractors (the agencies that supply contract workers) now add their own workers.

**Set up (HR), under Personnel Information › Contractors › Contractor portal: who signs in**

- **Add portal user**: a person at the contractor, with an e-mail address or mobile number (or both). Saving shows
  an **access link** to send them: by e-mail, WhatsApp or text message. With it they set a password.
- **May sign in** off, or the contractor made inactive, stops them at once, even if signed in.
- A contractor can have several portal users. Every e-mail address and mobile number belongs to one person only.

**In the portal (the contractor's portal user)**

- They sign in on the usual sign-in page with their e-mail or mobile number and password, and see only their own
  contractor: no menu of the company, no staff, pay or bills.
- **Add worker**: name, gender, date of birth, mobile number or e-mail, date of joining, and department,
  designation, location and shift from the company's lists. The worker gets the next employee number, category
  *Contract worker*, and is attached to this contractor. The access link to send them is shown straight away.
- Refused: a worker under 18 on joining, a mobile number or e-mail already in PeopleDesk, more workers than the
  licence allows, or any worker after the labour licence has ended.
- **Correct** a worker's details until the worker has signed in; after that the worker keeps them.
- For each worker: whether they have signed in, and which parts of their profile they have filled in (personal,
  family, education, Aadhaar/PAN/UAN, bank). Yes or no only: the contractor does not see the numbers.

**One contractor per worker.** A worker stays with the contractor that added them. Another contractor cannot add
someone already engaged through a contractor; they are told to ask HR to end that engagement first. Only HR can move
a worker to another contractor (Job tab), and the worker cannot change it.

## Contract workers

- They set their password with the access link and sign in with their **mobile number or e-mail**. This works even
  where password sign-in is switched off for staff, as contract workers rarely have a company Google or Microsoft
  account. If they forget the password, HR gives a new link (**Access link** on the profile). A contractor can send a
  link only until the worker has signed in.
- On **Home**, *Complete your details* lists what is left: personal details, family, education and previous jobs,
  Aadhaar/PAN/UAN (checked by HR, as for staff) and the bank account for wages.
- They have the rest of PeopleDesk: attendance and punching, leave, shifts, performance, training, feedback.
- They do **not** have payslips, salary, awards, tax declarations, expense claims or leave encashment. The menus,
  profile tabs and the Documents tab leave these out, and the server removes them from what it sends and refuses
  any attempt to save them.

## HR

- **Workers added by contractors** on the Contractors page: who added whom and when, and what HR still has to do:
  set wages (Salary tab) for the contract payroll and who they report to. The menu shows how many are left.
- **Access link** on every active employee's profile: for anyone without Google or Microsoft sign-in, and for a
  forgotten password.

## How access links work

A link is signed by the server, works for 7 days, and only once: when a password is set with it, every earlier link
for that person stops working. Anyone holding the link can set the password, so send it only to the person.

## For developers

- `backend/app/portal.py`: portal users and their passwords, access links, what a portal user sees, adding and
  correcting workers, and the check on contractor records HR saves. `main.py`: `/api/session`, `/api/auth/invite/*`,
  `/api/access-link`, `/api/contractor/*`; sign-in by mobile number. A portal session's subject is `cu:<user id>`, so
  every main-app endpoint (`current_user`) refuses it.
- `backend/app/policy.py`: `Ctx.is_contract_worker`, `_contract_worker_view` and the refusals for contract workers.
- `frontend/src/pages/ContractorPortal.jsx`, `Welcome.jsx` (the access link page); `App.jsx` routes to them.
  `engine.js`, section *PeopleDesk 2.9*: `cwSelf`, `myDetailsChecklist`, `portalCard`, `conAddedCard`, `accessLink`.
- A backup does not include portal passwords: after a restore, give portal users new access links.
