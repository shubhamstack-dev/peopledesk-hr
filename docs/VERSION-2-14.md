# PeopleDesk 2.14: the candidate's profile, comparison, Outlook interviews, negotiation and closure

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages, no new tables and no migration: the new fields
are kept on the existing records (candidates, applications, interviews, requisitions and the company).

**For Outlook meeting requests only:** in the Microsoft Entra admin center, open the app registration already used for
Microsoft sign-in (Users from Google and Microsoft), and under **API permissions** add Microsoft Graph, **Delegated**,
**Calendars.ReadWrite**, then grant consent. Nothing else changes. Without it, everything else works, and each
interview offers a calendar file instead.

## Add a candidate (Candidates and CVs › Add candidate, or from a requisition)

The dialog now has five tabs: **Details**, **Skills for the job**, **Employment history**, **Education** and **Awards**.
A tab with an error opens by itself when you save.

### Details

- **Current location** is a drop-down of the company's locations (Departments, designations and grades › Locations).
- **Current designation** (it was *Current role*) is a drop-down of the designation master.
- **Current employer** is a drop-down of Standard lists › Employers.
- Each ends with **Others**, to type a name that is not on the list. An employer typed under Others is added to the
  employers list (it goes to New names to review when someone other than HR adds it).
- The candidate keeps the name and, when it is on the list, a link to the location, designation or employer, so the
  profile can be compared with requisitions. Candidates added before 2.14 show their old text under Others; open and
  save them to link it.
- **Willing to relocate** is new.
- The CV is optional: the candidate can attach it through the link.

### Skills for the job

- **Assign to requisition** (or **Also assign to requisition** for a candidate already in the pool) puts the candidate
  in Sourced on that requisition.
- The primary and secondary skills of every requisition the candidate is in are listed with the level needed and the
  candidate's own rating, if they have sent their form. Give your **Rating** for each: None, Basic, Working, Advanced
  or Expert. **Meets** or **Below** shows at once.
- Your rating counts instead of the candidate's own in the skills match. Leave it as **Not rated** to let the
  candidate rate themselves on their form.
- **Other skills** is for anything not on the requisitions.

### Employment history, education and awards

- Add as many of each as needed with **Add employer**, **Add qualification** and **Add award**; **Remove** deletes one.
- Employment: employer and designation are drop-downs with Others (as above), then city, from and to (empty for the
  current job), last CTC, reason for leaving and what they did. Employer, designation and start are needed.
- Education: level, qualification and institution (from the standard lists, or typed), board or university, year
  passed and result.
- Awards: the award, **Given by** (suggests the employers and institutions entered), date, kind and what it was for.
- Required fields and longest entries follow **Field settings** for the Background tab, the same as on an employee.
- At joining, **Convert to employee** brings the employment history, education and awards onto the employee's
  Background tab, whether the candidate filled in their form or not.

## Invite candidates without a CV

- **Add a candidate** has **Send them the link to fill in their details, CV and skill levels** ticked. Only name,
  e-mail and mobile are needed.
- On an open requisition, **Invite by e-mail**: type or paste people, one per line (*name, e-mail, mobile*; the
  mobile is optional). Each is added to the candidate pool (someone already there, by e-mail or mobile, is reused),
  assigned to the requisition, and e-mailed the link. Up to 100 at a time.
- The e-mail now names the position. The form tells the candidate they can start without a CV, and asks for their
  level in each skill the job needs.
- The candidate's form starts with the employment history, education and awards HR recorded, and has a new
  **Awards** section. When they send it, what they sent becomes the candidate's history.

## Profile fit: comparing candidates with the job

Each candidate in a requisition gets a **profile fit**: a score out of 100 on each criterion the requisition sets,
averaged with weights.

| Criterion | Compared | Full marks when |
|---|---|---|
| Skills | the skills match (2.12) | as the match |
| Experience | years (or the employment history) with *Experience from / up to* | within the range |
| Expected CTC | with *Budget up to* | at or below the budget (10% above scores 80) |
| Can join by | today + notice period with *Fill by* | by the fill-by date (2 points off a day late) |
| Location | with the requisition's location | same location (same state, or willing to relocate: 70) |
| Current designation | with the requisition's designation | the same (held before: 85; one grade below: 75) |
| Qualification | highest qualification with the new **Minimum qualification** | at or above it |

- Only criteria the requisition sets and that are known for the candidate count. *Fit 82%** with a star means some
  are not known yet.
- Weights are under **Recruitment settings › Profile fit** (standard: skills 40, experience 15, expected CTC 15,
  joining 10, location 10, designation 5, qualification 5). A weight of 0 leaves a criterion out.
- The requisition has two new fields: **Minimum qualification** and **Minimum profile fit for shortlisting**.

Where it shows:

- **Pipeline cards** carry a *Fit* badge next to *Skills*.
- **Run shortlisting** ranks by profile fit, then skills match, and has a **Minimum profile fit** rule next to the
  skills rules. A requisition without skills can now be shortlisted on fit alone. The run keeps the rule used.
- **Compare candidates** (on the requisition's Pipeline, from **Compare the ticked** in the shortlisting run, or
  **Compare with others** on a candidate) puts the requisition's needs in the first column and the candidates side by side (the five
  best fits to start with; tick anyone else in the pipeline to add them): profile fit, skills match, each skill against the level needed, experience, designation,
  employment history, location, current and expected CTC against the budget, notice against the fill-by date, highest
  qualification, awards, CV status and interview ratings. **Shortlist** moves a sourced candidate to Screening.
  **Print** and **Download Excel** keep a copy for the hiring panel.
- The candidate's page has a **Profile against the requisition** card: each criterion, needed and found, its score,
  and the employment, education and awards.

## Interviews with Outlook (Microsoft 365)

When Microsoft sign-in is set up and Calendars.ReadWrite is granted, **Schedule interview** has an **Outlook
calendar** section:

- **Send a meeting request from my Outlook calendar to the panel.** The meeting is created in your calendar and
  Outlook sends the requests. **Invite the candidate too** adds them. For a video interview without a link, **Create
  a Teams meeting** adds one, and the Teams link is kept on the interview and in the call letter.
- **Check the panel's calendars** shows each panel member's free and busy time that day, from 8:00 to 20:00, and the
  times when everyone is free for the length of the interview. Click a time to use it.
- On the interview: who has accepted, declined or not replied (**Replies** brings them in), **Open in Outlook** and
  **Join the Teams meeting**. **Send Outlook invite** sends one for an interview scheduled without it.
- **Update** to a new date or time moves the Outlook meeting; **Cancelled** cancels it, with your note as the
  message. Only the person who sent the request can change it in Outlook; anyone else is told whom to ask.
- **Calendar file** downloads an .ics invitation for Outlook, Google Calendar or any other calendar, for anyone not on
  Microsoft 365.
- **Recruitment settings › Interview invitations** sets the defaults (Outlook request, candidate invited, Teams).

If Microsoft is not reachable, the interview is still scheduled and the note says why the request was not sent.

## After the interviews: offer, negotiation and closure

### Negotiation

- A **Negotiation** card appears on the candidate from Selected onwards. **Record a round**: what the candidate asked
  (CTC, joining date, joining bonus, other asks such as notice buyout or relocation), what we offered, the outcome
  (*Still talking*, *Agreed*, *We held our offer*, *Candidate walked away*) and a note. An ask above the budget is
  flagged.
- An issued or approved offer has **Candidate wants to negotiate**.
- Agreed before the offer is prepared: **Prepare offer** starts from the agreed terms.
- Agreed after: **Revise the offer to the agreed terms** keeps the earlier version, changes the offer, and sends it
  back to draft for approval again (above the budget still needs group approval). Issuing it gives a new letter
  number.
- *Candidate walked away* marks an issued offer as declined and the candidate as Withdrawn.
- **Offers and approvals** lists who is **In negotiation**.

### Closure

Once the offer is accepted, **Joining and closure** tracks the steps to the first day:

- resignation at the current employer (date), last working day there (worked out from the notice period, and flagged
  when it is on or after the joining date), joining documents received, background and reference check (in
  progress, clear, concerns found), and the joining date confirmed with the candidate;
- then **Convert to employee** as before (the closure records *Joined*), or **Did not join**: did not turn up, backed
  out after accepting, or offer withdrawn by us, with the reason. The candidate moves to Withdrawn, open follow-ups
  are closed and the position stays open.

**Offers and approvals** now has a **Joining tracker** (accepted offers, days to joining and each step) and the hires
**Closed in the last six months**, with the outcome and reason.

## For administrators

- New fields: candidates `locationId`, `currentEmployerId`, `currentTitleId`, `relocate`, `prevJobs`, `education`,
  `awards`; requisitions `minEdu`, `fitMin`; interviews `ms` (Outlook event id, links, replies) and `icsSeq`;
  applications `nego`, `closure`; offers `versions`, `closedAs`; companies `fitWeights`, `ivInvite`.
- The candidate's form (`backend/app/candform.py`) accepts `awards`, starts from HR's `prevJobs`, `education` and
  `awards`, and on sending copies the candidate's lists back onto the candidate, keeping HR's links to the standard
  lists on rows that were kept.
- Outlook calls are made from the browser with the signed-in person's Microsoft token (MSAL, delegated permission);
  the server does not hold Microsoft credentials.
