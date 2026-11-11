# PeopleDesk 2.16: professional trainings, total experience, and the news and knowledge hub

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages, tables or migration.

## Professional trainings attended

The **Background** tab of the profile has a new section, **Professional trainings attended**: trainings and
certifications from previous jobs or taken on one's own.

- **Training or certification** is a drop-down of the company's **training records** (Training and development) and
  the standard list of **Professional trainings**. **Others** lets the employee type a new one: it goes to HR under
  Standard lists › New names to review, and HR adds it to the list (or matches it to an existing name), the same way
  as employers and institutions.
- HR keeps the list under **Standard lists › Professional trainings**: add, edit, import from Excel, or **Add the
  starter list** of 28 common trainings and certifications (PMP, Six Sigma, ITIL, cloud certifications, CISA, CFA,
  ISO auditor, first aid, POSH awareness and others).
- Also: conducted by, **attended while at** (this company or a previous employer), from and completed on, hours,
  mode, certificate number, valid until (an expired certification is shown in red) and the **certificate** (photo or
  PDF).
- **Validation.** An entry stays **Unvalidated** until HR checks it: *No certificate: given by the employee*, or
  *Certificate uploaded: waiting for HR*. HR's **Approvals** list each employee with certificates to validate. HR
  opens the certificate and uses **Check**. **Confirmed** is accepted only when a certificate is attached. If the
  employee changes a validated entry, it goes back to unvalidated.
- The section is in **Field settings** (required fields, longest entries) like the other Background sections.

## Total experience

The first figure on the Background tab is now **Total experience**: the previous jobs plus the time in this company
(to today, or to the last working day for someone who has left), with both parts shown under it.

## News and knowledge hub

A new item at the top of the menu, **News and knowledge hub**, with a count of unread posts.

### For HR

**New post** (on the hub, or **Post news** on the home page):

- **What it is**: company news, company performance, something great happened, event, policy or process, or
  knowledge hub (with a **topic**, for example Policies and handbooks, How-to guides, Forms and templates).
- Title, message, an optional link, and **files**: PDF, Word, Excel, PowerPoint or pictures, up to 10 MB each.
- **Who it goes to**: everyone, or some departments and/or locations.
- **Show from** and **until** dates; **Pin it at the top**.
- **Show it to people when they sign in, until they read it** (on by default, except for the knowledge hub).
- **Ask people to confirm they have read it**, for policies.
- **Save as draft** or **Publish**. On a published post, **Ask everyone to read it again** after an important change.
- **Manage posts** lists every post with its status (draft, scheduled, live, ended), who it goes to, and how many have
  read it. Each post shows **Read by n of m**, the names of those who have not read it yet, and **Download who has
  not read it** (Excel).

### For employees

- At sign-in, the posts HR flagged appear first: **Mark as read** (or **I have read these** for policies), or
  **Later**, which shows them again at the next sign-in. Birthday and other greetings follow.
- **News**: pinned first, then the latest; **Mark as read**, **Mark all as read**. Unread posts are marked New.
- **Knowledge hub**: grouped by topic, with search across titles, text and file names.
- Unread news is also listed under **For you** on the home page, and the home page's company feed shows the news.
- Files on a post open only for the people it goes to.
- Announcements posted before this version count as already read.

## Security fix

Uploads of SVG and HTML files are now refused, and files are served with `X-Content-Type-Options: nosniff`. An SVG
picture opened from the site could run scripts in the viewer's session. Office documents are downloaded rather than
opened in the browser. Check that nobody has uploaded SVG files before: `SELECT id, name FROM files WHERE mime LIKE
'image/svg%';`.

## For administrators

- Employees: `prevTrainings` (checked by HR like the other Background lists, `backend/app/workforce.py`),
  `postsRead` (what each person has read, kept on their own record).
- Posts: `kind`, `category`, `files`, `link`, `depts`, `locations`, `from`, `until`, `pinned`, `popup`, `ack`, `status`,
  `rereadAt`. Standard lists: kind `training`.
