# PeopleDesk 2.8: skills, development from reviews, and time and shift controls

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages and no new tables: skills are a new standard
list in `master_items`, and the controls are kept on the company record.

## Skills and development from performance reviews

**Set up (HR), under Personnel Information › Standard lists › Skills**

- The skills library: name, category (technical, functional, behavioural, leadership, safety and compliance,
  language) and what it covers. **Add the starter list** loads 21 common skills; import more from Excel (columns
  *Name*, *Category*, *Also matches*). Skills employees type that are not on the list wait for HR, like other lists.
- **Skills each designation needs**: choose a designation and add skills at a level: Basic, Working, Advanced or
  Expert.

**In the review (Performance › My goals and reviews)**

- In the **manager review** stage the manager sees **Skills and development** under the review: each skill the role
  needs, with the level the role needs. They assess each skill, can assess others too, and **Raise a need** where
  there is a gap (to a level, with priority, a date and why). The suggested level is the role's level.
- In the **self review** stage the employee can add skills they want to develop.
- Employees see their assessed levels once the cycle closes, as with the manager rating.

**Planning the development (HR, Training and development › Skills and gaps)**

- **Development needs from performance reviews**, by skill: how many are open, high priority, planned and done, and
  who needs them. Filter by review cycle, department and designation.
- **Plan a training** starts a training with the skill already ticked under *Skills this training builds*. When you
  add participants, people with an open need for that skill are listed first and ticked; their need becomes
  *Training planned*.
- **Skills against what roles need**: for each skill, how many people's roles need it, how many meet the level, how
  many are below or not assessed yet, coverage, open needs and how many were trained this year. **Download Excel**
  gives a person-by-skill sheet. Managers see the same for their team.

**When people attend**

- Each training lists the skills it builds and to what level (set when planning or editing it).
- When the training is marked completed, everyone who attended has the skill recorded at that level. Their needs for
  it are marked done: those linked to the training, and any other open need for the skill that the training meets.
- The **Skills** tab on the profile shows, for each skill: what the role needs, the latest assessment, the trainings
  attended, what the person declared themselves, and whether they meet the role. The latest evidence counts: an
  assessment made after a training replaces what the training gave. Employees can add skills they have
  (*declared*), and they, their manager or HR can raise a need from a gap.

## Time and shift controls

**Time Management › Time and shift controls** (HR). Each control is **Off**, **Warn** or **Block**:

| Control | Limit (default) | Notes |
|---|---|---|
| Rest between two shifts | 11 hours at least | End of one shift to the start of the next |
| Working days in a row | 6 at most | Then a weekly off is needed (weekly rest) |
| Rostered hours in a week | 48 at most | Monday to Sunday, shift hours less breaks |
| Night shifts in a row | 6 at most | A night shift runs past midnight or starts at 20:00 or later |
| Women before 6:00 or after 19:00 | Consent needed | Record consent on the Job tab of the profile (OSH Code, section 43) |
| Punching in before the shift | 120 minutes early at most | Employees' own punches in the app |
| Corrections and shift requests for past days | 7 days back at most | Employees' own requests |
| Attendance corrections a month | 3 at most | Punch-time corrections, per person |

- **Warn** lets the change through, tells the person making it, and lists it under Control exceptions.
- **Block** refuses the change in the app and **on the server**, wherever it comes from: the roster grid, Change team
  shifts, assigning a rotation, automatic rotation, approving a shift request, punching in, or a correction request.
- **HR may override a blocked roster change** (on by default): HR is asked for a reason, the change goes through and
  the override is kept in the activity log and shown on Control exceptions.
- Automatic rotation leaves out anyone whose rotation would break a blocking control, and **Apply rotations now**
  names them, so HR or the manager can fix their roster by hand.
- On a rotation, days after the roster is filled to are treated as not yet planned, so the last day of a rotation is
  not compared with a default shift that will never be worked.
- Defaults: new companies start with the roster controls set to Block (rest, days in a row, women's consent),
  corrections back in time to Block, and the rest to Warn. Existing companies start with the roster controls on
  Warn and the punch and correction controls Off, so nothing is refused until HR saves the controls.

**Time Management › Control exceptions** (HR for the company, managers for their team): one line per person and
control over a period (four weeks back and ahead by default), with how often, between which dates, the next case and
a link to the roster week. Early punches, corrections over the monthly limit and HR's overrides are listed too.

## Demo data

- Skills for both companies, with what Engineers, Senior engineers, Engineering managers, Account executives, Sales
  associates, Warehouse associates and Shift supervisors need.
- Last year's review (Annual review 2025-26) has managers' assessments and six development needs from it. The demo
  trainings build skills: Secure coding, Negotiation, People management and coaching, POSH awareness.
- Nilgiri Retail has the controls switched on. Priya More and Vaishali Kamble have consented to evening and night
  work; Neha Sawant has not, so her evening shifts show under Control exceptions. Store rotations now change after
  the Sunday off.

## For developers

- `frontend/src/engine/engine.js`, section *PeopleDesk 2.8*: `skillProfile`, `reviewSkillsCard`, `VIEWS.skillgaps`,
  `skillRolesCard`, `PROFILE_TABS.skills`; `TC_RULES`, `timeControls`, `controlIssues`, `controlVerdict`,
  `VIEWS.timecontrols`.
- `backend/app/workforce.py`: `Guard.check_controls` runs after the roster is saved, inside the same transaction, so
  a blocked change undoes the whole save; `Guard.check_attendance_request` covers early punches and corrections.
  Skills are a kind of standard list (`MASTER_KINDS`).
