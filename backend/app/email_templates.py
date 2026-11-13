"""
Admin-editable subject/body for the e-mails PeopleDesk sends, instead of each one being an inline
f-string at its call site. Mirrors doctemplates.py's approach (a Jinja2 SandboxedEnvironment) but for
plain-text e-mail bodies, not Word documents -- every e-mail this app sends today is text-only, so
there is no HTML side to this yet.

A mail key names one kind of e-mail (e.g. "access.invite"). DEFAULTS holds today's exact wording as a
Jinja2 template, so an install that never visits Email templates sends byte-identical e-mail to
before this existed. An HR administrator can override subject and/or body per company in the
emailTemplates collection; render() prefers that, falling back to the default. Everything a caller
already knew when it built its f-string (names, links, pre-joined lines, pluralised words) is passed
in as the context -- the same values, just handed to Jinja instead of an f-string. Jinja control
structures ({% if %}, {% for %}) work in a customised template too, same as doctemplates.py's Word
templates allow {%tr for %}.
"""
import logging
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import text

from . import repo

TABLE = "email_templates"


def _env() -> SandboxedEnvironment:
    return SandboxedEnvironment(autoescape=False, trim_blocks=True)


def _render_str(s: str, ctx: dict) -> str:
    return _env().from_string(s or "").render(**ctx)


# mail_key -> (subject template, body template, [(merge tag, what it is), ...])
DEFAULTS: dict[str, dict] = {
    "access.invite": {
        "subject": "Your access to PeopleDesk, {{ company }}",
        "body": "Dear {{ name }},\n\n{{ who }} has given you access to PeopleDesk for {{ company }}.\n\n"
                "Open this link to set your password (it works once, for {{ inviteDays }} days):\n{{ url }}\n\n"
                "Afterwards, sign in with your e-mail address or mobile number and that password.\n",
        "tags": [("name", "the person's name"), ("who", "who gave them access"), ("company", "company name"),
                  ("url", "the one-time link"), ("inviteDays", "how many days the link lasts")],
    },
    "candidate.link": {
        "subject": "{% if jobLabel %}{{ jobLabel }} at {{ company }}: your details{% else %}Your details for {{ company }}{% endif %}",
        "body": "Dear {{ name }},\n\nThank you for your interest in {{ company }}{{ what }}. Please fill in your details, "
                "your experience and education{{ skillsNote }}, and attach your CV, using this link (it works for {{ linkDays }} days):\n"
                "{{ url }}\n\nThe first time, the link asks you to create a candidate sign-in with a password of your own. "
                "Afterwards, sign in with your e-mail address and that password, from this link or from the sign-in page "
                "(choose \"Candidate? Sign in\").\n\nNo CV yet? You can fill in the form now and attach it later. "
                "You can save the form and come back to it before you send it.\n",
        "tags": [("name", "candidate's name"), ("company", "company name"), ("jobLabel", "the single job title, if only one"),
                  ("what", "\" for the position of X, Y\" or empty"), ("skillsNote", "skills-rating note, if any jobs"),
                  ("url", "the application-form link"), ("linkDays", "how many days the link lasts")],
    },
    "reimb.paid": {
        "subject": "Expense reimbursement ₹{{ total }} ({{ runNo }})",
        "body": "Dear {{ firstName }},\n\nYour approved expense claims are being reimbursed {{ how }}:\n\n"
                "{% for c in claims %}  {{ c.no }}  {{ c.title }}  ₹{{ c.amount }}\n{% endfor %}\n"
                "Total ₹{{ total }}. Reimbursement run {{ runNo }}, {{ companyName }}.\n",
        "tags": [("firstName", "employee's first name"), ("how", "\"with your salary for ...\" or \"by bank transfer ...\""),
                  ("claims", "list of {no, title, amount} for each claim paid"), ("total", "total amount, formatted"),
                  ("runNo", "the reimbursement run's number"), ("companyName", "company name")],
    },
    "statutory.submitted": {
        "subject": "Approval needed: statutory details change for {{ name }} ({{ no }})",
        "body": "{{ name }} has asked to change their statutory details:\n\n{{ changesLines }}\n\n"
                "{{ docCount }} supporting document(s) attached in PeopleDesk.{{ noteLine }}\n\n"
                "Review and approve: {{ link }}\n\nThe change applies only after HR approves it.",
        "tags": [("name", "employee's name"), ("no", "the request's number"), ("changesLines", "one \"- field: old -> new\" line per change"),
                  ("docCount", "number of supporting documents"), ("noteLine", "\"\\nNote: ...\" or empty"), ("link", "link to the request")],
    },
    "statutory.decided": {
        "subject": "Your statutory details change was {{ outcome }} ({{ no }})",
        "body": "Dear {{ firstName }},\n\nHR has {{ outcome }} your request to change: {{ changeLabels }}.{{ noteBlock }}\n\n"
                "See it in PeopleDesk: {{ link }}",
        "tags": [("firstName", "employee's first name"), ("outcome", "\"approved\" or \"not approved\""), ("no", "the request's number"),
                  ("changeLabels", "comma-joined names of the changed fields"), ("noteBlock", "\"\\n\\nNote from HR: ...\" or empty"), ("link", "link to the request")],
    },
    "comp.launched": {
        "subject": "Salary revision planning is open: {{ cycleName }}",
        "body": "Salary revision planning for {{ cycleName }} is open in PeopleDesk.\n\n"
                "You have a budget for increases in your team. Hand part of it to the managers below you if you wish, "
                "propose each person's new salary and submit your plan{{ deadlineBlock }}.\n\n"
                "New salaries take effect from {{ effective }}.\n\nOpen your plan: {{ link }}",
        "tags": [("cycleName", "the salary-planning cycle's name"), ("deadlineBlock", "\" by DATE\" or empty"),
                  ("effective", "when new salaries take effect"), ("link", "link to the plan")],
    },
    "comp.submitted": {
        "subject": "Salary revision plan from {{ who }} for your review",
        "body": "{{ who }} has submitted their salary revision plan for {{ cycleName }}.\n\n"
                "Review it, discuss, then approve or send it back: {{ link }}",
        "tags": [("who", "the budget holder's name"), ("cycleName", "the cycle's name"), ("link", "link to the budget")],
    },
    "comp.decided": {
        "subject": "Salary revision plan of {{ who }} {{ outcome }} by {{ deciderName }}",
        "body": "{{ deciderName }} has {{ outcomeVerb }} the salary revision plan of {{ who }} for {{ cycleName }}.{{ noteBlock }}\n\n"
                "Open it: {{ link }}",
        "tags": [("who", "the budget holder's name"), ("outcome", "\"approved\" or \"sent back\""), ("outcomeVerb", "\"approved\" or \"sent back for changes\""),
                  ("deciderName", "who decided"), ("cycleName", "the cycle's name"), ("noteBlock", "\"\\n\\nNote: ...\" or empty"), ("link", "link to the budget")],
    },
    "comp.comment": {
        "subject": "New comment on the salary revision plan of {{ who }}",
        "body": "{{ writerName }} wrote:\n\n{{ commentText }}\n\nReply in PeopleDesk: {{ link }}",
        "tags": [("who", "the budget holder's name"), ("writerName", "who wrote the comment"), ("commentText", "the comment"), ("link", "link to the budget")],
    },
    "training.feedback": {
        "subject": "Your training feedback report ({{ trainingsCount }} training{{ 's' if trainingsCount > 1 else '' }})",
        "body": "Dear {{ name }},\n\nThank you for running {{ trainingsCount }} training{{ 's' if trainingsCount > 1 else '' }} with us: "
                "{{ trainingsList }}.\n{{ statsLine }}\n\nRatings\n{{ ratingsBlock }}\n\nAreas to improve\n{{ improveBlock }}"
                "{{ commentsBlock }}{{ likedBlock }}\n\nFeedback is anonymous.\n\nHuman resources",
        "tags": [("name", "trainer's name"), ("trainingsCount", "how many trainings"), ("trainingsList", "comma-joined \"Title (start date)\""),
                  ("statsLine", "attendance/feedback counts"), ("ratingsBlock", "one \"- label: avg\" line per rating"),
                  ("improveBlock", "lowest-rated areas"), ("commentsBlock", "\"What participants would like improved\" section, if any"),
                  ("likedBlock", "\"What participants liked\" section, if any")],
    },
    "report.scheduled": {
        "subject": "{{ reportName }} ({{ when }})",
        "body": "Dear {{ name }},\n\nAttached is the scheduled report \"{{ reportName }}\", as of {{ when }} ({{ rowCount }} row{{ 's' if rowCount != 1 else '' }}).\n\n"
                "Human resources",
        "tags": [("name", "recipient's name, if known, else \"there\""), ("reportName", "the saved report's name"),
                  ("when", "when the report was run"), ("rowCount", "how many rows it returned")],
    },
    # 2.18: the recruitment flow
    "recruit.shortlist": {
        "subject": "Shortlist for {{ job }} ({{ reqNo }}): {{ count }} candidate{{ 's' if count > 1 else '' }} for your approval",
        "body": "Dear {{ firstName }},\n\n{{ sender }} has shortlisted {{ count }} candidate{{ 's' if count > 1 else '' }} for {{ job }} ({{ reqNo }}) "
                "and asks for your approval before interviews are arranged:\n\n{{ candidatesLines }}\n{{ noteBlock }}\n"
                "Approve, reject or hold each candidate: {{ link }}\n",
        "tags": [("firstName", "approver's first name"), ("sender", "who sent the shortlist"), ("job", "requisition title"),
                 ("reqNo", "requisition number"), ("count", "number of candidates"), ("candidatesLines", "one line per candidate"),
                 ("noteBlock", "\"Note: ...\" or empty"), ("link", "link to the approval page")],
    },
    "recruit.selection": {
        "subject": "Final selection for {{ job }} ({{ reqNo }}): your decision",
        "body": "Dear {{ firstName }},\n\nThe interviews for {{ job }} ({{ reqNo }}) are complete. {{ sender }} proposes:\n\n{{ candidatesLines }}\n\n"
                "Agree or decide otherwise for each candidate: {{ link }}\n",
        "tags": [("firstName", "hiring manager's first name"), ("sender", "who made the proposal"), ("job", "requisition title"),
                 ("reqNo", "requisition number"), ("candidatesLines", "one line per candidate with the proposal"), ("link", "link to the final selection")],
    },
    "recruit.referral": {
        "subject": "Your view needed on {{ candidate }} for {{ job }}",
        "body": "Dear {{ firstName }},\n\n{{ sender }} interviewed {{ candidate }} for {{ job }} ({{ round }}) and refers the decision to you."
                "{{ questionBlock }}\n\nSee the CV and the interview feedback, then recommend hiring, rejection or hold: {{ link }}\n",
        "tags": [("firstName", "first name of the person referred to"), ("sender", "the interviewer"), ("candidate", "candidate's name"),
                 ("job", "requisition title"), ("round", "interview round"), ("questionBlock", "\"\\n\\nQuestion: ...\" or empty"), ("link", "link to the candidate")],
    },
    # 2.19: the conversation with a candidate, both ways
    "candidate.message": {
        "subject": "{{ subject }}",
        "body": "Dear {{ firstName }},\n\n{{ text }}\n{{ filesLine }}\n{{ replyLine }}\n{{ link }}\n\n{{ sender }}\n{{ company }}\n",
        "tags": [("firstName", "candidate's first name"), ("subject", "the message's subject"), ("text", "the message"), ("filesLine", "names of files attached, or empty"),
                 ("replyLine", "how to reply"), ("link", "the sign-in page"), ("sender", "who wrote it"), ("company", "company name")],
    },
    "candidate.toHr": {
        "subject": "{{ candidate }}: {{ subject }}",
        "body": "Dear {{ firstName }},\n\n{{ candidate }} ({{ job }}) wrote{{ via }}:\n\n{{ text }}\n{{ filesLine }}\n{{ replyLine }}\n{{ link }}\n",
        "tags": [("firstName", "your first name"), ("candidate", "candidate's name"), ("job", "the job"), ("subject", "the message's subject"), ("via", "\" in the candidate portal\" or \" by e-mail\""),
                 ("text", "the message"), ("filesLine", "files attached, or empty"), ("replyLine", "how to answer"), ("link", "the candidate in PeopleDesk")],
    },
    "candidate.notice.interview": {
        "subject": "{{ headline }}: {{ job }}, {{ when }}",
        "body": "{{ intro }}\n\n{{ round }}: {{ when }} ({{ duration }} minutes)\n{{ where }}\n{{ panelLine }}\n\n{{ outro }}",
        "tags": [("headline", "Interview, Interview moved or Interview cancelled"), ("intro", "first sentence"), ("job", "the job"), ("round", "e.g. First round"),
                 ("when", "date and time"), ("duration", "minutes"), ("where", "the link, venue or phone"), ("panelLine", "who interviews, or empty"), ("outro", "last sentence")],
    },
    "candidate.notice.offer": {
        "subject": "Your offer: {{ job }}",
        "body": "We are pleased to offer you the position of {{ job }}{{ roundWord }}. Your offer letter {{ letterNo }} is in your candidate portal: "
                "read it there, then accept it, decline it or ask for changes.{{ expiryLine }}",
        "tags": [("job", "the job"), ("roundWord", "\" (revised offer)\" or empty"), ("letterNo", "offer letter number"), ("expiryLine", "\" Please reply by ...\" or empty")],
    },
}

MAIL_KEYS = list(DEFAULTS)


def catalogue() -> list[dict]:
    return [{"mailKey": k, "subject": v["subject"], "body": v["body"], "tags": v["tags"]} for k, v in DEFAULTS.items()]


def _lookup(conn, company_id, mail_key: str) -> dict | None:
    """The company's own active override for this key, else a global one (companyId left blank by a
    group administrator applies to every company, same convention as document templates)."""
    rows = conn.execute(text(f"SELECT data, company_id FROM {repo.BY_NAME['emailTemplates'].table} WHERE mailKey=:k AND (company_id=:c OR company_id IS NULL)"),
                        {"k": mail_key, "c": company_id}).fetchall()
    cands = [repo.loads(d) for d, _ in rows]
    own = next((t for t, (_, c) in zip(cands, rows) if c == company_id and t.get("active", True)), None)
    if own:
        return own
    # a group-wide template (set by the group administrator) is not used for a company that registered
    # itself: that company is private, and its mail says only what its own HR wrote, or the default
    if company_id and company_id in repo.registered_companies(conn):
        return None
    return next((t for t, (_, c) in zip(cands, rows) if c is None and t.get("active", True)), None)


def render(conn, company_id, mail_key: str, ctx: dict) -> tuple[str, str]:
    """(subject, body) for one e-mail: the company's own template if it has an active one for this
    key, else a group-wide one, else the built-in default -- all rendered the same way, so nothing
    regresses when no override exists."""
    d = DEFAULTS.get(mail_key)
    if d is None:
        raise ValueError(f"unknown mail key: {mail_key}")
    t = _lookup(conn, company_id, mail_key)
    subject_tpl = (t.get("subject") if t else None) or d["subject"]
    body_tpl = (t.get("body") if t else None) or d["body"]
    try:
        return _render_str(subject_tpl, ctx).strip(), _render_str(body_tpl, ctx)
    except Exception as e:  # noqa: BLE001 - a broken or unsafe edited template must not stop the e-mail
        logging.getLogger("peopledesk").warning("E-mail template %s of company %s could not be used (%s): sending the default", mail_key, company_id, e)
        return _render_str(d["subject"], ctx).strip(), _render_str(d["body"], ctx)
