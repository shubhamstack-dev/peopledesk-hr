# PeopleDesk 2.4: statutory registers, PF and ESI exits, salary revision planning

## Updating the server

Apply the patch or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. No new packages. The API creates three new tables (`comp_cycles`, `comp_budgets`, `comp_recommendations`) when it starts. If its database user cannot create tables, run `database/migrations/2026-11-v2-4.sql` once as a MySQL administrator. The registers need no new tables; they are built from the payroll runs you already have.

## PF, ESI and professional tax registers (Payroll)

Four new menu items: **PF register**, **ESI register**, **Professional tax register** and **PF and ESI joiners and leavers**.

- **Period:** choose any range of months with *From* and *To*, or **One month** or **Financial year**. Up to 36 months.
- **Every employee on the rolls in the period is listed**, leavers included. Those without PF, ESI or PT appear under *Not contributing*, *Not covered* or *Not liable* with the reason (excluded from PF, wages above the ESI ceiling at the start of the contribution period, gross below the PT slab, payroll not run, joined later).
- **PF register:** challan by month split into A/c 1 (employee share, VPF and employer EPF), A/c 2 (admin), A/c 10 (EPS) and A/c 21 (EDLI) with the due date; for one month, each member's gross, EPF, EPS and EDLI wages, every share and NCP days, as in the ECR; for a longer period, member totals (as in the annual member statement).
- **ESI register:** contribution by month with due dates; IP number, dispensary, days paid, ESI wages and both shares per insured person; leavers with the ESIC reason code used in their last month.
- **Professional tax register:** employees by state, month and salary slab with the tax deducted (what the state returns ask for), and each employee's deduction month by month.
- **Excel** downloads a workbook with a summary sheet, a sheet with every employee for every month, and per-employee totals. **Print** prints the summary and totals with the company's name and PF or ESI code.
- Draft months are marked. Lock payroll before filing.

## People leaving: PF and ESI exit

- On the exit page, HR now has **PF and ESI exit**. PeopleDesk suggests the EPFO reason (C cessation, S superannuation at 58 or more, R retirement, D death, P permanent disablement) and the ESIC reason code (2 left service, 3 retired, 5 expired, 10 retrenchment, 4 out of coverage) from the type of exit. Record the PF date of exit (normally the last working day) and the dates you marked the exit on the EPFO and ESIC portals.
- PF applies when the employee is a PF member; ESI when they were covered in the six months before leaving. Otherwise it shows *Not applicable*.
- When both are recorded, the HR clearance item *PF and ESI exit date updated* is ticked.
- **Joiners and leavers** lists everyone leaving or who left in the period with the PF and ESI status, settlement status and a **Record** button; and new joiners without a UAN or IP number.
- After the last working day, leavers not yet updated on the portals appear in HR's **Approvals**. Completing an exit without it asks for confirmation.
- The **ESIC monthly upload file** now uses the recorded reason code with the last working day for a leaver (it used to put 1 only when no days were paid).
- Only HR can record this; the server refuses it from anyone else.

## Salary revision planning (Compensation)

### HR sets up the cycle

1. **Compensation › Salary revision planning › New cycle.** Give the name, the date new salaries take effect (default next 1 April), the **total increment budget** (for example ₹10,00,000: the increase in annual fixed CTC across everyone), the date plans are due, who is included (joined on or before a date; probation optional), the reason written on the salary history, a flag for increases above a percentage, and the **guideline increase for each performance rating**.
2. **Give budgets to managers.** At the organisation level, tick the managers who get a budget and the amount. PeopleDesk suggests a split in proportion to each team's current CTC. Usually you give budgets to the heads directly under the top of the company. You can do this before or after opening planning.
3. **Open planning.** Everyone eligible is added with their current salary as it stands the day before the effective date. Managers with a budget are e-mailed (if e-mail is set up) and see it in Approvals. Employees do not see the plan.

### Managers plan

- A manager sees **Your budget**: what they have, what they handed down, the increases they decided and what is left.
- **Give budgets to managers** hands part of it to managers below them, who do the same in turn. Each budget covers that manager's team.
- **Who decides each increase:** the nearest manager above the person who holds a budget. A manager's own increase is decided by the budget holder above them, never by themselves. People with no budget holder above them (such as the head of the company) are decided by HR from the organisation budget.
- Enter each increase as a **percentage or the new CTC**; the totals update as you type. **Fill from guidelines** sets every increase from the last rating and scales them down if they would exceed the budget. Notes per person are kept.
- People **serving notice or gone** drop out of the increase automatically and free their budget. HR can also **take someone out** or **add people** (for example someone who finished probation).
- **Submit plan** when finished. A manager can submit only after the managers they gave budgets to have submitted, and not over budget. A plan can be taken back until the first approval.

### Discussion and approval

- A submitted plan is approved **in turn by every budget holder above, then HR**. Each sees it in Approvals and by e-mail, can open the full plan, and **approves or sends it back** with a comment. A plan sent back goes to its manager to change and resubmit, and starts the approvals again.
- Every plan has a **discussion**: comments about the whole plan or one person, seen by the manager, the managers above and HR, with e-mail to them.
- HR sees all budgets as a tree with what each has used and who it is waiting for, can **approve every plan waiting for HR** at once, and can **reopen** any plan.

### Approving and applying

- When every plan is approved, HR **approves the cycle**, then **applies it to salaries**: each new CTC is added to the salary history from the effective date, so payroll pays it from that month (arrears are added automatically if that month is already locked). Variable pay targets are unchanged. People leaving are skipped. **Undo** removes them again while no payroll from that month is locked.
- **Revision letters** creates a numbered letter for everyone revised from a Word template (Administration › Document templates) and adds it to their profile, where they can download it. The letter is dated the effective date, so `previous_ctc`, `ctc_annual`, `increment_amount`, `increment_pct` and the salary breakup come from the revision.
- **Excel** downloads the whole plan and the budgets.

### Who can see and change what (enforced on the server)

- Only HR creates, opens, approves and applies cycles, and sees the organisation's total budget.
- A budget is seen by its holder, the managers above them and HR. A person's recommendation is seen by the managers above them and HR, **never by the person themselves**.
- Only the manager who decides a person's increase can change it, only the proposed salary and the note, never below the current salary, and only while their plan is not submitted.
- Only the manager who handed down a budget can change its amount; nobody can hand down or (once submitted) spend more than their budget. The server checks every budget in the cycle after each save.
- Approvers are fixed (the budget holders above, then HR) and decide only their own step, in order. Comments cannot be edited or removed.

## For developers

- `backend/app/comp.py`: the rules (who decides, budget use, permitted changes, what each person may read). `policy.py` calls it; `main.py` checks budgets after each save and sends the e-mails (`/api/comp/notify`).
- `backend/app/collections.py`: `compCycles`, `compBudgets`, `compRecs`. In `frontend/src/engine/sync.js` they are listed in that order so budgets are saved before recommendations.
- `frontend/src/engine/engine.js`: section *PeopleDesk 2.4: statutory registers* (`VIEWS.statreg`, `statExitOf`, `ACT.statExit`) and section *compensation planning* (`VIEWS.compplan`).
- Statutory reason codes follow the EPFO and ESIC portals as of 2026; check them against the portals before filing.
