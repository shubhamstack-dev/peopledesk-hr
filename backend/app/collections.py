"""
Where each part of the HR data lives in MySQL.

The React app works with one object per record (the same shape the original
single-file app used). Each record is stored whole in a JSON column, and the
fields the server filters, joins or checks permissions on are copied into
ordinary indexed columns next to it. The JSON stays the source of truth; the
columns are rewritten from it on every save.
"""
from dataclasses import dataclass, field
import re

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")


@dataclass(frozen=True)
class Coll:
    name: str                      # key in the app state, e.g. "leaveReqs"
    table: str                     # MySQL table
    extra: dict = field(default_factory=dict)   # column -> (json key, kind)
    company_from_id: bool = False  # companies: the record's own id is its company
    emp_from_id: bool = False      # employees: the record's own id is the employee


# kind: "str" (VARCHAR), "date" (DATE, ISO only), "month" (CHAR(7))
COLLS = [
    Coll("companies", "companies", {"code": ("code", "str"), "name": ("name", "str"), "domain": ("domain", "str")}, company_from_id=True),
    Coll("employees", "employees", {
        "emp_no": ("empNo", "str"), "email": ("email", "str"), "first_name": ("firstName", "str"),
        "last_name": ("lastName", "str"), "role": ("role", "str"), "status": ("status", "str"),
        "manager_id": ("managerId", "str"), "dept_id": ("deptId", "str"), "doj": ("doj", "date"),
    }, emp_from_id=True),
    Coll("depts", "departments", {"name": ("name", "str")}),
    Coll("desigs", "designations", {"name": ("name", "str")}),
    Coll("grades", "grades", {"name": ("name", "str")}),
    Coll("locations", "locations", {"name": ("name", "str")}),
    Coll("holidays", "holidays", {"day": ("date", "date"), "name": ("name", "str")}),
    Coll("leaveTypes", "leave_types", {"code": ("code", "str")}),
    Coll("leaveReqs", "leave_requests", {"status": ("status", "str"), "date_from": ("from", "date"), "date_to": ("to", "date")}),
    Coll("leaveAdj", "leave_adjustments"),
    Coll("shifts", "shifts", {"code": ("code", "str")}),
    Coll("punches", "punches", {"day": ("date", "date")}),
    Coll("regs", "attendance_regularisations", {"day": ("date", "date"), "status": ("status", "str")}),
    Coll("cycles", "review_cycles", {"stage": ("stage", "str")}),
    Coll("goals", "goals", {"cycle_id": ("cycleId", "str"), "status": ("status", "str")}),
    Coll("reviews", "reviews", {"cycle_id": ("cycleId", "str")}),
    Coll("feedback", "feedback", {"from_emp": ("from", "str"), "to_emp": ("to", "str"), "type": ("type", "str")}),
    Coll("posts", "posts"),
    Coll("payComps", "pay_components", {"code": ("code", "str")}),
    Coll("payInputs", "pay_inputs", {"month": ("month", "month"), "code": ("code", "str")}),
    Coll("payRuns", "pay_runs", {"month": ("month", "month"), "status": ("status", "str")}),
    Coll("declarations", "tax_declarations", {"fy": ("fy", "str")}),
    Coll("exits", "exits", {"status": ("status", "str"), "lwd": ("lwd", "date")}),
    Coll("reqs", "job_requisitions", {"req_no": ("no", "str"), "status": ("status", "str")}),
    Coll("cands", "candidates", {"email": ("email", "str")}),
    Coll("apps", "applications", {"req_id": ("reqId", "str"), "cand_id": ("candId", "str"), "stage": ("stage", "str")}),
    Coll("interviews", "interviews", {"app_id": ("appId", "str"), "day": ("date", "date"), "status": ("status", "str")}),
    Coll("otRecs", "overtime_records", {"day": ("date", "date"), "status": ("status", "str")}),
    Coll("shiftPatterns", "shift_patterns"),
    # v2: approvals, expenses, performance templates, onboarding and assets
    Coll("requests", "approval_requests", {"kind": ("kind", "str"), "status": ("status", "str")}),
    Coll("expenseCats", "expense_categories", {"name": ("name", "str")}),
    Coll("expenseClaims", "expense_claims", {"claim_no": ("no", "str"), "status": ("status", "str")}),
    Coll("perfTemplates", "performance_templates", {"name": ("name", "str")}),
    Coll("onboardings", "onboardings", {"status": ("status", "str"), "doj": ("doj", "date")}),
    Coll("onboardTemplates", "onboarding_templates", {"dept": ("dept", "str")}),
    Coll("assets", "assets", {"asset_type": ("type", "str"), "tag": ("tag", "str"), "status": ("status", "str")}),
]
BY_NAME = {c.name: c for c in COLLS}

# Single objects kept in app_kv
SINGLETONS = ("group", "settings", "stat", "seq")

STR_LEN = 255


def column_values(coll: Coll, rec: dict) -> dict:
    """Indexed columns for one record, taken from its JSON."""
    def s(v):
        if v is None or v == "" or isinstance(v, (dict, list)):
            return None
        return str(v)[:STR_LEN]

    out = {
        "company_id": s(rec.get("id") if coll.company_from_id else rec.get("companyId")),
        "emp_id": s(rec.get("id") if coll.emp_from_id else rec.get("empId")),
    }
    for col, (key, kind) in coll.extra.items():
        v = rec.get(key)
        if kind == "date":
            out[col] = v if isinstance(v, str) and ISO_DATE.match(v) else None
        elif kind == "month":
            out[col] = v if isinstance(v, str) and ISO_MONTH.match(v) else None
        else:
            out[col] = s(v)
    return out
