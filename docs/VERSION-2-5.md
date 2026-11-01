# PeopleDesk 2.5: training and development

## Updating the server

Apply the patch or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. No new packages. The API creates four tables (`trainings`, `training_enrolments`, `training_feedback`, `training_needs`) when it starts; if its database user cannot create tables, run `database/migrations/2026-11-v2-5.sql` once as a MySQL administrator.

Training content can be up to 200 MB a file. Change it with `TRAINING_UPLOAD_MB` in `.env`. If PeopleDesk sits behind nginx, raise `client_max_body_size` to match. Share long videos as a link.

## The menu: Training and development

| Item | Who |
|---|---|
| My training | Everyone: to-do list, upcoming trainings, trainings attended with content and certificates, training hours this year |
| Training calendar | Everyone: upcoming and past trainings, by category |
| Team training | Managers: requests to approve, ratings due, each team member's training this year |
| Development needs | Everyone: needs for yourself and, for managers, your team |
| Plan and manage trainings | HR |
| Instructor reports | HR (every trainer) and internal trainers (their own) |

Each employee profile has a **Training** tab with their record and needs, visible to them, their managers and HR.

## Planning a training (HR)

1. **New training**: title, category, internal (choose the trainers among employees) or external (trainer's name, provider, e-mail for the report, phone), how it runs (classroom, virtual, on the job, e-learning, at the provider), dates and times, hours, places, venue or link, when enrolment closes, cost, whether it is mandatory, who should attend, objectives and agenda, and after how many days managers rate it (default 30).
2. It starts as a **draft**. Add the **questionnaire** and adjust the **feedback form** if you wish (see below).
3. **Publish** to open enrolment. **Cancel training** or **Edit** at any time.

**Development needs → trainings.** Managers, HR and employees record needs (topic, category, priority, needed by, why). Under Development needs, HR sees **open needs by topic** and **Plan a training** starts one for the topic. When adding participants, people with a matching open need are listed first and ticked; their need becomes *Training planned*, then *Done* once they attend.

## Who takes part

- **Employees** open a training in the calendar and **Ask for a place**, saying why. Their line manager approves or declines (HR does, if they have no manager). It is in the manager's Approvals.
- **Managers** **enrol team members** directly; **HR** adds anyone. A full training warns before going over its places.
- People can **withdraw** (and managers and HR remove them) until the training starts.

## Running it (trainer or HR)

- From the start date the trainer marks each participant **Attended** or **Absent**. **Mark completed** records anyone not marked as absent, opens feedback and the questionnaire after the training, and opens the content for the people who attended.
- **Training content:** upload slides, documents, spreadsheets, PDFs, pictures, audio, video or zip files, or add links (recordings, course pages, shared folders). **Only the trainers, HR and people who attended can open it**: the server refuses the file to anyone else, and others see only how many items there are.
- **Certificate:** participants who attended print a certificate of participation (with their score if they passed).

## Questionnaires and feedback

- **Questionnaire:** multiple-choice questions, used before the training (what people already know), after it (what they learnt), or both, with a pass mark. Each participant answers once. **The server marks the answers and participants never receive the correct answers**, so scores cannot be faked. Results show before-and-after averages and how many passed.
- **Feedback:** after attending, each participant rates every line of the feedback form from 1 to 5 (relevance, content, trainer's knowledge, clarity, engagement, pace, materials, arrangements, overall, plus any you add), says what they liked and what the trainer should improve, and whether they would recommend it. **Trainers see feedback without names**; HR sees names. The form is fixed once someone answers.
- **Manager rating:** after the number of days set for the training, each participant's manager is asked in Approvals to rate how it worked: applies what was learnt at work, improvement seen, worth the time, with a comment. HR and the trainer see these ratings; the employee does not.
- All of it is in Approvals: requests to approve, questionnaires, feedback and ratings due, and trainings that are over but not completed.

## Instructor reports

For every internal and external trainer, across all their completed trainings:

- every rating against **the average across all the company's trainings**;
- **areas to improve**: questions rated below 3.5, or clearly below the company average (the two lowest if nothing stands out), and strengths;
- what participants would like improved and what they liked, in their own words, without names;
- questionnaire gain from before to after, and managers' ratings of the effect at work;
- each training's attendance and overall rating.

**Internal trainers** see their own report under Instructor reports. **HR** can **print** any report or **e-mail it to the trainer** (to the external trainer's e-mail on the training, or the internal trainer's work e-mail); the e-mail has no participant names.

## Reports and exports

- **Plan and manage trainings**: trainings held this year, training hours (and per employee), cost (and per person trained), overall rating. **Excel** exports every training and every participant with hours, scores and manager ratings.
- Each completed training exports its participants and its feedback to **Excel**.

## Who can do what (enforced on the server)

- Only HR plans, publishes, edits and cancels trainings. Internal trainers may add content, set the questionnaire and mark the training completed, nothing else.
- An employee may ask for a place for themselves, withdraw, and answer their questionnaire once. Only a manager in their reporting line (or HR) approves or enrols them. Only the trainer or HR marks attendance. Only someone who attended gives feedback, once and as themselves. Only a manager above them rates the effect.
- Cost and the external trainer's contact details are for HR. Correct answers are for HR and the trainer. Feedback is anonymous to trainers. Development needs are seen by the employee, their managers and HR.

## Demo data

**Explore with demo data** now includes a completed internal training with questionnaire results, feedback and a manager rating; a completed external training whose feedback points to its materials and venue; an upcoming leadership programme with one enrolment and one request waiting for approval; a mandatory POSH session; and three development needs.

## For developers

- `backend/app/training.py`: the rules, the marking of questionnaires and the report for e-mails. `policy.py` calls it; `main.py` has `/api/training/upload`, `/api/training/score`, `/api/training/report-mail` and lets attendees open training files in `_file_visible`.
- `frontend/src/engine/engine.js`: section *PeopleDesk 2.5: training and development* (`VIEWS.training`, `VIEWS.course`, `trReport`, `PROFILE_TABS.training`, `trainingDemo`).
