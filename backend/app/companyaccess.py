"""Switch a company's sign-in off or on from the server, by its short code. For companies that registered
themselves (the group administrator does not see those in the app):

    docker exec pd-app python -m app.companyaccess list
    docker exec pd-app python -m app.companyaccess off ACME
    docker exec pd-app python -m app.companyaccess on ACME
"""
import sys

from sqlalchemy import text

from . import repo


def main(argv):
    cmd = (argv[1] if len(argv) > 1 else "list").lower()
    with repo.engine.begin() as conn:
        rows = [repo.loads(d) for d in conn.execute(text("SELECT data FROM companies")).scalars()]
        if cmd == "list":
            for c in sorted(rows, key=lambda c: c.get("code") or ""):
                n = conn.execute(text("SELECT COUNT(*) FROM employees WHERE company_id=:c AND (status IS NULL OR status<>'exited')"), {"c": c["id"]}).scalar()
                print(f"{c.get('code',''):8} {'OFF' if c.get('signinOff') else 'on ':4} {n:5} employees  {c.get('legalName') or c.get('name')}"
                      f"{'  (registered itself)' if c.get('source') == 'register' else ''}")
            return 0
        if cmd not in ("on", "off") or len(argv) < 3:
            print(__doc__)
            return 2
        code = argv[2].strip().upper()
        co = next((c for c in rows if (c.get("code") or "").upper() == code), None)
        if not co:
            print(f"No company with the code {code}.")
            return 1
        if co.get("source") != "register" and any(
                (repo.loads(d) or {}).get("role") == "super" for d in
                conn.execute(text("SELECT data FROM employees WHERE company_id=:c"), {"c": co["id"]}).scalars()):
            print("That is the platform company (the group administrator's own): its sign-in cannot be switched off.")
            return 1
        co["signinOff"] = cmd == "off"
        repo.upsert(conn, "companies", [co], None)
        repo.audit_add(conn, "Company sign-in switched " + cmd + " (server)", f"{co.get('name')} ({code})", None)
        repo.bump_rev(conn)
        print(f"Sign-in for {co.get('name')} ({code}) is now {cmd.upper()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
