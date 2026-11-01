"""
Training and development: the rules the server enforces.

HR plans trainings (trainings): internal ones run by employees, external ones by an outside trainer. People
take part through one enrolment each (trainingEnrols): they ask for a place and their manager approves, or a
manager or HR enrols them. The trainer marks attendance. Before or after, participants answer the training's
questionnaire, which the server scores; after attending they give feedback (trainingFeedback), kept apart so
trainers see it without names. Some time after the training each participant's manager rates how well it
worked. Training content is visible only to people who attended, the trainers and HR.

Development needs (trainingNeeds) follow the normal workflow rules: the employee, their managers and HR.
"""

ACTIVE = {"requested", "approved", "attended", "absent"}
WITHDRAWABLE = {"requested", "approved"}
CONTENT_MIME = ("image/", "application/pdf", "text/plain", "text/csv", "video/", "audio/", "application/zip", "application/x-zip-compressed",
                "application/msword", "application/vnd.ms-", "application/vnd.openxmlformats-officedocument.", "application/vnd.oasis.opendocument.")


class Problem(Exception):
    pass


def is_trainer(tr: dict | None, emp_id: str) -> bool:
    return bool(tr) and tr.get("kind") == "internal" and emp_id in (tr.get("trainerIds") or [])


def score(quiz: dict | None, answers) -> dict:
    """Marks a questionnaire. answers: {question id: chosen option index}."""
    qs = [q for q in (quiz or {}).get("questions") or [] if q.get("options")]
    answers = answers if isinstance(answers, dict) else {}
    right = sum(1 for q in qs if str(answers.get(q.get("id"))) == str(q.get("correct")))
    total = len(qs)
    pct = round(right * 100 / total) if total else 0
    return {"score": right, "total": total, "pct": pct, "passed": pct >= int((quiz or {}).get("pass") or 0)}


def _changed(new: dict, old: dict) -> set:
    return {k for k in set(new) | set(old) if new.get(k) != old.get(k)} - {"log", "updatedAt", "updatedBy"}


# ---------------------------------------------------------------- trainings
TRAINER_MAY = {"materials", "quiz", "status", "completedAt", "completedBy"}


def check_training(new: dict, old: dict | None, me: str):
    """HR may change anything (checked before this). An internal trainer may add content, set the questionnaire
    and mark the training completed."""
    if old is None or not is_trainer(old, me):
        raise Problem("only HR plans trainings")
    if _changed(new, old) - TRAINER_MAY:
        raise Problem("a trainer can change only the content, the questionnaire and completion")
    if new.get("status") != old.get("status") and not (old.get("status") == "scheduled" and new.get("status") == "completed"):
        raise Problem("a trainer can only mark the training completed")
    return new


# ---------------------------------------------------------------- enrolments
def check_enrol(new: dict, old: dict | None, me: str, line: set, tr: dict | None, enrols: list, emps: dict):
    if not tr:
        raise Problem("that training does not exist")
    if old and new.get("trainingId") != old.get("trainingId"):
        raise Problem("an enrolment cannot move to another training")
    subject = (old or new).get("empId")
    if new.get("empId") != subject:
        raise Problem("an enrolment cannot move to another person")
    if (emps.get(subject) or {}).get("companyId") != tr.get("companyId"):
        raise Problem("the training is for another company")
    self_, mgr, trainer = subject == me, subject in line, is_trainer(tr, me)
    if old and self_ and "mgrReview" not in new and old.get("mgrReview"):
        new = {**new, "mgrReview": old["mgrReview"]}     # hidden from the employee, so it comes back without it

    if old is None:
        if tr.get("status") != "scheduled":
            raise Problem("this training is not taking enrolments")
        if any(x.get("empId") == subject and x.get("id") != new.get("id") and x.get("status") in ACTIVE for x in enrols):
            raise Problem("already enrolled")
        for k in ("attendance", "quiz", "mgrReview", "decidedBy"):
            if new.get(k):
                raise Problem("a new enrolment starts empty")
        if new.get("by") != me:
            raise Problem("enrol people as yourself")
        if mgr and new.get("status") == "approved":
            return new
        if self_ and new.get("status") == "requested":
            return new
        raise Problem("ask for a place for yourself, or enrol people in your team")

    changed = _changed(new, old)
    if not changed:
        return new
    allowed, st_from, st_to = set(), old.get("status"), new.get("status")
    if self_:
        allowed |= {"quiz"}
        if st_to == "withdrawn" and st_from in WITHDRAWABLE:
            allowed |= {"status", "decidedAt", "decidedBy", "note"}
    if mgr and not self_:
        allowed |= {"mgrReview"}
        if (st_from == "requested" and st_to in ("approved", "rejected")) or (st_to == "withdrawn" and st_from in WITHDRAWABLE):
            allowed |= {"status", "decidedAt", "decidedBy", "note"}
    if trainer and not self_:
        allowed |= {"attendance", "hours"}
        if st_from in ("approved", "attended", "absent") and st_to in ("attended", "absent"):
            allowed |= {"status"}
    if changed - allowed:
        who = "the trainer" if "attendance" in changed or st_to in ("attended", "absent") else "the participant's manager" if {"mgrReview"} & changed or st_to in ("approved", "rejected") else "someone else"
        raise Problem(f"only {who} can change that")
    if "mgrReview" in changed:
        rv = new.get("mgrReview") or {}
        if old.get("status") != "attended" or rv.get("by") != me or any(not (isinstance(v, int) and 1 <= v <= 5) for v in (rv.get("ratings") or {}).values()):
            raise Problem("rate a training your team member attended, 1 to 5, as yourself")
    if "quiz" in changed:
        oq, nq = old.get("quiz") or {}, new.get("quiz") or {}
        for phase in set(oq) | set(nq):
            if oq.get(phase) == nq.get(phase):
                continue
            if oq.get(phase):
                raise Problem("the questionnaire was already answered")
            if phase not in ("pre", "post") or not (tr.get("quiz") or {}).get(phase):
                raise Problem("this training has no such questionnaire")
            if phase == "pre" and st_from not in ("requested", "approved"):
                raise Problem("the pre-training questionnaire is answered before the training")
            if phase == "post" and st_from != "attended":
                raise Problem("the post-training questionnaire is for people who attended")
            ans = (nq.get(phase) or {}).get("answers") or {}
            nq[phase] = {**(nq.get(phase) or {}), **score(tr.get("quiz"), ans), "answers": ans}   # marked here, whatever the browser sent
        new["quiz"] = nq
    return new


# ---------------------------------------------------------------- feedback
def check_feedback(new: dict, old: dict | None, me: str, tr: dict | None, enrols: list, others: list):
    if not tr:
        raise Problem("that training does not exist")
    if new.get("empId") != me or (old and old.get("empId") != me):
        raise Problem("feedback can only be given as yourself")
    if old and old.get("trainingId") != new.get("trainingId"):
        raise Problem("feedback cannot move to another training")
    if not any(x.get("empId") == me and x.get("status") == "attended" for x in enrols):
        raise Problem("feedback is from people who attended")
    if any(f.get("empId") == me and f.get("id") != new.get("id") for f in others):
        raise Problem("you have already given feedback")
    for v in (new.get("ratings") or {}).values():
        if not (isinstance(v, int) and 1 <= v <= 5):
            raise Problem("ratings are from 1 to 5")
    return new


# ---------------------------------------------------------------- reading
def visible(st: dict, ctx) -> None:
    emp_co = {e["id"]: e.get("companyId") for e in st["employees"]}
    hr = ctx.is_hr_for
    by_tr = {t["id"]: t for t in st.get("trainings", [])}
    enrols = st.get("trainingEnrols", [])
    attended = {x.get("trainingId") for x in enrols if x.get("empId") == ctx.id and x.get("status") == "attended"}
    mine_co = ctx.me.get("companyId")

    st["trainingEnrols"] = [dict(x) for x in enrols if hr(emp_co.get(x.get("empId"))) or x.get("empId") == ctx.id
                            or x.get("empId") in ctx.line or is_trainer(by_tr.get(x.get("trainingId")), ctx.id)]
    for x in st["trainingEnrols"]:
        if x.get("empId") == ctx.id and not hr(emp_co.get(x.get("empId"))):
            x.pop("mgrReview", None)                 # the manager's rating is for the manager, the trainer and HR
    fb = []
    for f in st.get("trainingFeedback", []):
        t = by_tr.get(f.get("trainingId"))
        if hr((t or {}).get("companyId")) or f.get("empId") == ctx.id:
            fb.append(f)
        elif is_trainer(t, ctx.id):
            fb.append({k: v for k, v in f.items() if k not in ("empId", "by")})   # trainers see feedback without names
    st["trainingFeedback"] = fb
    out = []
    for t in st.get("trainings", []):
        trainer = is_trainer(t, ctx.id)
        if hr(t.get("companyId")) or trainer:      # trainers save the training back, so they get it whole
            out.append(t)
            continue
        if t.get("companyId") != mine_co and not trainer:
            continue
        if t.get("status") == "draft" and not trainer:
            continue
        t = dict(t)
        t.pop("cost", None)
        if t.get("trainer"):
            t["trainer"] = {k: v for k, v in t["trainer"].items() if k in ("name", "org")}
        if not trainer:
            q = dict(t.get("quiz") or {})
            q["questions"] = [{k: v for k, v in (x or {}).items() if k != "correct"} for x in q.get("questions") or []]
            t["quiz"] = q
            if t["id"] not in attended:
                t["materialsCount"] = len(t.get("materials") or [])
                t["materials"] = []
        out.append(t)
    st["trainings"] = out
    st["trainingNeeds"] = [n for n in st.get("trainingNeeds", []) if hr(n.get("companyId") or emp_co.get(n.get("empId")))
                           or n.get("empId") == ctx.id or n.get("empId") in ctx.line]


# ---------------------------------------------------------------- instructor report (for the e-mail)
def report(key: str, trainings: list, feedback: list, enrols: list, labels: dict) -> dict:
    """Feedback for one trainer across their completed trainings, against the company's average, and the
    areas to improve: the lowest-rated questions, those below 3.5 or well below the company's average."""
    def keys(t):
        if t.get("kind") == "internal":
            return ["emp:" + i for i in t.get("trainerIds") or []]
        tr = t.get("trainer") or {}
        return ["ext:" + (tr.get("email") or tr.get("name") or "").strip().lower()]
    mine = [t for t in trainings if key in keys(t) and t.get("status") == "completed"]
    ids = {t["id"] for t in mine}
    fb_mine = [f for f in feedback if f.get("trainingId") in ids]
    avg = lambda vals: round(sum(vals) / len(vals), 2) if vals else None  # noqa: E731
    qs = {}
    for f in fb_mine:
        for k, v in (f.get("ratings") or {}).items():
            qs.setdefault(k, []).append(v)
    org = {}
    for f in feedback:
        for k, v in (f.get("ratings") or {}).items():
            org.setdefault(k, []).append(v)
    rows = [{"key": k, "label": labels.get(k, k), "avg": avg(v), "n": len(v), "org": avg(org.get(k, []))} for k, v in qs.items()]
    rows.sort(key=lambda r: r["avg"])
    improve = [r for r in rows if r["key"] != "overall" and (r["avg"] < 3.5 or (r["org"] and r["avg"] < r["org"] - 0.3))]
    if not improve:
        improve = [r for r in rows if r["key"] != "overall"][:2]
    att = [x for x in enrols if x.get("trainingId") in ids and x.get("status") in ("attended", "absent")]
    return {"trainings": mine, "feedback": len(fb_mine), "rows": rows, "improve": improve,
            "comments": [f.get("improve") for f in fb_mine if f.get("improve")],
            "liked": [f.get("liked") for f in fb_mine if f.get("liked")],
            "attended": sum(1 for x in att if x.get("status") == "attended"), "enrolled": len(att)}
