# PeopleDesk 2.17: candidates sign in to fill in their form

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages. One new table, `candidate_credentials`
(candidates' passwords), is created when the API starts; nothing else changes in the database.

## What changes for the candidate

HR's link no longer opens the form by itself. The candidate form is filled in by the candidate, signed in as a
candidate.

- **First visit.** The link opens **Create your candidate sign-in**. The candidate signs in with the e-mail address
  HR has for them (or their mobile number, when HR has no e-mail), shown on the page, and chooses a password of
  their own (at least 10 characters). They are then signed in and the form opens.
- **Later visits.** The same link asks for their password. Or, from the sign-in page, **Candidate? Sign in to fill
  in your details**, then their e-mail address (or mobile number) and password. This works even where password
  sign-in is switched off for staff.
- Signed in, the candidate fills in the form as before: save and finish later, attach the CV, send. The page shows
  **Signed in as a candidate**, with **Change password** and **Sign out**.
- **Forgotten password.** A link sets a password once. HR presses **Send the link again**; the new link offers
  **Forgot your password? Set a new one with this link**.
- After the form is sent, the candidate can still sign in to see it (read only). When HR asks for changes, they sign
  in again to make them. Once they join and are converted into an employee, the candidate sign-in stops; they sign
  in as an employee.

## Only candidates fill in the form

- The form is read and saved only with a candidate's own session. Someone who merely has the link sees the
  candidate's name, the company and the job, and the sign-in box: none of the details entered (PAN, Aadhaar, bank
  account and the rest).
- An employee cannot fill it in. If the link is opened in a browser where an employee (or a contractor) is signed
  in, the page says **This form is for the candidate** and offers to sign out and continue as the candidate. HR
  signed in to PeopleDesk cannot open or save a candidate's form either.
- HR cannot send the candidate link to an active employee's e-mail address, and a candidate sign-in cannot be made
  with one. Give the candidate's own address.
- A candidate session gets nothing of the main app (employees, payroll, recruitment): only their own form.

## What changes for HR

- **Ask the candidate to fill in their details** and **Send the link again** work as before. The candidate needs an
  e-mail address or a mobile number on their record to be sent a link.
- The link dialog and the e-mail tell the candidate to create their sign-in the first time and sign in afterwards.
- The candidate's **Candidate's details** card shows whether they have created their sign-in yet, and when.
- Sign-ins, new passwords and password changes are in the activity log under recruitment.

## For developers

- `backend/app/candform.py`: `candidate_credentials` (`CRED_DDL`), session subject `cd:` + candidate id
  (`SESSION_PREFIX`), `candidates_for_login`, `session_problem`, `link_view`, `account_problem`,
  `is_employee_login`, `note_account` (`form.accountAt`, kept by `merge_from_app`). The link token is unchanged; its
  nonce also records which link set the password (`set_with`), so each link sets one password.
- `backend/app/main.py`: `POST /api/apply/open` now returns only the link page (`hasAccount`, `canSetPassword`,
  `signedIn`); `POST /api/apply/save` is removed. New: `POST /api/apply/account` (create the sign-in, or a new
  password, with a link), `GET` and `POST /api/candidate/form`, `POST /api/candidate/password`, all needing a
  candidate session (`current_candidate`). `POST /api/auth/login` signs candidates in (a candidate whose mobile
  number is also an employee's signs in with their own password); `GET /api/session` returns `kind: candidate`.
  `POST /api/candidate-form/link` refuses an employee's e-mail address and a candidate with no e-mail or mobile.
- `backend/app/migrate.py` creates `candidate_credentials`.
- `frontend/src/pages/CandidateForm.jsx`: the gate (create a sign-in, sign in, set a new password, or sign out an
  employee) and the form, in `link` or `session` mode. `App.jsx`: phase `candidate`. `Login.jsx`: **Candidate? Sign
  in**. `engine.js`: the link dialog, the bulk-send note and the candidate card.
- Tests: `backend/tests/test_candidate_signin.py` (needs a MySQL or MariaDB database, which it empties).
