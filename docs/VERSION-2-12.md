# PeopleDesk 2.12: standard lists, responsibilities, and skills-based shortlisting

## Updating the server

Apply the patch or use the zip, then rebuild as usual. No new packages, no new tables and no migration: the new
list (responsibilities) is kept with the other standard lists, and the new fields are stored on the existing
records (requisitions, candidates, employees' previous jobs).

## Fixes

- **Standard lists: the Add button did nothing.** Clicking **Add institution**, **Add qualification**, **Add
  employer** or **Add skill** raised an error and no dialog opened. The management-meeting screen (2.11) used the
  same button action and replaced the standard-list one. Both now have their own action.
- **Job requisitions: Approve and Reject did nothing.** On a requisition waiting for approval, HR's **Approve** and
  **Reject** buttons raised an error, because the approval of promotions and leave encashment used the same action.
  Fixed the same way.

## Standard lists

**Personnel Information › Standard lists** now has six tabs: new names to review, schools, colleges and institutes,
qualifications, employers (companies), skills and **responsibilities**.

- Every tab's **Add** button works.
- Each line has an **Edit** and a **Delete** button (clicking the line still opens it too). Delete is refused while
  the entry is in use: on profiles, previous jobs and references, requisitions or candidates. Rename it, or map a
  duplicate to it with **Same as…**, instead.
- **Responsibilities** is a new list: what people did in a job, each with an area (operations, people and
  leadership, sales and customers, finance and compliance, technology, projects, quality and safety, other).
  **Add the starter list** puts in 26 common ones. It can be imported from and downloaded to Excel like the others.

## Background: references and previous jobs

On the **Background** tab of the profile, and on the form a candidate fills in:

- **Add reference: Organisation** is a drop-down of the employers (companies) list, and **Their designation** a
  drop-down of the company's designations (**Departments, designations and grades**). Both end with **Others**,
  which opens a box to type a name that is not on the list. An organisation typed under Others goes to **New names
  to review**, like any new employer, and is linked to the employers list from then on.
- **Add previous job: Designation** is a drop-down of the designations with **Others**. **Employer** is now the same
  kind of drop-down (it was a box with suggestions).
- **Responsibilities matrix.** Under each previous job, every responsibility on the list can be marked **Main**,
  **Secondary** or **Not in this job**. A filter helps with a long list, and the count of main and secondary ones
  is shown. The choices can be changed at any time by editing the job. The job's line on the profile shows them.
  The free-text box stays, as **Other responsibilities, in your words**, so nothing entered earlier is lost.

## Recruitment: skills a job needs, candidates' levels, and automatic shortlisting

### On the requisition

**Raise requisition** (and **Edit**) has, instead of a single *Key skills* box:

- **Primary skills needed**: the skills the job cannot be done without, each with the level needed (Basic,
  Working, Advanced, Expert).
- **Secondary skills needed**: useful skills that are not essential, each with a level.
- Skills come from **Standard lists › Skills**. **New skill…** at the end of the drop-down adds one: from HR it goes
  straight on the list; from a manager it is proposed to HR (it can be used on the requisition at once).
  A skill can be listed only once, as primary or secondary.
- **Other skills or notes** keeps what was typed in *Key skills* on older requisitions.
- **Shortlist candidates automatically by skills match**, a **minimum skills match** (70% unless changed) and
  **Every primary skill must be at the level needed** (on unless unticked).

The requisition's page shows both lists, and each candidate on the pipeline carries a **Skills %** badge (with *
when not every skill is rated yet). **Assign CVs** lists the pool with the best match first.

### The candidate's levels

- On the form HR sends a candidate (**Ask the candidate to fill in their details**), a **Your skills** section asks
  their level in each skill their requisitions need, the primary ones first, with **None** for a skill they do not
  have. The form cannot be sent until every skill has a level.
- On the candidate's page in a requisition, **Skills match** shows each skill: the level needed, the candidate's
  own rating, the **assessed level** HR records (after screening or an interview) and whether it meets the need.
  An assessed level counts instead of the candidate's own rating.
- At joining (**Convert to employee at joining**), the skill levels go onto the employee's skills, together with
  the previous jobs' designations and responsibilities and the references' organisations.

### The match and automatic shortlisting

For each skill the requisition needs, the candidate scores their level divided by the level needed, at most 1
(Working against Advanced scores 2 ÷ 3). Primary skills count twice. The match is the weighted average, as a
percentage.

> Python Advanced, SQL Working, FastAPI Working (primary) and Communication Working (secondary). A candidate at
> Advanced, Working, Working and Basic scores (2 + 2 + 2 + 0.5) ÷ 7 = **93%**.

With **Shortlist automatically** on, a candidate in **Sourced** moves to **Screening** when they are rated on every
skill, reach the minimum match and, if required, every primary skill is at the level needed. Their history says
*Shortlisted automatically: skills match 93%*. This happens:

- when the candidate sends their form (on the server, so nobody needs to be signed in);
- when HR records assessed levels on the candidate's page;
- when candidates are assigned to the requisition, or the requisition is saved;
- with **Shortlist by skills now** on the requisition, which also works when automatic shortlisting is off.

Candidates are only ever moved forward from Sourced; nobody is rejected automatically.
