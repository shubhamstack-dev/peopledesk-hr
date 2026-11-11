"""2.17: the candidate signs in to fill in their form.

Runs against a real MySQL or MariaDB database (DATABASE_URL, default as in app/config.py), which it empties.
    cd backend && JWT_SECRET=test python -m pytest tests/test_candidate_signin.py -q
"""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main, repo
from app.security import hash_password, set_pw_hash

H = {"x-peopledesk": "1"}
ADMIN_PW = "admin-password-1"
EMP_PW = "employee-password-1"
CAND_PW = "candidate-pass-1"

STATE = {
    "companies": [{"id": "co1", "name": "Aequm", "legalName": "Aequm India Private Limited"}],
    "employees": [
        {"id": "e1", "role": "super", "email": "admin@aequm.in", "firstName": "Asha", "lastName": "Rao", "companyId": "co1", "status": "active"},
        {"id": "e2", "role": "employee", "email": "ravi@aequm.in", "firstName": "Ravi", "lastName": "K", "companyId": "co1", "status": "active",
         "phone": "9876500000"},
    ],
}


def client():
    return TestClient(main.app, headers=H)


def cand(cid, email="", phone="", name="Meera Iyer"):
    return {"id": cid, "companyId": "co1", "name": name, "email": email, "phone": phone, "stage": "sourced"}


@pytest.fixture(scope="module")
def hr():
    with repo.engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    main.migrate.run(repo.engine)
    c = client()
    r = c.post("/api/setup", json={"state": STATE, "adminId": "e1", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    with repo.engine.begin() as conn:
        set_pw_hash(conn, "e2", hash_password(EMP_PW))
        repo.upsert(conn, "cands", [cand("c1", email="Meera.Iyer@example.com"),
                                   cand("c2", email="ravi@aequm.in", name="Ravi K"),          # an employee's address
                                   cand("c3", phone="98765 00000", name="Arjun Shah"),        # mobile only, shared with an employee
                                   cand("c4", name="No Contact")], "e1")
    return c


def send_link(hr, cid):
    r = hr.post("/api/candidate-form/link", json={"candId": cid, "send": False})
    assert r.status_code == 200, r.text
    return re.search(r"[?&]t=([^&]+)", r.json()["url"]).group(1)


def test_link_alone_shows_no_details_and_cannot_save(hr):
    token = send_link(hr, "c1")
    stranger = client()
    r = stranger.post("/api/apply/open", json={"token": token})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["hasAccount"] is False and v["canSetPassword"] is True and v["login"] == "Meera.Iyer@example.com"
    assert "data" not in v and "rules" not in v                     # nothing the candidate entered
    # the old token-only save is gone, and the form needs a candidate session
    assert stranger.post("/api/apply/save", json={"token": token, "data": {}}).status_code in (404, 405)
    assert stranger.get("/api/candidate/form").status_code == 401


def test_candidate_creates_sign_in_and_fills_the_form(hr):
    token = send_link(hr, "c1")
    c = client()
    assert c.post("/api/apply/account", json={"token": token, "password": "short"}).status_code == 400
    r = c.post("/api/apply/account", json={"token": token, "password": CAND_PW})
    assert r.status_code == 200 and r.json()["kind"] == "candidate", r.text
    assert c.get("/api/session").json() == {"kind": "candidate"}
    f = c.get("/api/candidate/form").json()
    assert f["editable"] and f["data"]["firstName"] == "Meera"
    d = {**f["data"], "lastName": "Iyer", "dob": "1995-05-01", "gender": "F", "phone": "9123456789",
         "address": "12 MG Road", "addrCity": "Bengaluru", "emergencyName": "S Iyer", "emergencyPhone": "9123400000"}
    r = c.post("/api/candidate/form", json={"data": d, "submit": False})
    assert r.status_code == 200 and r.json()["status"] == "draft", r.text
    # the same link cannot set a password again
    assert c.post("/api/apply/account", json={"token": token, "password": "another-pass-1"}).status_code == 400
    # HR sees that the candidate made a sign-in
    with repo.engine.connect() as conn:
        rec = repo.get_records(conn, "cands", ["c1"])["c1"]
    assert rec["form"]["accountAt"] and rec["form"]["status"] == "draft"


def test_candidate_signs_in_from_the_sign_in_page(hr):
    c = client()
    assert c.post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": "wrong-password"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": CAND_PW})
    assert r.status_code == 200 and r.json()["kind"] == "candidate", r.text
    assert c.get("/api/candidate/form").json()["data"]["addrCity"] == "Bengaluru"
    # a candidate gets nothing of the main app
    assert c.get("/api/state").status_code == 401
    assert c.get("/api/contractor/state").status_code == 403


def test_employees_cannot_fill_the_candidate_form(hr):
    emp = client()
    assert emp.post("/api/auth/login", json={"email": "ravi@aequm.in", "password": EMP_PW}).status_code == 200
    assert emp.get("/api/candidate/form").status_code == 403
    assert emp.post("/api/candidate/form", json={"data": {}}).status_code == 403
    # HR itself cannot either
    assert hr.get("/api/candidate/form").status_code == 403
    # the link page tells the browser an employee is signed in
    token = send_link(hr, "c1")
    assert emp.post("/api/apply/open", json={"token": token}).json()["signedIn"] == "employee"
    # no candidate link to an employee's e-mail address, nor a sign-in for one
    r = hr.post("/api/candidate-form/link", json={"candId": "c2", "send": False})
    assert r.status_code == 400 and "employee" in r.json()["detail"]
    assert hr.post("/api/candidate-form/link", json={"candId": "c4", "send": False}).status_code == 400   # nothing to sign in with


def test_new_link_resets_a_forgotten_password(hr):
    token = send_link(hr, "c1")
    c = client()
    v = c.post("/api/apply/open", json={"token": token}).json()
    assert v["hasAccount"] is True and v["canSetPassword"] is True
    assert c.post("/api/apply/account", json={"token": token, "password": "a-new-password-1"}).status_code == 200
    assert client().post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": CAND_PW}).status_code == 401
    assert client().post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": "a-new-password-1"}).status_code == 200


def test_mobile_only_candidate_whose_number_is_an_employees(hr):
    token = send_link(hr, "c3")
    c = client()
    assert c.post("/api/apply/account", json={"token": token, "password": CAND_PW}).status_code == 200
    # the employee with that mobile number still signs in as the employee
    assert client().post("/api/auth/login", json={"email": "9876500000", "password": EMP_PW}).json().get("me") == "e2"
    # and the candidate, with their own password, as the candidate
    r = client().post("/api/auth/login", json={"email": "+91 98765 00000", "password": CAND_PW})
    assert r.status_code == 200 and r.json()["kind"] == "candidate", r.text


def test_sending_and_joining(hr):
    c = client()
    c.post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": "a-new-password-1"})
    d = c.get("/api/candidate/form").json()["data"]
    d["declaration"] = True
    d["education"] = [{"level": "Graduate", "qualification": "B.Com", "institution": "Christ College", "university": "Bangalore University",
                       "mode": "full", "fromYear": "2013", "toYear": "2016", "score": "72", "scoreType": "pct"}]
    r = c.post("/api/candidate/form", json={"data": d, "submit": True})
    assert r.status_code == 200 and r.json()["status"] == "submitted" and not r.json()["editable"], r.text
    assert c.post("/api/candidate/form", json={"data": d, "submit": True}).status_code == 400
    # once they join, the candidate sign-in stops
    with repo.engine.begin() as conn:
        rec = repo.get_records(conn, "cands", ["c1"])["c1"]
        rec["form"]["status"] = "closed"
        repo.upsert(conn, "cands", [rec], "e1")
    assert c.get("/api/candidate/form").status_code == 401
    r = client().post("/api/auth/login", json={"email": "meera.iyer@example.com", "password": "a-new-password-1"})
    assert r.status_code == 403 and "employee record" in r.json()["detail"]


def test_change_password(hr):
    c = client()
    assert c.post("/api/auth/login", json={"email": "+91 98765 00000", "password": CAND_PW}).status_code == 200
    assert c.post("/api/candidate/password", json={"current": "wrong", "new": "changed-pass-1"}).status_code == 400
    assert c.post("/api/candidate/password", json={"current": CAND_PW, "new": "changed-pass-1"}).status_code == 200
    assert client().post("/api/auth/login", json={"email": "9876500000", "password": "changed-pass-1"}).json()["kind"] == "candidate"
