# PeopleDesk 2.15: previous jobs, cities, photos, expense purposes and reimbursement runs

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages. One new table, `reimbursement_runs`, which
the API creates when it starts (or run `database/migrations/2026-11-v2-15.sql` once as a MySQL administrator if the
API's database user cannot create tables).

Automatic reimbursement runs are made by the API itself, every 15 minutes it checks whether a run is due. Two
settings in `backend/.env` (both optional): `REIMB_AUTO=false` turns this off, `REIMB_TICK_MIN` changes how often it
checks. With several API workers only one makes a run (a database lock), and a run day is never run twice. E-mails to
employees need the SMTP settings already used for approvals.

## Previous jobs: reason for leaving and city

On **Add previous job** (an employee's Background tab), on the candidate dialog's **Employment history** and on the
form a candidate fills in through their link:

- **Reason for leaving** is a drop-down of standard reasons: better role or career growth, higher pay, relocation,
  contract or project ended, company closed, downsized or layoff, higher studies, family or personal reasons, health
  reasons, better work-life balance, retirement, asked to leave by the employer, still working there. **Others**
  opens a box to type one.
- **City** is a drop-down of the company's locations and cities (below), with **Others**.
- Jobs entered before keep what was typed; it shows under Others.

## The cities of India in the location list

**Departments and grades** has a new **Cities** card under Locations.

- **Add the starter list** adds 500 cities and towns across every state and union territory.
- **Import from Excel** takes any list with the headings **City**, **State** and **Metro** (Yes or No). The file
  `India-cities.xlsx` delivered with this version is the starter list in that format: add more towns to it and import
  it again. A city already on the list is skipped. State names are matched loosely (Orissa, Pondicherry and NCT of
  Delhi are understood); a city whose state is not recognised is added without a state, and you are told which.
- **Download template**, **Download the list**, **Add a city**, search, and **Delete** for a city nobody uses.
- Cities are kept with the locations but are **not offered as places people work**: the Location drop-downs on an
  employee, a requisition and an offer still show only the offices. They are offered wherever a city is asked for: a
  previous job, a candidate's current location. A candidate's city with a state now counts towards the profile fit
  (same state as the job).
- The **Metro** flag is set for Delhi, New Delhi, Mumbai, Kolkata and Chennai. Check it against the income-tax rules
  in force before relying on it for the HRA exemption.
- The list of states now includes Sikkim, the north-eastern states, Ladakh, Lakshadweep, the Andaman and Nicobar
  Islands and Dadra and Nagar Haveli and Daman and Diu.

## Profile photos

- **Add photo** under the initials on **My profile** (and on anyone's profile for HR). JPEG, PNG or WebP up to 8 MB;
  it is cropped square and made smaller in the browser before it is sent. **Change photo** and **Remove**.
- The photo shows on the **organisation chart**, in the people list, on the profile and next to your name at the top.
- Everyone in the company can see the photos. The server accepts a photo only if it is an image uploaded by the
  person setting it, or by HR, so no other file can be shown this way.

## Expense claims

### Purpose

- **Expense categories, purposes and limits** has a new list, **Purposes of claims**. Nine are added to start with
  (customer visit, sales and business development, project or site work, training or conference, internal meeting
  or review, recruitment, relocation, office purchase, other); add, edit, order or switch off as you like.
- Each purpose can **ask for a reference** (for example Customer or Project), list the **supporting documents** to
  attach and make them **required**, have a **limit for the whole claim**, and carry a cost centre or GL code.
- **New expense claim** starts with **Purpose**, a drop-down, then the reference if the purpose asks for one, then
  **Details** (what was in the purpose box before).

### Supporting documents

- **Attach documents** on the claim takes several files at once (photos or PDFs, up to 10 MB each): approvals,
  invitations, visit reports, tickets. Each expense line keeps its own receipt as before.
- A claim cannot be sent without documents when its purpose requires them.
- Approvers and Finance see the documents on the claim, and a warning listing every problem: lines over their
  limits, missing receipts, the purpose's limit exceeded, documents missing.

### Approval steps from the claim

In **Approval workflows › Expense claims › Change**, each step now has **Only for some claims**:

- **Purposes**: the step applies only to claims with one of these purposes;
- **With an expense of the category**: only to claims with a line in one of these categories;
- **Only when** a line is over its limit, the claim is over the purpose's limit, or a receipt or supporting document
  is missing.

They combine with **Only from ₹**. For example: line manager, then Finance, then the manager's manager only for
office purchases over the limit. The steps are fixed when the claim is sent.

## Reimbursement runs

### The cycle (Expenses › Reimbursement cycle, HR)

- **Pay approved claims in reimbursement runs on this cycle**.
- **Paid**: with the next salary (a reimbursement that is not taxed, pay component 1900, in the first salary month
  not locked yet), or by a **separate bank transfer**.
- **How often**: monthly on a day you choose (29, 30 or 31 meaning the last day), fortnightly (the 15th and the last
  day), or weekly on a day of the week.
- **Cut-off**: claims approved fewer than this many days before the run day wait for the next run.
- **Make the run automatically on the run day**, and **e-mail each employee what is paid**.
- The next three run days are shown. Run days before the cycle was set up are not made up.

### Runs (Expenses › Reimbursement runs, Finance and HR)

- Approved claims waiting to be paid, the next run, what is waiting for a bank transfer, and what was paid this year.
- **Run now** pays the ticked claims at once (Finance cannot include their own claim; HR or another member of
  Finance pays it).
- Automatic runs need nobody to sign in.
- Each run lists its claims by employee. **With salary**: the claims are paid and each person's pay gets one
  Expense reimbursement amount for the month. **Bank transfer**: **Download bank advice** (beneficiary, account,
  IFSC, amount, narration; anyone without a bank account is flagged), make the transfer, then **Record the bank
  transfer** with the UTR and date: every claim in the run is paid.
- The claim shows its run and, while waiting, the date of the next run. **Pay now, outside the cycle** remains for
  exceptions.

## For administrators

- New: `backend/app/reimb.py` (the cycle, runs, automatic runs), endpoints `POST /api/reimb/run` and
  `POST /api/reimb/paid` (Finance or HR of the company), table `reimbursement_runs` (HR and Finance see it).
- Purposes are expense categories with `kind: "purpose"`; cities are locations with `kind: "city"`.
- Claims: `purposeId`, `purpose`, `ref`, `details`, `docs`, `issues`, `reimbRunId`, `reimbRunNo`. Workflow steps:
  `purposes`, `cats`, `onIssues`. Companies: `reimb`. Employees: `photoId`.
- Photos are served with a one-hour browser cache (a new photo is a new file); other files stay uncached.
