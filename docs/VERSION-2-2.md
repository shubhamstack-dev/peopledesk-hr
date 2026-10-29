# PeopleDesk 2.2: punch edits, shift changes and medical insurance

## Updating the server

Apply the patch, or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. No database or settings changes are needed.

## Punch times and shifts (Time Management › My attendance)

- **Punches:** the new **Punches** table lists every day of the month with the shift, the punch-in and punch-out times from the attendance device or the app, the hours, the status, and any change waiting for approval.
- **Edit times:** the employee enters the correct in and out times and a reason. The recorded times stay until the change is approved.
- **Change shift:** the employee asks to work another shift, or a weekly off, on a day. Shift changes are offered in companies set to shift-based working.
- **Approval:** both go through the workflow engine. Under **Administration › Approval workflows**, set the approvers for **Attendance corrections (punch times)** and **Shift changes**. The default for both is the line manager; for example, add HR or a head of department after the manager. Each request shows its current step to the employee and in Approvals.
- **When approved:**
  - A time correction replaces that day's punches, marked "corrected".
  - A shift change updates the roster for that day.
  - If the last approver is outside the employee's reporting line, the change is applied automatically the next time the line manager or HR opens PeopleDesk.
- **Direct edits are blocked:**
  - **Employees** can no longer change their own punches directly. They punch in and out for today at the current time; any other change must be a correction.
  - **Night shifts:** punching out after midnight is allowed on the previous day's record.
  - **The server** refuses anything else.
- **Older requests:** corrections made before this update keep their old approval route.

## Medical insurance (mediclaim)

- **Personnel Information › Medical insurance policies** (HR): add each policy with:
  - its name and type (group mediclaim, top-up, personal accident, term life)
  - the insurance company, policy number, validity, sum insured and TPA
  - the contact details: insurer helpline and e-mail, TPA helpline and e-mail, claims address, website or app, and the HR contact
  - notes for employees, such as network hospitals or the cashless process

  The list shows how many employees are enrolled, and flags policies that expire within 30 days.
- **Profile › Personal › Medical insurance › Add insurance** (HR): choose the policy and enter:
  - the employee's member ID and e-card number
  - the sum insured, and whether it is a family floater
  - the cover dates (empty means the policy's dates)
  - the family members covered, each with their own member ID; family members come from the Family tab
- **The employee** sees their insurance on the Personal tab: policy and member numbers, covered family with their member IDs, and every contact for a claim.
- **Who can change and see it:** only HR can change it. It is hidden from colleagues.
