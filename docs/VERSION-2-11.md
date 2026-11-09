# PeopleDesk 2.11: candidates' details, goal library, appraisal, meetings and succession

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages. The API creates three tables
(`goal_library`, `performance_meetings`, `succession_plans`) when it starts; if its database user cannot create
tables, run `database/migrations/2026-11-v2-11.sql` once as a MySQL administrator. Existing goal templates are
moved into the goal library the first time HR opens them or presses **Move them into the library**; their
weightages and targets are kept.

## Recruitment: the candidate fills in their details, and becomes an employee at joining

- On a candidate (**Candidates and CVs**, or the candidate's page in a requisition), HR presses **Ask the candidate
  to fill in their details**. PeopleDesk makes a link (sent by e-mail when the server can send mail, and shown to
  copy or send on WhatsApp). The link works for 14 days without signing in; a new link stops older ones.
- The candidate fills in: personal details, address and emergency contact, PAN, Aadhaar, UAN and bank account,
  current job and expected pay, education, previous jobs, references, family, and attaches their CV. They can save
  and come back, then send it with a declaration that the details are true. Formats (PAN, Aadhaar, IFSC, PIN,
  dates) are checked by the server.
- HR sees **Candidate's details: Received** on the candidate, can view and print them, mark them checked or **Ask
  for changes** (the candidate's link opens again with HR's note). Received forms appear in **Approvals**.
  Outside HR (hiring managers, interview panels) people see only whether the form was sent, not its contents.
- **Convert to employee at joining** is offered once the candidate is *Selected* (no longer only after an accepted
  offer in PeopleDesk). With an accepted offer the offer's terms are used; otherwise HR enters the designation,
  grade, location, manager, CTC and probation. Ticking **Bring over what the candidate filled in** fills the new
  employee record: personal details, address, emergency contact, PAN, Aadhaar, UAN, bank, education and previous
  jobs (linked to the standard lists of institutions, qualifications and employers), references and family. A PDF
  CV is added to the employee's documents. The form is then closed.

## Performance management

### Goal library: goals and measurement criteria, independent of roles

**Performance Management › Goal library and measurement criteria** (HR). Each entry is a goal (a result) or a
competency (a behaviour), with a code, area, what it covers, and how it is measured:

| Measured as | Rating |
|---|---|
| A number, higher is better (revenue, on-time %) | From the achievement as a % of target, against the entry's bands (standard: 120% → 5, 105% → 4, 95% → 3, 80% → 2) |
| A number, lower is better (cost, defects, attrition) | The same, with target ÷ actual |
| A milestone | Against the descriptions for each rating |
| Rating descriptions (competencies) | Against the descriptions for each rating |

Each entry also has a unit, the formula or rule, where the figures come from and how often they are measured, and
a description of what earns each rating from 5 to 1. **Add common goals** gives a starting set of 18.

### Role weightages

**Role weightages** (formerly *Goal templates by designation*): for each role (designations, grades,
departments) choose goals from the library, with the role's **weightage** (adding up to 100%) and **target**. The
same library goal can weigh 40% for sales managers and 10% for engineers. **Goals against roles** shows the whole
matrix. People get their role's goals with the measurement criteria copied onto their goal sheet, so later changes
to the library do not change a sheet already in use. On their sheet, an employee may change only the target of a
role's goal; the manager can change its weight (the role's weight stays visible).

### The appraisal form

**My goals and appraisal** now shows everything needed to appraise:

- Job details: designation, grade, department, manager, date of joining and time in the company, the role.
- Each goal with its weightage, target, progress, check-ins and **How it is measured** (criteria and what earns
  each rating).
- **Appraise** (employee) and **Rate** (manager) per goal: the achievement against the target with the rating the
  criteria give it (e.g. *115% of the target: the criteria give 4*), a comment, and evidence (photo or PDF).
- A structured self-appraisal: achievements, challenges, support needed, career aspirations, what to learn next,
  willingness to move. **Send my self-appraisal** once every goal is appraised.
- The manager review: strengths, areas to improve, overall comments, potential and a recommendation (promotion,
  special increment, development, improvement plan, separation; not shown to the employee). **Complete the
  review** locks it; HR can reopen.
- **For this appraisal**: earlier ratings, trainings attended in the period, open development needs, changes in
  the period (promotions, transfers), and feedback and kudos received.
- After the cycle closes, the employee **acknowledges** the appraisal (agrees, or does not fully agree with a
  comment).
- **Appraisal form** prints the whole appraisal with signature lines.

### Review meetings

**Performance Management › Review meetings**, or **Schedule a review meeting** on someone's appraisal. A manager
(or HR) schedules a meeting with the employee (goal setting, check-in, appraisal, improvement-plan review), then
records the minutes (discussed, going well, to improve, agreed) and actions with owners and dates. Once it is
marked held, the employee is asked in Approvals to read the minutes and say whether they are a fair record. The
meetings appear on the appraisal and in the printed appraisal form.

### Management meetings and decisions

**Performance Management › Management meetings and decisions**, and on **Calibration**. A manager or HR calls a
meeting (chair, people invited, agenda), writes the minutes and records a **decision for each person discussed**:
promote (with the new designation and grade), special increment, retain as key talent, development plan,
performance improvement plan, transfer or change of role, **asked to leave (separation)**, or no change, with the
reasons, an owner and a date. From a decision the owner can propose the promotion (promotion workflow), start the
exit (exit management) or raise a development need; the decision's status follows what is done there. The
**Decisions** tab lists every decision with what has happened since, and downloads to Excel.

These meetings are confidential: only HR and the people invited see them, never the employees discussed unless
invited. Outside HR, decisions may only be about people in the recorder's reporting line, and nobody records a
decision about themselves (enforced on the server).

### Succession planning

**Performance Management › Succession planning** (managers and HR). During the cycle a manager plans the key
positions in their team, including their own: how critical the position is, the risk of losing the person in it,
when it may fall vacant and why, who covers in an emergency, and possible successors, each with readiness (now,
1–2 years, 3 or more years), strengths, gaps and how to develop them, with their rating, potential and time in
grade shown. They **Send it to HR**, who reviews it. **Bench strength** shows critical positions with nobody ready
now and the talent pool (everyone named as a successor). The person in a position does not see plans their
managers make about it, and successors do not see that they are named.

### Who sees goals and reviews

Goals and reviews now reach only the employee, their managers (line and dotted line) and HR. Finance receives
only final ratings, for variable pay. Before 2.11 every signed-in employee received them (the screens hid them).

## For developers

- `backend/app/candform.py`: the candidate's link (`p: candform` token with a nonce on the candidate's `form`),
  `clean` and `check` (what the form holds and its rules), `save`, `merge_from_app` (saves from the app keep what
  the candidate entered; HR may only return or close the form). `main.py`: `POST /api/candidate-form/link` (HR),
  `POST /api/apply/open` and `/api/apply/save` (no session, CSRF header required).
- `backend/app/perf.py`: `visible` (meetings, plans, goals and reviews), `check_meeting`, `check_plan`,
  `may_delete`. `policy.py`: `PERF`, `goalLib` is HR-only, candidates' forms redacted outside HR.
  `collections.py`: `goalLib` (`goal_library`), `perfMeetings` (`performance_meetings`), `succession`
  (`succession_plans`). File access: evidence on goals and files on meetings.
- `frontend/src/engine/engine.js`, section *PeopleDesk 2.11*: `critFromLib`, `suggestRating`, `tplGoals`
  (templates now hold `lines: [{libId, weight, target}]`), `goalsFromRole`, `VIEWS.goallib`, `VIEWS.perftemplates`,
  `VIEWS.performance` (replaced), `ACT.goalAppraise`, `ACT.apprPrint`, `VIEWS.perfmeetings`, `VIEWS.perfmeeting`,
  `VIEWS.succession`, `applyCandForm`, `ACT.offerJoin` (replaced). Reviews keep `selfSummary` and `mgrSummary`
  for older screens and add `self`, `mgr` and `empAck`.
- `frontend/src/pages/CandidateForm.jsx`: the candidate's page at `#/apply?t=…`.
