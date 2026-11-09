# PeopleDesk 2.10: Administration, IT and Finance teams

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages. The API creates one table (`asset_types`)
when it starts; if its database user cannot create tables, run `database/migrations/2026-11-v2-10.sql` once as a
MySQL administrator.

## Teams (Administration › Teams: Administration, IT and Finance)

HR (and the group administrator) put people in three teams with **Change** on each team. A team member keeps their
own access as an employee and gains the team's access in their own company. HR can still do everything the teams
do. Each change is recorded in the person's history and in the activity log, and only HR can change it: nobody can
give themselves a team (enforced on the server).

| Team | Can do |
|---|---|
| Administration | Keep the list of administration kinds of asset (ID cards, access cards, locker keys, uniforms…); add them to stock, issue them to employees and take them back |
| IT | Keep the list of IT kinds of asset (laptops, desktops, monitors, mobile phones, SIM cards, TVs, tablets…), add new kinds; add them to stock, issue and take them back |
| Finance | Payroll runs for own employees and contract workers, attendance locks, payslips and bank files, contractor bill payments, TDS certificates, PF, ESI and PT registers, variable pay, the SAP export; check and pay expense claims |

What stays with HR: pay components and statutory rates (Finance can add a missing component such as the expense
reimbursement, not change one), policies, employees' records and salaries, PF and ESI joiners and leavers.

## Assets (Personnel Information › Assets)

- **Kinds of asset** (IT, Administration and HR): each team's list. **Add a kind** for anything new (a TV, a
  tablet, a mobile phone), say whether each one needs a serial number, and untick *In use* to stop adding more.
  **Add common kinds** fills in a starter list. A kind belongs to one team; only that team or HR changes it.
- **Assets register**: each team sees and looks after only its own kinds (HR sees all), with what is issued, in
  stock, not yet confirmed by the employee, and with people who are leaving.
- **Add to stock**: kind, tag, serial number, make and model, cost and date bought.
- **Issue to an employee**: choose the person, then one from stock or a new one entered there and then. Also from
  the **Assets** tab of any employee's profile (**Issue an asset**), where returns can be recorded too.
- The employee sees what they hold and confirms receipt, as before.
- Existing assets are linked to a kind of the same name the first time the team opens the page. Assets of a kind
  that no team has (for example an old *Phone*) stay with HR and their named custodians until HR adds the kind.
- **Enrolment checklists**: *Done by* can now be *The IT team*, *The Administration team* or *The Finance team*.
  New companies start that way; existing checklists named IT, Administration or Finance with nobody named switch to
  the team when HR opens Enrolment checklists. A laptop or ID card allocated during enrolment is linked to its kind.

## Finance

- **Payroll** menu: the payroll runs, TDS certificates, ESI, PF, ESI and PT registers, variable pay and the SAP
  export. **Time Management**: both attendance registers, for the whole company, with **Lock for payroll**.
- Finance sees, for payroll, each employee's salary, bank account, PAN, Aadhaar, UAN, ESI number, date of birth and
  state; not their address, family, background or documents. Finance can change an employee's tax regime (TDS
  pages) and nothing else on the employee record.
- **Expenses › Claims to approve and pay**: every claim in the company once sent, with its receipts. The default
  approval chain for expense claims is now **line manager, then the Finance team** (HR when there is no Finance
  team), so a company that has not changed its chain behaves as before until it names a Finance team. Finance
  approves or rejects at its step and **pays** approved claims, with salary or outside payroll. Nobody approves or
  pays their own claim. Companies with their own chain can add the *Finance team* step under Approval workflows.

## For developers

- `backend/app/policy.py`: `Ctx.teams`, `in_team`, `is_finance_for`; `_team_write` (what a team may save),
  `asset_team`, the finance view of employees (`FINANCE_SEES`) and the team filters in `redact_state`.
  `collections.py`: `assetTypes` (table `asset_types`). `main.py`: Finance may open the receipts of claims.
- `frontend/src/engine/engine.js`, section *PeopleDesk 2.10*: `TEAMS`, `inTeam`, `canPay`, `VIEWS.teams`,
  `VIEWS.assets` (register and kinds), `allocDialog`, `PROFILE_TABS.assets`; the payroll menus use `PAY`, the
  expense chain has a `finance` level, enrolment checklists have team owners.
