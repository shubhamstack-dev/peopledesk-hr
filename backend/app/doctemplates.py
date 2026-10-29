"""
Document templates: Word (.docx) files whose placeholders are filled from the database.

An HR administrator uploads a .docx written in Word with placeholders such as
    Dear {{ salutation }} {{ employee_name }},
    Your annual CTC is revised to {{ ctc_annual }} ({{ ctc_annual_words }}) from {{ effective_date }}.
and, for tables, rows repeated with
    {%tr for c in salary_components %} {{ c.name }} {{ c.monthly }} {{ c.annual }} {%tr endfor %}

Each placeholder is mapped (on the template record, field `mapping`) to one of:
    {"source": "field", "key": "<catalogue key>"}      a value read from the database (FIELDS below)
    {"source": "emp",   "key": "<employee JSON key>"}  any field stored on the employee record
    {"source": "text",  "value": "..."}                 the same fixed text every time
    {"source": "ask",   "label": "...", "type": "text|date|number|money"}   typed in when the document is made
    {"source": "blank"}                                 left empty
A placeholder without a mapping whose name is a catalogue key is filled from that key.

The values are read on the server from MySQL, so a document always shows what is saved,
not what a browser happens to hold. Rendering uses docxtpl in a sandboxed Jinja
environment with XML escaping on, so neither a template nor a value can break out of the document.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date

from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import text

from . import repo

MAX_TEMPLATE_MB = 10
PLACEHOLDER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
EMP_TYPES = {"permanent": "Permanent", "probation": "Probation", "contract": "Fixed-term contract", "intern": "Intern"}


# ---------------------------------------------------------------- formatting (Indian conventions)
def _d(iso) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10]) if iso else None
    except ValueError:
        return None


def dmy(iso) -> str:
    d = _d(iso)
    return d.strftime("%d-%m-%Y") if d else ""


def long_date(iso) -> str:
    d = _d(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}" if d else ""


def inr(n, symbol=True) -> str:
    """12,34,567 with Indian digit grouping."""
    try:
        v = round(float(n))
    except (TypeError, ValueError):
        return ""
    neg, s = v < 0, str(abs(int(v)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        s = f"{head},{tail}"
    return ("-" if neg else "") + ("₹ " if symbol else "") + s


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
         "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _two(n):
    return _ONES[n] if n < 20 else _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def _three(n):
    h, r = divmod(n, 100)
    return " ".join(x for x in ((_ONES[h] + " hundred") if h else "", _two(r) if r else "") if x)


def in_words(n) -> str:
    """Rupees in words with lakh and crore: 1250000 -> 'Rupees twelve lakh fifty thousand only'."""
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "Rupees zero only"
    parts, crore = [], v // 10_000_000
    v %= 10_000_000
    if crore:
        parts.append((in_words(crore)[7:-5] if crore > 99 else _two(crore)) + " crore")
    for size, name in ((100_000, "lakh"), (1000, "thousand")):
        q, v = divmod(v, size)
        if q:
            parts.append(f"{_two(q)} {name}")
    if v:
        parts.append(_three(v))
    return "Rupees " + " ".join(parts) + " only"


def fy_label(iso) -> str:
    d = _d(iso) or date.today()
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


# ---------------------------------------------------------------- the field catalogue
# key, label, group. The value comes from _values() below.
FIELDS = [
    ("employee_name", "Full name", "Employee"), ("first_name", "First name", "Employee"), ("last_name", "Last name", "Employee"),
    ("salutation", "Mr / Ms (from gender)", "Employee"), ("emp_no", "Employee number", "Employee"),
    ("email", "Work e-mail", "Employee"), ("personal_email", "Personal e-mail", "Employee"), ("phone", "Mobile", "Employee"),
    ("gender", "Gender", "Employee"), ("dob", "Date of birth", "Employee"), ("blood_group", "Blood group", "Employee"),
    ("address", "Address: street and area", "Employee"), ("city", "City", "Employee"), ("state", "State", "Employee"),
    ("pin", "PIN code", "Employee"), ("address_full", "Full address (several lines)", "Employee"),
    ("emergency_contact", "Emergency contact", "Employee"),

    ("designation", "Designation", "Job"), ("department", "Department", "Job"), ("grade", "Grade", "Job"),
    ("location", "Location", "Job"), ("employment_type", "Employment type", "Job"),
    ("doj", "Date of joining (dd-mm-yyyy)", "Job"), ("doj_long", "Date of joining (29 October 2026)", "Job"),
    ("probation_end", "Probation ends", "Job"), ("years_of_service", "Years of service", "Job"),
    ("manager_name", "Reporting manager", "Job"), ("manager_designation", "Manager's designation", "Job"),
    ("manager_email", "Manager's e-mail", "Job"), ("hod_name", "Head of department", "Job"),

    ("ctc_annual", "Annual fixed CTC (₹ 12,00,000)", "Pay"), ("ctc_annual_words", "Annual fixed CTC in words", "Pay"),
    ("ctc_annual_number", "Annual fixed CTC (number only)", "Pay"), ("ctc_monthly", "Monthly CTC", "Pay"),
    ("variable_pay", "Annual variable pay", "Pay"), ("total_ctc", "Fixed plus variable", "Pay"),
    ("salary_effective", "Current salary effective from", "Pay"), ("salary_reason", "Reason for current salary", "Pay"),
    ("previous_ctc", "Previous annual CTC", "Pay"), ("increment_amount", "Increase over previous CTC", "Pay"),
    ("increment_pct", "Increase over previous CTC (%)", "Pay"),
    ("gross_monthly", "Gross monthly salary", "Pay"), ("employer_pf_monthly", "Employer PF per month", "Pay"),
    ("salary_components", "Salary breakup rows (for a table loop)", "Pay"),

    ("pan", "PAN", "Statutory and bank"), ("uan", "UAN", "Statutory and bank"), ("pf_no", "PF member ID", "Statutory and bank"),
    ("esi_no", "ESI IP number", "Statutory and bank"), ("aadhaar_masked", "Aadhaar (last 4 digits only)", "Statutory and bank"),
    ("bank_name", "Bank", "Statutory and bank"), ("bank_account", "Bank account number", "Statutory and bank"),
    ("ifsc", "IFSC", "Statutory and bank"),

    ("resignation_date", "Resignation date", "Exit"), ("last_working_day", "Last working day", "Exit"),
    ("last_working_day_long", "Last working day (long)", "Exit"), ("exit_type", "Resignation or termination", "Exit"),

    ("company_name", "Company name", "Company"), ("company_legal_name", "Legal name", "Company"),
    ("company_address", "Address", "Company"), ("company_code", "Code", "Company"), ("company_pan", "PAN", "Company"),
    ("company_tan", "TAN", "Company"), ("company_pf_code", "PF establishment code", "Company"),
    ("company_esi_code", "ESI code", "Company"), ("group_name", "Group name", "Company"),

    ("today", "Date of the document (dd-mm-yyyy)", "Document"), ("today_long", "Date of the document (29 October 2026)", "Document"),
    ("letter_no", "Letter number (from the document type)", "Document"), ("document_type", "Document type", "Document"),
    ("financial_year", "Financial year (2026-27)", "Document"),
    ("issued_by", "Issued by (signed-in HR)", "Document"), ("issued_by_designation", "Issuer's designation", "Document"),
]
FIELD_KEYS = {k for k, _l, _g in FIELDS}
LIST_FIELDS = {"salary_components"}


def catalogue() -> list[dict]:
    return [{"key": k, "label": l, "group": g, "list": k in LIST_FIELDS} for k, l, g in FIELDS]


# ---------------------------------------------------------------- reading a template
class TemplateProblem(ValueError):
    pass


def _check_docx(data: bytes):
    if len(data) > MAX_TEMPLATE_MB * 1024 * 1024:
        raise TemplateProblem(f"Templates can be up to {MAX_TEMPLATE_MB} MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if "word/document.xml" not in names:
                raise TemplateProblem("That is not a Word document. Save it as .docx (Word 2007 or later) and upload it again.")
            if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                raise TemplateProblem("This document is too large when unpacked.")
    except zipfile.BadZipFile:
        raise TemplateProblem("That is not a .docx file. Older .doc files must be saved as .docx in Word first.")


def _env() -> SandboxedEnvironment:
    # autoescape: values with & < > cannot break the Word XML
    return SandboxedEnvironment(autoescape=True)


def scan(data: bytes) -> dict:
    """Placeholders used in a template: {placeholders, known, unknown}."""
    from docxtpl import DocxTemplate
    _check_docx(data)
    try:
        tpl = DocxTemplate(io.BytesIO(data))
        found = sorted(tpl.get_undeclared_template_variables(_env()))
    except TemplateError as e:
        raise TemplateProblem(_explain(e))
    except Exception as e:  # noqa: BLE001  damaged files
        raise TemplateProblem(f"The document could not be read: {e}")
    return {"placeholders": found, "known": [p for p in found if p in FIELD_KEYS], "unknown": [p for p in found if p not in FIELD_KEYS]}


def _explain(e: TemplateError) -> str:
    msg = getattr(e, "message", None) or str(e)
    ctx = " ".join(x.strip() for x in getattr(e, "docx_context", []) or [] if x.strip())[:160]
    hint = " Placeholders are written {{ name }}, with letters, digits and underscores only (no spaces)."
    return f"There is a mistake in a placeholder: {msg}.{hint}" + (f" Near: “{ctx}”" if ctx else "")


# ---------------------------------------------------------------- values from the database
def _one(conn, table: str, rec_id):
    if not rec_id:
        return {}
    row = conn.execute(text(f"SELECT data FROM {table} WHERE id=:i"), {"i": rec_id}).scalar()
    return repo.loads(row) or {}


def _name(e: dict) -> str:
    return f"{e.get('firstName', '')} {e.get('lastName', '')}".strip()


def _salary(e: dict, on: str):
    hist = sorted((s for s in e.get("salaryHist") or [] if str(s.get("effective", "")) <= on), key=lambda s: s.get("effective", ""), reverse=True)
    return (hist[0] if hist else {}), (hist[1] if len(hist) > 1 else {})


def values(conn, emp_id: str, me: dict, on: str | None = None, computed: dict | None = None, doc_type: dict | None = None) -> dict:
    """Every catalogue value for one employee, read from MySQL."""
    on = on or date.today().isoformat()
    e = _one(conn, "employees", emp_id)
    if not e:
        raise TemplateProblem("That employee does not exist.")
    co = _one(conn, "companies", e.get("companyId"))
    dept, desig = _one(conn, "departments", e.get("deptId")), _one(conn, "designations", e.get("desigId"))
    mgr = _one(conn, "employees", e.get("managerId"))
    hod = _one(conn, "employees", dept.get("headId"))
    group = repo.get_singleton(conn, "group") or {}
    me_desig = _one(conn, "designations", me.get("desigId"))
    cur, prev = _salary(e, on)
    ctc, var, pctc = float(cur.get("ctc") or 0), float(cur.get("variable") or 0), float(prev.get("ctc") or 0)
    exit_ = (repo.loads(conn.execute(text("SELECT data FROM exits WHERE emp_id=:i ORDER BY created_at DESC LIMIT 1"), {"i": emp_id}).scalar()) or {})
    city = e.get("addrCity") if e.get("addrCity") and e.get("addrCity") != "Other" else e.get("addrCityOther", "")
    doj = _d(e.get("doj"))
    comp = computed or {}
    aad = re.sub(r"\D", "", str(e.get("aadhaar") or ""))

    v = {
        "employee_name": _name(e), "first_name": e.get("firstName", ""), "last_name": e.get("lastName", ""),
        "salutation": {"M": "Mr.", "F": "Ms."}.get(e.get("gender"), ""), "emp_no": e.get("empNo", ""),
        "email": e.get("email", ""), "personal_email": e.get("personalEmail", ""), "phone": e.get("phone", ""),
        "gender": {"M": "Male", "F": "Female", "O": "Other"}.get(e.get("gender"), ""), "dob": dmy(e.get("dob")),
        "blood_group": e.get("blood", ""), "address": e.get("address", ""), "city": city or "", "state": e.get("addrState", ""),
        "pin": e.get("addrPin", ""),
        "address_full": "\n".join(x for x in (e.get("address", ""), ", ".join(x for x in (city, e.get("addrState", "")) if x) + (f" {e.get('addrPin')}" if e.get("addrPin") else "")) if x and x.strip()),
        "emergency_contact": ", ".join(x for x in (e.get("emergencyName", ""), e.get("emergencyRelation", ""), e.get("emergencyPhone", "")) if x),

        "designation": desig.get("name", ""), "department": dept.get("name", ""),
        "grade": _one(conn, "grades", e.get("gradeId")).get("name", ""), "location": _one(conn, "locations", e.get("locationId")).get("name", ""),
        "employment_type": EMP_TYPES.get(e.get("empType"), e.get("empType", "")), "doj": dmy(e.get("doj")), "doj_long": long_date(e.get("doj")),
        "probation_end": dmy(e.get("probationEnd")),
        "years_of_service": f"{((_d(on) or date.today()) - doj).days / 365.25:.1f}" if doj else "",
        "manager_name": _name(mgr), "manager_designation": _one(conn, "designations", mgr.get("desigId")).get("name", "") if mgr else "",
        "manager_email": mgr.get("email", ""), "hod_name": _name(hod),

        "ctc_annual": inr(ctc) if ctc else "", "ctc_annual_words": in_words(ctc) if ctc else "", "ctc_annual_number": inr(ctc, False) if ctc else "",
        "ctc_monthly": inr(ctc / 12) if ctc else "", "variable_pay": inr(var) if var else "", "total_ctc": inr(ctc + var) if ctc else "",
        "salary_effective": dmy(cur.get("effective")), "salary_reason": cur.get("reason", ""),
        "previous_ctc": inr(pctc) if pctc else "", "increment_amount": inr(ctc - pctc) if pctc else "",
        "increment_pct": f"{(ctc - pctc) * 100 / pctc:.1f}%" if pctc else "",
        # worked out in the browser by the payroll rules (pay components, PF, ESI) and sent with the request
        "gross_monthly": inr(comp["gross_monthly"]) if comp.get("gross_monthly") else "",
        "employer_pf_monthly": inr(comp["employer_pf_monthly"]) if comp.get("employer_pf_monthly") else "",
        "salary_components": [{"name": str(c.get("name", ""))[:120], "code": str(c.get("code", ""))[:20],
                               "monthly": inr(c.get("monthly")), "annual": inr(c.get("annual"))}
                              for c in (comp.get("salary_components") or [])[:60] if isinstance(c, dict)],

        "pan": e.get("pan", ""), "uan": e.get("uan", ""), "pf_no": e.get("pfNo", ""), "esi_no": e.get("esiNo", ""),
        "aadhaar_masked": f"XXXX XXXX {aad[-4:]}" if len(aad) >= 4 else "", "bank_name": e.get("bankName", ""),
        "bank_account": e.get("bankAcc", ""), "ifsc": e.get("ifsc", ""),

        "resignation_date": dmy(exit_.get("resignDate")), "last_working_day": dmy(exit_.get("lwd")),
        "last_working_day_long": long_date(exit_.get("lwd")),
        "exit_type": {"resignation": "Resignation", "termination": "Termination"}.get(exit_.get("type"), exit_.get("type", "")),

        "company_name": co.get("name", ""), "company_legal_name": co.get("legalName") or co.get("name", ""),
        "company_address": co.get("address", ""), "company_code": co.get("code", ""), "company_pan": co.get("pan", ""),
        "company_tan": co.get("tan", ""), "company_pf_code": co.get("pfCode", ""), "company_esi_code": co.get("esiCode", ""),
        "group_name": group.get("name", ""),

        "today": dmy(on), "today_long": long_date(on), "letter_no": "DRAFT", "document_type": (doc_type or {}).get("name", ""),
        "financial_year": fy_label(on), "issued_by": _name(me), "issued_by_designation": me_desig.get("name", ""),
    }
    return {"emp": e, "company": co, "values": v}


def next_letter_no(conn, doc_type: dict, company: dict, on: str) -> str:
    """PREFIX/COMPANY/2026-27/0001. The counter is atomic in MySQL, so two people never get the same number."""
    prefix = re.sub(r"[^A-Za-z0-9-]", "", str(doc_type.get("prefix") or ""))[:12]
    if not prefix:
        return ""
    fy = fy_label(on)
    key = f"{prefix}|{company.get('id', '')}|{fy}"
    conn.execute(text("INSERT INTO doc_counters (k, n) VALUES (:k, LAST_INSERT_ID(1)) ON DUPLICATE KEY UPDATE n = LAST_INSERT_ID(n + 1)"), {"k": key})
    n = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return f"{prefix}/{company.get('code') or 'CO'}/{fy}/{int(n):04d}"


# ---------------------------------------------------------------- filling a template
def _fmt_asked(val, kind: str) -> str:
    val = "" if val is None else str(val).strip()[:2000]
    if not val:
        return ""
    if kind == "date":
        return long_date(val) if _d(val) else val
    if kind == "money":
        try:
            return inr(float(val.replace(",", "")))
        except ValueError:
            return val
    return val


def build_context(tpl: dict, base: dict, emp: dict, asked: dict) -> tuple[dict, list]:
    """The context for the template and the placeholders that came out empty."""
    mapping = tpl.get("mapping") or {}
    ctx, empty = {}, []
    for ph in tpl.get("placeholders") or []:
        if not PLACEHOLDER.match(ph):
            continue
        m = mapping.get(ph) or ({"source": "field", "key": ph} if ph in FIELD_KEYS else {"source": "ask", "label": ph})
        src = m.get("source")
        if src == "field":
            val = base.get(m.get("key"), "")
        elif src == "emp":
            raw = emp.get(str(m.get("key", "")))
            val = dmy(raw) if isinstance(raw, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", raw) else ("" if isinstance(raw, (dict, list)) or raw is None else str(raw))
        elif src == "text":
            val = str(m.get("value", ""))
        elif src == "ask":
            val = _fmt_asked(asked.get(ph), m.get("type", "text"))
        else:
            val = ""
        if val in ("", None, []):
            empty.append(ph)
        ctx[ph] = val
    return ctx, empty


def render(data: bytes, context: dict) -> bytes:
    from docxtpl import DocxTemplate, Listing
    # several lines (addresses): Word line breaks instead of one run-on line
    ctx = {k: (Listing(v) if isinstance(v, str) and "\n" in v else v) for k, v in context.items()}
    try:
        tpl = DocxTemplate(io.BytesIO(data))
        tpl.render(ctx, _env())
        out = io.BytesIO()
        tpl.save(out)
        return out.getvalue()
    except TemplateError as e:
        raise TemplateProblem(_explain(e))


def safe_filename(*parts) -> str:
    base = " - ".join(p for p in parts if p)
    base = re.sub(r"[^\w .()-]+", "_", base).strip(" ._")[:120] or "document"
    return f"{base}.docx"


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
