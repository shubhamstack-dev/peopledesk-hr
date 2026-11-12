# PeopleDesk 2.18: the recruitment flow, from CV to signed offer

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages, no new tables and no migration: the new fields
are kept on the existing records (companies, candidates, applications and interviews).

**Before you start using it**, look at **Recruitment settings › Recruitment flow**. The three checks below are on as
standard, and the server keeps to them:

- candidates are interviewed only after management approves the shortlist;
- candidates are selected only through the final selection, decided by the hiring manager;
- an offer is accepted only with the signed offer letter attached.

Candidates already in Screening need management approval before an interview is scheduled, and candidates already in
Interview move to Selected through the final selection. Switch a check off if you do not want it.

## The flow

1. **CVs come in** from job portals (import) or from the candidate's own form (the link, as before).
2. **HR shortlists** them against the requisition (Screening), by hand or with **Run shortlisting**.
3. **Management approves** the shortlist: approve, hold or reject each candidate.
4. **Interviews** are arranged for approved candidates, online, by phone or face to face.
5. **Each panel member fills in the feedback form**: ratings, strengths and concerns, and a recommendation: hire,
   reject, hold, or refer the decision to someone else.
6. **The final selection**: once the interviews are done and the feedback is in, HR proposes select, reject or hold,
   and the hiring manager decides.
7. **The offer**, in as many rounds as it takes, each approved before its letter is issued.
8. **Acceptance with the signed offer letter**, then joining and closure (2.14) and the employee record.

## Import from a job portal (Candidates and CVs, or a requisition)

**Import from job portal** takes the list you export from the portal as Excel or CSV: Naukri (RMS or Resdex),
LinkedIn, Indeed, foundit, Shine, Instahyre, apna, iimjobs or hirist, or any other.

- The columns are matched by their names; title rows at the top of the export are skipped. Check or change the
  matching under **Columns** before you import.
- Experience, salary and notice period are read as the portals write them: *5 Yrs 3 Months*, *12.5 Lacs*,
  *12 Lacs 50 Thousand*, *INR 12,00,000*, *1.2 Cr*, *50,000 per month*, *Immediate*, *1 Month*,
  *More than 3 Months*. A plain number below 200 as salary is taken as lakhs.
- Mobile numbers are kept as 10 digits (+91 or 0 in front removed).
- **CVs**: choose the CV files too (up to 2 MB each). Each is matched to a candidate by the e-mail or mobile in the
  file name, or by the candidate's name, as in the portals' bulk CV downloads (*Naukri_RohitVerma[5y_3m].pdf*).
  A file that fits nobody, or more than one candidate, is left out and named.
- The preview shows each row as **New**, **Already in the pool** (same e-mail or mobile), **Twice in the file**, or
  **Left out** (no name, or neither e-mail nor mobile).
- **Assign to requisition** puts everyone imported in Sourced on that requisition; automatic shortlisting (2.12)
  runs as usual. **Fill in the details that are empty** updates candidates already in the pool without overwriting
  anything. **Send each new candidate the link** sends the form link (2.11).
- Education, the profile link and the application date go into the candidate's notes. The source is *Job portal*,
  and the portal is kept on the candidate. Up to 1,000 rows at a time.

## Management approval of the shortlist

- On the requisition, **Send shortlist for approval** lists the candidates in Screening. Tick them, add a note and
  send. They move to the new stage **Management approval**, a column on the pipeline.
- **Who approves** (Recruitment settings › Recruitment flow): the requisition's hiring manager, and the management
  approvers you choose for every requisition. **With more than one approver**: one approval is enough (the latest
  decision counts), or everyone must approve (a rejection by anyone rejects).
- Approvers see **Shortlist to approve** in Approvals and work on **Recruitment › Shortlists to approve**: each
  candidate with experience, current and expected CTC against the budget, notice, profile fit, skills match, the CV
  and the other approvers' decisions. **Approve**, **Hold** or **Reject**, with a reason for hold or reject;
  **Approve all** for a requisition. Approvers can open the candidate's page.
- Approved: the candidate moves to Interview. Rejected: to Rejected, with the reason. On hold: stays with
  management; the approver can decide later, and HR can **Send again**.
- **Schedule interview** on a candidate who is not approved explains why and offers **Send for approval**. HR can
  choose **Interview without approval** with a reason, which is kept on the candidate's record.
- HR sees what is still **with management** and can **Remind by e-mail**.

## The interview feedback form

- **Give feedback** opens the form: each point rated 1 to 5 (or *Not seen*), the overall rating (filled in from the
  points until you change it), the recommendation, strengths and concerns.
- **Recommendation**: *Recommend hiring*, *Reject*, *Put on hold* (why, and decide by), or *Refer to others to
  decide* (choose the people, and what they should decide or check).
- **The points** are set under Recruitment settings › Interview feedback form (up to 12). The standard ones are
  technical and functional knowledge, relevant experience, problem solving, communication, attitude and culture fit,
  and teamwork and leadership.
- **Referrals**: each person referred to sees it in Approvals, opens the candidate (CV and all the feedback) and gives
  their decision: hiring, rejection or hold, with the reason.
- **Face to face, on paper**: **Blank form to print** on each interview. HR types a filled-in form in with **Type in a
  filled-in form**, choosing the panel member; it shows as typed in by HR.
- The candidate's page has an **Interview feedback** card: each round, each panel member's recommendation, overall
  rating and points, strengths and concerns, the referrals, whose feedback is due, and whether the candidate is ready
  for the final selection.

## The final selection

- A candidate is **ready** when no interview is still scheduled, every panel member of each completed interview has
  given feedback and every referral is answered. HR sees **Interviews done: final selection** in Approvals.
- **Recruitment › Final selection** lists the open requisitions; open one. **Propose**: for each candidate in
  interviews, select, reject or keep on hold, a rank and a note. Select and hold need the candidate to be ready;
  reject is always possible. **Send to the hiring manager**.
- The hiring manager sees **Final selection: your decision** in Approvals, and on the page HR's proposal next to each
  candidate. Agree, or decide otherwise with a reason, and **Confirm decisions**.
- Select: the candidate moves to Selected and the offer can be prepared. Reject: to Rejected. Hold: stays in
  Interview; HR can propose again in a later round. Earlier rounds are kept.
- Where the HR person is the hiring manager, or the requisition has no hiring manager, HR's choice is the decision.
- The **Move to Selected** button is gone while the final selection is on.

## Offer rounds and the signed acceptance

- **Declined** asks for the candidate's reason and what next: **Make a revised offer** (the offer goes back to draft
  with the earlier one kept as a round; change the terms, send it for approval, issue it with a new letter number) or
  **Close** (as before).
- **Revise the offer** on an approved or issued offer starts a new round in the same way. Negotiation (2.14) still
  works as before.
- The **Offer rounds** card lists every round: CTC, joining date, letter number, when it was issued and the outcome.
- **Accepted** asks for the date the candidate signed and the **signed offer letter** (PDF or photo, up to 10 MB).
  The acceptance is recorded only with it, unless the check is off. For an offer accepted earlier without it,
  **Attach the signed letter**.
- The hiring manager can open the signed letter as well as HR.
- At **Convert to employee** (or rehire), the signed letter is filed on the employee's documents as *Offer letter*.
  Joining and closure (2.14) follow as before.

## E-mails

Three new e-mails, editable under **E-mail templates**: *Shortlist for approval* (to each approver who has not
decided), *Final selection* (to the hiring manager) and *Interview referral* (to the person referred to). The
recipients are worked out on the server from the saved records. Without a mail server the screens say so, and every
item is in the person's Approvals anyway.

## For administrators

- New fields: companies `rflow` (`slOn`, `slHM`, `slIds`, `slRule`, `selOn`, `signOn`) and `ivCriteria`; candidates
  `portal`; applications `shortlist`, `sel` and `offer.signed`, with `offer.versions` now also holding `issuedAt`,
  `respondedAt` and `reason`; interviews `feedback[...]` with `scores`, `strengths`, `concerns`, `holdReason`,
  `holdUntil`, `referTo`, `referQ` and `enteredBy`, and `referrals`. A new stage `approval`, and the recommendations
  `reject` and `refer` (old `strong` and `no` still show).
- **Server checks** (`backend/app/recruit.py`, called from `policy.py` for applications and interviews, for everyone,
  the group administrator too):
  - each approver decides only for themselves;
  - the shortlist's status must match the decisions;
  - no move to interviews, and no new interview, without approval (or HR's skip with a reason);
  - only HR and the requisition's owners send shortlists, propose, schedule interviews and move candidates;
  - only the hiring manager decides the final selection, and differently from HR only with a reason;
  - no move to Selected or later except through it;
  - each panel member writes only their own feedback; HR types in a form only for a panel member, marked as typed in;
  - only the person referred to answers a referral;
  - an offer is accepted only with the signed letter.
- **New endpoint**: `/api/recruit/notify` (events `shortlist`, `selection`, `referral`). It sends only for what the
  caller sent, proposed or referred.
- **Files**: a file on an application (the signed letter) can also be opened by the requisition's hiring manager and
  the person who raised it.
- **Tests**:
  - `backend/tests/test_recruit_flow.py`: the rules, no database needed;
  - `frontend/tests/portal-import.test.mjs`: the portal parsing, with `node frontend/tests/portal-import.test.mjs`.
- The portal parsing is in `frontend/src/engine/portal-import.js`.
