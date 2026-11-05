# PeopleDesk 2.7: workforce

Employee background with HR checks, standard lists kept by HR, wedding anniversaries and greetings at sign-in,
employee categories, contractors with their own attendance register and payroll, rotation and shift-change policy,
and attendance locked for payroll.

## Updating the server

Apply the patch or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
No new packages. The API creates two tables (`master_items`, `contractors`) when it starts; if its database user cannot
create tables, run `database/migrations/2026-11-v2-7.sql` once as a MySQL administrator.

Shift-change notice and attendance locks are worked out in the business's time zone: `APP_TZ` in `.env`, default
`Asia/Kolkata`. Set it if your company works in another time zone.

## Employee categories

On the **Job** tab of each profile, **Employee category** is one of:

| Category | Attendance | Overtime | Register and payroll |
|---|---|---|---|
| Salaried: staff | General shift, fixed weekly offs | No | Own employees |
| Salaried: blue collar | Rostered shifts and rotations | Yes | Own employees |
| Salaried: shift worker | Rostered shifts and rotations | Only if ticked | Own employees |
| Contract worker (third party) | Rostered shifts and rotations | Yes | Contract workers |

Choosing a category fills in the attendance group and overtime; both can still be changed. A contract worker must be
attached to a contractor. Existing employees get a category from their current attendance group (shift staff become
blue collar, or shift workers if they were excluded from overtime).

## Background (Profile › Background)

Employees record their **previous employment**, **education**, **awards and achievements** and **references**
(including who referred them for the job), with an optional relieving letter or certificate for each.

- **HR checks each entry**: confirmed, check in progress, does not match, or could not be reached, with how it was
  checked and a note. The employee sees the result, never HR's note.
- If an employee changes an entry HR has checked, the check is removed and HR checks it again. The server enforces
  this: nobody can mark their own background as checked.
- Line managers see their people's experience, education and awards, without previous salary, reasons for leaving or
  references. Other colleagues see none of it.

## Standard lists (Personnel Information › Standard lists)

HR keeps lists of **schools, colleges and institutes**, **qualifications** and **employers**. Employees choose from
them on the Background tab.

- When someone types a name that is not on a list, it waits under **New names to review** (also in Approvals):
  - **Add to list**: it becomes a standard entry (correct the spelling if needed; their profile follows).
  - **Same as…**: it is mapped to an existing entry, and that spelling is matched to it from then on.
  - **Keep off the list**: it stays on their profile as typed, and is not offered to others.
- The employee is told what HR decided.
- **Add the starter list** loads common Indian boards, universities, institutes, qualifications and employers.
  **Import from Excel** takes columns *Name*, *Type*, *City*, *Also matches*.
- Names HR types on a profile go straight onto the list. Only HR can change the lists (enforced on the server).

## Wedding anniversary and greetings

- On the **Personal** tab, married employees add their wedding anniversary and choose whether colleagues see it (day
  and month only; never the year).
- On their birthday, wedding anniversary and work anniversary, people are greeted when they sign in (once that day)
  and on their home page under **For you**. Managers are told about their team's occasions a few days ahead.
- **Personnel Information › Greetings and notifications** (HR): the messages, with {first}, {name}, {company} and
  {years}; whether to greet at sign-in; and the next 30 days of occasions.
- The sign-in message also tells people about shift changes a manager made for them.

## Contractors (Personnel Information › Contractors)

Each contractor has its licence (number, validity, workers allowed), PAN, GSTIN, PF and ESI codes, service charge
(% of wages, or of wages plus employer PF and ESI), GST (on the service charge or on the whole bill), contact and bank
details. The page shows each contractor's billed, paid and outstanding amounts, and the bills still to pay. Approvals
reminds HR of bills to pay and licences expiring within 30 days.

## Two registers and two payrolls

- **Time Management › Attendance register: own employees / contract workers.** The contract register can be filtered by
  contractor.
- **Payroll › Payroll runs: own employees / contract workers.** Each runs separately, month by month.
- A contract payroll run shows a **bill for each contractor**: gross wages, employer PF and ESI, service charge and GST.
  Print the bill, or download the wage register, PF ECR, ESI file, bank file and payslips for one contractor.
- Once the run is locked the bill is final. **Record payment** (amount, date, mode, UTR, paid by, and whether the
  contractor's PF and ESI challans for the month were seen). A bill paid in full is **knocked off**: it shows as
  *Paid: knocked off* and drops out of what is outstanding. Part payments leave the balance outstanding. A run with
  payments cannot be unlocked until they are removed.
- Payslips of contract workers name the contractor they are employed through. Your own PF, ESI and PT registers cover
  your own employees only.

## Attendance locked for payroll

- Locking a payroll run locks that month's attendance for its register (own employees or contract workers).
- HR can lock attendance before locking payroll: **Lock attendance** on the payroll run, or **Lock for payroll** on the
  attendance register (which runs payroll for the month if it has not been run).
- Attendance is locked up to the day before it is locked, or the whole month once the month is over, so people can
  still punch in on the remaining days.
- While locked, nobody (HR included) can change punches, attendance corrections, shift-change requests, leave or the
  roster for those days. **Unlock attendance** on the run (after unlocking the payroll, if it is locked).
- Overtime approvals are not locked: overtime approved after a month is locked is paid in the next payroll, as before.

## Rotation and shift changes

**Time Management › Rotation and shift change policy** (HR):

- **Managers assign rotations**: managers and HR assign a pattern from Shift roster › Assign rotation, as before.
- **The organisation applies them automatically**: shift staff get the pattern the rules give them (by department,
  location and category, with a default), and the roster is kept filled the chosen number of weeks ahead. Days a
  manager changed by hand are left as they are. **Apply rotations now** runs it at once; otherwise it runs when HR or a
  manager opens PeopleDesk.
- **Notice before a shift starts (hours)**: a shift can only be changed this long before it starts. 24 means a shift
  starting Tuesday at 07:00 can be changed until Monday 07:00. New companies start at 24; existing companies start at
  0 (no notice) until HR sets it.
- Whether line managers may change shifts, and whether HR may change them with less notice.

**Time Management › Change team shifts** (managers): choose people, dates, the new shift (or weekly off, or back to
their default shift) and a reason. **Check the changes** shows each day and whether it can change; days that are too
soon or locked are skipped. Each person sees the change on their attendance page and when they next sign in. The
roster grid greys out days that cannot change.

A change the employee asked for themselves, once approved, applies whatever the notice. The server enforces the notice
and the locks for every change, whichever screen it comes from.

## Demo data

The demo data now includes a contractor (Sahyadri Manpower Services) with three warehouse workers on the three-shift
rotation, contract payroll from June (June to August paid and knocked off, September part paid), automatic rotation
with 24 hours' notice for Nilgiri Retail, backgrounds with HR checks (one reference that does not match), two names
waiting for HR, and wedding anniversaries (Anita Rao's is today, so she is greeted when she signs in).

## For developers

- `backend/app/workforce.py`: background checks and what others see of them, standard-list proposals, attendance
  locks (`Guard.check_record`) and shift-change notice (`Guard.check_roster`). `policy.py` and `main.py` call it on
  every save.
- `frontend/src/engine/engine.js`: section *PeopleDesk 2.7: workforce* (`VIEWS.masterdata`, `VIEWS.contractors`,
  `VIEWS.shiftchange`, `VIEWS.shiftpolicy`, `VIEWS.greetings`, `PROFILE_TABS.background`, `contractBills`,
  `autoRotate`, `myNotices`), plus the register and payroll changes. `Home.jsx` shows the notices; `App.jsx` shows the
  greeting after sign-in.
