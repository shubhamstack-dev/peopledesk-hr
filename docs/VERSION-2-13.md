# PeopleDesk 2.13: field settings, code numbering, awards, budgets and the shortlisting run

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages, no new tables and no migration: the new
settings are kept on the company record, and the shortlisting runs on the requisition.

## Field settings (Personnel Information › Field settings)

For each data-entry screen, HR chooses which fields must be filled in and how long a text entry may be.

- Screens covered: the Background tab (previous job, qualification, award, reference), the job requisition, the
  candidate added by HR, **the candidate's own form (the CV format)**, and the set-up lists built on the common list
  dialog (departments, designations, grades, locations, leave types, pay components, expense categories, review
  cycles and the others opened from Field settings).
- Each field is **Optional** or **Required**. Fields the software needs (a name, a job title, the employer of a
  previous job and so on) show **Always required** and cannot be made optional.
- **Longest entry** limits text fields in characters (1 to 2,000). The box stops typing at the limit.
- Required fields carry a red * on every screen.
- On the candidate's form the settings are also enforced by the server: the form cannot be sent until every
  required field is filled in, and text is cut to the longest entry.

## Code numbering (Personnel Information › Code numbering)

Codes are given automatically for **departments, designations, grades, locations and job requisitions**:
a prefix you choose (for example D, DE, G, L, REQ-) followed by a running number of the digits you choose.

- With numbering on, the code is filled in when an entry is added and cannot be typed or changed.
- The next number follows the highest code already in use with the same prefix, so existing codes stay as they are
  (with D01 and D02 in use, the next department is D03).
- Two departments, designations, grades or locations of a company can no longer have the same code, whether
  numbering is on or not.

## Awards: Given by

**Given by** on an award is now a drop-down of the organisations the employee worked at: this company and the
employers under Previous employment, and, in a second group, where they studied.

- A **professional** award must come from an organisation they worked at; an **academic** one from where they
  studied or worked. Add the previous job first if the organisation is missing.
- **Others** (a name typed in) is offered only for sports, community and other awards.

## Job requisition: budget from the grade

- Choosing a **grade** fills **Budget: CTC from** and **up to** from the grade's pay band (Departments and grades),
  and shows the band under the budget.
- Choosing a **designation** fills its usual grade when no grade is chosen yet, and with it the budget.
- The budget stays editable. A figure typed by hand is kept when the grade changes.

## Recruitment: from requisition to shortlist

1. **Find and assign CVs.** **Assign CVs** on the requisition searches the pool by name, company, role or skill, can
   show only candidates at 50, 70 or 90% skills match or more, and lists the best match first. Add a new
   candidate from the same dialog.
2. **Send the CV link.** When assigning, **Send each the link to fill in their details and CV** is ticked. The
   requisition also has **Send CV links**, which sends it to everyone assigned who has not sent their CV. Links
   are e-mailed when the server has e-mail set up; otherwise the dialog lists each link to copy.
3. **The candidate fills in the CV in your format.** The form follows Field settings. The skills the requisition
   needs are listed for them to rate; they cannot add or skip any. **Save** keeps a draft: the same link opens it
   again where they left off. **Send my details** submits it.
4. **Run shortlisting.** On the requisition, **Run shortlisting** lists everyone in Sourced with their CV status
   and skills match, with the skills below the level needed. Set the minimum match and whether every primary skill
   must be at the level (the requisition's own rules to start with), and whether only candidates who sent their
   CV count. Those who meet the rules are ticked; change any tick, then **Shortlist the ticked candidates**: they
   move to Screening. Optionally, **Move the others with a CV to Rejected**. Each run is kept on the requisition
   (who ran it, when, the rules and the result).

Automatic shortlisting (2.12) still works as before. **Run shortlisting** replaces the *Shortlist by skills now*
button.
