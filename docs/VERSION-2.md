# PeopleDesk version 2: upgrade and user guide

Version 2 adds the reporting structure with dotted lines, moving people on the organisation chart, approval workflows, a company-level choice between shifts and time management, goal templates, fixed and variable pay, leave carry forward and encashment, expense claims, employee enrolment with department checklists and an assets register, promotions and progression, and activity logs.

## 1. Upgrading your server

Nothing in your `.env` changes. On the server, in the project folder:

```bash
git pull                      # or: git am 0001-PeopleDesk-version-2.patch
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker logs pd-app --tail 50  # should show "Application startup complete", no "migration failed"
```

What happens:

- **Database.** When the API starts, it creates the 8 new tables and adds three columns to `audit_log`. Existing data is not touched, and running it again does nothing. Your Docker MySQL user owns the database, so it has the rights it needs. If you run MySQL elsewhere with a restricted user, run `database/migrations/2026-10-v2.sql` once as an administrator instead.
- **Uploads.** Expense receipts are stored in a new Docker volume, `pd_uploads`. It survives rebuilds. Back it up along with MySQL:
  - `docker run --rm -v peopledesk_pd_uploads:/u -v $PWD:/b alpine tar czf /b/uploads.tgz -C /u .`
- **Defaults.** The default expense categories and enrolment checklists are created for a company the first time an HR administrator opens:
  - Expenses → Expense categories and limits
  - Personnel Information → Enrolment checklists

  Review them there.
- **Engine source.** `frontend/src/engine/engine.js` is now edited directly. `npm run engine` refuses to overwrite it, because the original HTML does not contain these features.

After upgrading, set up in this order:

1. **Departments, designations and grades.** Give each grade a level, a pay band and the months before promotion. Name department heads. Optionally give each designation its usual grade.
2. **Companies.** Choose the working pattern (see 5). This can also be done under Time Management → Shifts or time management.
3. **Administration → Approval workflows.**
4. **Personnel Information → Enrolment checklists.** Name the people who handle IT, Administration and Finance.
5. **Expenses → Expense categories and limits.**
6. **Performance Management → Goal templates by designation.**
7. **Leave Management → Leave policies.** Set the carry-forward lapse and the encashment rules per leave type.

## 2. Organisation hierarchy and reporting (requirements 1, 3)

- **One line manager, any number of dotted-line managers.**
  - The line manager approves leave, attendance and goals, as before.
  - Dotted-line managers see the person in their team views and profile. They can be approvers in workflows that include the dotted-line step.
- **Personnel Information → Reporting structure.** Lists everyone with their line and dotted-line managers, direct and dotted reports, and the date the current arrangement started. HR can change it there. The page also shows recent changes and changes scheduled for later.
- **Profile → Reporting tab.** Shows the current lines and the full history with effective dates.
- **Personnel action → Reporting lines.** The same change from a profile.

## 3. Moving people on the organisation chart (requirements 2, 8)

- HR drags a person's card onto their new manager. The ⇄ button on each card does the same on touch screens.
- The move dialog asks for:
  - **Line or dotted line.** Replace the line manager, or add a dotted-line manager.
  - **Effective date.** A future date is applied automatically on that day. Until then it shows under Scheduled.
  - **Department.** Keep it, or move to the new manager's department.
  - **Their team.** Moves with them, or stays and reports to their old manager.
- Dated records are written automatically: the reporting history, an entry in the employee's History, and the activity log.
- Someone can't be moved under a person in their own team. The chart doesn't offer it, and the server refuses it.

## 4. Approvals (requirement 5)

**Administration → Approval workflows** sets, per company, who approves each request, in order. There are three request types:
- **Expense claims.** Default: line manager, then HR.
- **Leave encashment.** Default: line manager, then HR.
- **Promotion proposals.** Default: manager's manager, then HR.

Steps can be:
- line manager
- dotted-line manager
- manager's manager
- head of department
- payroll approver
- a named person
- HR

Expense steps can apply only from an amount, for example payroll approver only from ₹10,000.

How a chain runs:
- **Resolved at submission.** A later reorganisation doesn't change open requests.
- **Steps are skipped** when nobody holds the role. A person never approves their own request, and the same person twice in a row approves once.
- **HR always approves last** for encashment and promotions, because they change pay and job records. HR's approval applies the result straight away.
- **Everything waiting appears in Approvals,** with a link to the request. Each request page shows the approval steps and its own activity log.

Leave, attendance corrections, overtime and goals keep their existing approval rules.

## 5. Shifts or time management (requirements 6, 7)

**Time Management → Shifts or time management** (or the Companies form) sets each company to one of two modes:
- **Shift-based.**
  - Shift definitions, rosters and rotation patterns are available.
  - People in the Shift attendance group can earn overtime, paid or as comp-off.
- **Time management only.**
  - Punches, regularisations and the attendance register, against standard working hours.
  - Rosters, patterns and overtime are hidden, and nobody earns overtime.

Overtime now applies only in shift-based companies, and only to people in the Shift attendance group. This is a change from version 1, where people in the Regular group could also be marked eligible.

## 6. Goal templates by designation and role (requirement 9)

**Performance Management → Goal templates by designation.**
- **What a template holds.** Goals and competencies, each with an area, how it is measured, a weight and a target. Weights must add up to 100%.
- **Who it applies to.** It can be limited to designations, grades and departments. Each person gets the most specific match: designation counts most, then grade, then department. A template with no conditions applies to everyone else.
- **How people use it.** On the goals page during goal setting, the employee or manager clicks **Start from the template**. They can change the goals before sending them to the manager.
- **Bulk.** HR can give everyone without goals their template in one step.

## 7. Fixed and variable pay (requirement 9)

- **Personnel action → Salary revision** records two amounts:
  - the **annual fixed CTC**, paid monthly through payroll as before
  - an **annual variable pay target**

  The Salary tab shows both and the total. It also warns when pay is outside the grade's band.
- **Payroll → Variable pay:**
  1. Choose the period (month, quarter, half year or year) and the review cycle whose final ratings to use.
  2. Set the payout % for each rating. Default: 5 → 120%, 4 → 100%, 3 → 80%, 2 → 50%, 1 → 0%.
  3. Override any person's payout % if needed.
  4. Post to a payroll month. It is paid as **Variable pay (1550)**, prorated for people who joined during the period.

  A period can't be posted twice for the same person.

## 8. Leave carry forward (requirement 10)

- Balances carry forward automatically up to each leave type's **Carry forward up to (days)**, as before.
- **New in Leave policies:**
  - **Carried-forward days lapse after (months).** Carried days not used within that time are removed from the balance.
  - **Encash at year end, days above the carry limit (up to).**
- **Leave Management → Year-end carry forward.**
  - Shows, per person and leave type, the closing balance and what was carried, encashed and lapsed.
  - **Encash and post to payroll** takes the encashable days off the old year's balance and pays them as Leave encashment (1700). Posting twice is not possible.
  - **Download** gives the table as a spreadsheet.

## 9. Leave encashment (requirement 11)

- **Leave policies** has three new fields:
  - **Employees may request encashment during the year.**
  - **Balance to keep after encashment.**
  - **Most days encashed in a leave year.**
- **Leave Management → Leave encashment.** Employees see what they can encash and request it. The request goes through its approval workflow.
- **HR's final approval:**
  - takes the days off the balance
  - adds Leave encashment (1700) to the next open payroll month

  Daily wages are basic plus DA ÷ the encashment divisor, the same as on exit.
- Encashment on exit works as before.

## 10. Expense claims (requirement 12)

- **Expenses → Expense categories and limits** is the master data. Each category has:
  - a GL code
  - how it is claimed: an amount, kilometres × rate, or days × rate
  - limits per claim line and per month
  - the amount above which a receipt is needed
- **Expenses → My expense claims.** Employees add each expense, attach the receipt (photo or PDF, up to 10 MB), save a draft or send the claim. Lines over a limit or missing a receipt are flagged to approvers, but can still be sent.
- **Expenses → Claims to approve and pay.**
  - Approvers decide.
  - HR pays approved claims with salary, as **Expense reimbursement (1900)**, not taxed. Or HR records a payment made outside payroll, with its reference.
- **Who can open receipts.** Only the employee, the claim's approvers and HR.

## 11. Employee enrolment (requirements 13, 14)

- **Starting it.** When HR adds an employee, PeopleDesk offers to start enrolment. It can also be started from Personnel action → Start enrolment, or from Personnel Information → Employee enrolment.
- **Who does what.** Each department gets its checklist, from **Personnel Information → Enrolment checklists**:

  | Department | Tasks |
  |---|---|
  | HR | Documents, PF and ESI |
  | IT | Laptop, e-mail, access |
  | Administration | ID card, access card, seat |
  | Finance | Salary account, reimbursements |
  | The manager | Welcome, buddy, first-week plan |
  | The new joiner | Their own details, and confirming assets received |

  Each checklist names who does it and when, counted from the joining date. Departments without a named person fall back to HR.
- **How departments are told.** Each person sees their tasks in **Approvals** and on the enrolment page. HR can also click **E-mail departments**, which opens your mail program with everyone's tasks filled in. (The server does not send mail itself.)
- **Asset items** such as the laptop and ID card are allocated with their tag, serial and model. They go into the assets register.
- **Finishing.** HR completes the enrolment when every task is done or marked not needed.
- **Permissions.** A department can only tick its own tasks; the server refuses anything else.

**Personnel Information → Assets** is the register.
- **What it records.** What was issued, to whom, when and by whom; what came back and in what condition; and the employee's confirmation of receipt.
- **Alerts.** It flags assets held by people who are leaving, and the department that issued them gets a reminder in Approvals.
- **Profiles.** Each profile has an Assets tab.

## 12. Promotions and progression (requirement 15)

- **Grades** have a level, a pay band and the months in grade before promotion.
- **Personnel Information → Promotions and progression:**
  - **Who is due:** months in grade against the minimum, and the last final rating, which must be at least 3. It also shows pay against the band.
  - **Proposals:** a manager or HR proposes the new designation, grade, fixed CTC and variable target, with a justification. It goes through the promotion workflow, and HR's approval applies it from the effective date. It updates the designation, grade, salary with arrears if backdated, the grade history and the employee's History.
  - **Promoted this year.**
- **Profile → Career tab:** the grade and designation timeline, time in grade, and a **Propose promotion** button.
- **Direct promotions.** HR can still promote directly with Personnel action → Promotion, which now also keeps the grade history.

## 13. Activity log (requirement 16)

- **Administration → Activity log.** Who changed what, and when, across PeopleDesk. You can filter by area, person, date and text, and download it.
- **Profile → Activity log tab** (HR): everything recorded about that employee.
- **Per record.** Every approval request, expense claim, enrolment and asset keeps its own log. Everyone taking part can see it.
- **Dated history.** Personnel actions keep their effective dates on the History tab, as before.

## 14. Permissions added on the server

- **Expense claims, approval requests, enrolments and assets** are visible only to the people taking part in them (the employee, the approvers, the department owners) and to HR.
- **An approval step can only be decided by its approver.** Nobody can approve their own request, and a request can't be created already approved.
- **Only HR finishes things:** applying a promotion or encashment, paying a claim, completing an enrolment.
- **Protected employee fields.** Employees cannot change their own reporting lines, grade history or scheduled moves.
- **HR-only data.** Goal templates, expense categories and enrolment checklists can be changed only by HR.
