# PeopleDesk 2.3: document templates from Word

HR can keep letters and forms as Word templates, and create them for any employee with the details filled in from the database: salary revision, appointment, confirmation, promotion, transfer, experience letters and so on.

## Updating the server

Apply the patch or use the zip, then rebuild with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. One new Python package is needed (`docxtpl`, already in `backend/requirements.txt`). The API creates the three new tables (`document_types`, `document_templates`, `doc_counters`) when it starts. If its database user cannot create tables, run `database/migrations/2026-10-v2-3.sql` once as a MySQL administrator.

## Document types (Administration › Document types)

- A type is a kind of document HR issues, such as *Salary revision letter*. **Add the usual types** creates the common ones.
- Give a type a **number prefix** to number its documents: prefix `SRL` gives `SRL/NTPL/2026-27/0001`, `0002` and so on, starting again each financial year, separately for each company. Numbers are taken in MySQL in one step, so two HR users can never get the same number.
- A type for **all companies** can only be made by the group administrator; HR administrators make types for their own companies.

## Templates (Administration › Document templates)

1. **Write the letter in Word.** Where a detail goes, type a placeholder in double curly brackets, for example `Dear {{ salutation }} {{ employee_name }},`. Names use letters, digits and underscores only, no spaces. Placeholders work in the body, in tables and in headers and footers, and keep the formatting you give them in Word. Save as `.docx`.
2. **Add a template**, give it a name and document type, and upload the file. PeopleDesk lists every placeholder it found. Two samples are in `docs/templates/`.
3. **Map each placeholder** to where its value comes from:
   - **Database field**: one of about 70 fields: employee, job, pay, statutory and bank, exit, company and document details. Placeholders named after a field (`{{ designation }}`) are mapped automatically. The full list, with a copy button, is under the templates.
   - **Employee record field**: any field stored on the employee record, such as `addrCity`.
   - **Fixed text**: the same words in every document.
   - **Ask when creating**: a question HR answers each time, such as the effective date or a performance note, as short text, a paragraph, a date (written 1 April 2026), an amount (written ₹ 12,50,000) or a number. It can be required.
   - **Leave empty**.
4. **Save and download a draft** for any employee to check it. Questions are filled with their labels so you can see where the answers land.

Uploading a new Word file replaces the template and keeps the mappings for placeholders that are still there. Earlier files stay listed under the template.

### Tables and optional text

To repeat a table row for each salary component, use three rows in Word: a row containing only `{%tr for c in salary_components %}`, a row with `{{ c.name }}`, `{{ c.monthly }}` and `{{ c.annual }}` in its cells, and a row containing only `{%tr endfor %}`. The salary breakup comes from the company's pay components and the payroll rules, so it matches the payslip.

To show a sentence only when there is a value, wrap it: `{% if variable_pay %}You are also eligible for variable pay of {{ variable_pay }}.{% endif %}`.

## Creating a document (employee profile › Documents)

1. HR opens **Create from a template**, chooses the template and the date, and answers the template's questions.
2. **Download a draft** gives a copy marked DRAFT; nothing is numbered or saved.
3. **Create and add to profile** fills the template from the database, gives it the next letter number, keeps the Word file and lists it under **Letters and service documents**, where the employee can download it. It is recorded in the employee's history and the activity log.

If a placeholder comes out empty, for example no previous salary for an increase, PeopleDesk says which, so the record can be completed and the document made again.

## Who can do what

- Only HR (for that employee's company) and the group administrator can see templates, upload them and create documents. The server checks this on every request.
- An employee sees and downloads the documents on their own profile. Colleagues and managers cannot open them.
- Values are read from MySQL on the server, not from the browser. Templates are filled in a restricted (sandboxed) template engine, and every value is escaped, so neither a template nor a value with `&` or `<` can damage the document.

## For developers

- `backend/app/doctemplates.py`: the field catalogue (`FIELDS`), reading placeholders, reading values from the database, letter numbers and filling the Word file with docxtpl. To add a field, add it to `FIELDS` and give it a value in `values()`.
- `backend/app/main.py`: `/api/doc-templates/fields`, `/scan`, `/preview` and `/generate`.
- `frontend/src/pages/DocTemplates.jsx`: the Templates and Document types screens. The profile dialog is `ACT.docGen` in `engine.js`.
- Documents are made as `.docx`. For PDF, LibreOffice can be added to the server image and the filled file converted after `render()`.
