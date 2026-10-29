# PeopleDesk 2.1: employee self-service

## Updating the server

Apply the patch, or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.

- **No database changes are needed.**
- **To send e-mail to HR**, add these settings to `.env` (see `.env.example`):
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
  - `APP_URL`, the address of PeopleDesk, used for links in the e-mails

  For Microsoft 365, use `smtp.office365.com`, port 587, with a mailbox that is allowed to send with SMTP AUTH. Without these settings, requests still appear in Approvals; only the e-mail is skipped, and the employee is told so.

## What changed on the profile

| Tab | What the employee can do |
|---|---|
| **Personal** | Blood group and marital status from lists (marital status now includes Divorcee and Widowed). Address split into house and street, country, state, city and PIN code. The city list covers about 350 Indian cities and fills in the state. A city not in the list can be typed. The PIN code is checked: 6 digits, not starting with 0. Emergency contact has a name, relationship (Spouse, Father, Mother, Son, Daughter, Brother, Sister, Friend, Other) and phone. |
| **Family** | Add parents, spouse, children (shown as Child 1, Child 2 and so on), siblings, in-laws and others, with date of birth, gender, phone, occupation, whether each is a dependant for medical insurance, and nomination shares. A warning shows if the shares do not add up to 100%. |
| **Statutory** | **Request a change** for PAN, Aadhaar, UAN, PF member ID, ESI IP number or ESI dispensary. A document is required for each change. HR is e-mailed with a link, approves in Approvals, and the change applies only then. The document is filed under the employee's documents, and the employee is e-mailed the decision. Employees can no longer change these fields directly; the server ignores such changes. |
| **Bank** | Bank name from a list of about 50 Indian banks, or a bank typed in. Typing the IFSC fills in the bank. A warning shows if the IFSC does not belong to the chosen bank. |
| **Salary** | The salary structure HR maintains: fixed CTC, variable target, monthly components and the employer's contributions. |
| **Documents** | Letters issued by HR (joining, confirmation, salary revision, bonus, promotion and others), uploaded by HR from this tab. Below them: payslips, salary revisions and bonuses, and the employee's statutory proofs. |
| **Performance** | Every review cycle with self, manager and final ratings. The manager's rating shows once the cycle closes. A button opens the self-appraisal while it is open, and goal setting while that is open. |
| **Reimbursements** | Every expense claim with its status and how it was paid: with salary (and in which month) or separately (with the reference). Totals show what was paid this year and what is still open. |

## Leave

- **Workflow.** Leave requests now go through the workflow engine. Set the chain under **Administration › Approval workflows › Leave**. The default is the line manager. A step can apply only to leave longer than a number of days, for example the head of department for more than 5 days. HR is added when the leave type or the company's HR approval limit requires it. Requests made before this update keep their old approval route.
- **Supporting documents.** Employees can attach documents (photo or PDF) when applying. In **Leave policies**, "Supporting document needed for more than (days)" makes a document compulsory, for example a medical certificate for sick leave of more than 2 days.
- **Who sees attachments.** Approvers see the documents in Approvals.

## Who can open uploaded files

Each file can be opened by:
- the person who uploaded it
- HR of the company
- the employee, for letters on their own record
- the people taking part in a request or claim it belongs to
- for leave: the employee, their managers, and the approvers in its workflow

Anyone else gets "You cannot open this file". Family members, the address and documents are hidden from colleagues.
