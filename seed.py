"""
ClockWork PM – seed data.
Run once: python seed.py
"""
from app.database import init_db, get_db
import bcrypt as _bcrypt
from datetime import date, timedelta
import random

def seed():
    init_db()
    conn = get_db()
    c = conn.cursor()

    # Check if already seeded
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        print("Already seeded, skipping.")
        conn.close()
        return

    # ── Users ──────────────────────────────────────────────────────────────────
    pw = _bcrypt.hashpw(b"password123", _bcrypt.gensalt()).decode()
    c.execute("INSERT INTO users (name, email, password_hash, role, manager_id, is_active) VALUES (?,?,?,?,?,?)",
              ("Aparna", "aparna@vineinfotech.com", pw, "Admin", None, 1))
    admin_id = c.lastrowid

    c.execute("INSERT INTO users (name, email, password_hash, role, manager_id, is_active) VALUES (?,?,?,?,?,?)",
              ("Mark Manager", "mark@vine.com", pw, "Manager", admin_id, 1))
    mgr_id = c.lastrowid

    c.execute("INSERT INTO users (name, email, password_hash, role, manager_id, is_active) VALUES (?,?,?,?,?,?)",
              ("Emma Employee", "emma@vine.com", pw, "Employee", mgr_id, 1))
    emp_id = c.lastrowid

    # ── Projects ──────────────────────────────────────────────────────────────
    c.execute("INSERT INTO projects (name, client, is_active) VALUES (?,?,?)", ("AceHub", "AceHub Corp", 1))
    acehub_id = c.lastrowid

    c.execute("INSERT INTO projects (name, client, is_active) VALUES (?,?,?)", ("Internal", "Vine InfoTech", 1))
    internal_id = c.lastrowid

    c.execute("INSERT INTO projects (name, client, is_active) VALUES (?,?,?)", ("Personal", "", 1))
    personal_id = c.lastrowid

    c.execute("INSERT INTO projects (name, client, is_active) VALUES (?,?,?)", ("Leave", "", 1))
    leave_id = c.lastrowid

    # ── Sub-projects ──────────────────────────────────────────────────────────
    sub_map = {}
    for name in ["HR", "UAT", "SIT", "General"]:
        c.execute("INSERT INTO sub_projects (project_id, name) VALUES (?,?)", (acehub_id, name))
        sub_map[name] = c.lastrowid

    # No sub-projects for Internal / Personal / Leave (can add later)

    # ── Timesheet entries – 2 weeks of realistic data ─────────────────────────
    today = date.today()
    # Start from 2 weeks ago Monday
    monday = today - timedelta(days=today.weekday() + 14)

    def add_entry(user_id, d, proj_id, sub_id, cat, activity, hours, status="Submitted"):
        c.execute("""INSERT INTO timesheet_entries
                     (user_id, entry_date, project_id, sub_project_id, category, activity, hours, status)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, d.isoformat(), proj_id, sub_id, cat, activity, hours, status))

    # Two weeks of data for all 3 users
    for week_offset in range(2):
        week_start = monday + timedelta(weeks=week_offset)
        status = "Submitted" if week_offset == 0 else "Draft"

        for user_id in [admin_id, mgr_id, emp_id]:
            for day_offset in range(5):  # Mon-Fri
                d = week_start + timedelta(days=day_offset)
                if d > today:
                    continue

                # Typical day: 4h billable AceHub + 2h billable AceHub + 2h internal
                sub = random.choice([sub_map["HR"], sub_map["UAT"], sub_map["SIT"], sub_map["General"]])
                add_entry(user_id, d, acehub_id, sub, "Billable",
                          random.choice(["Sprint planning", "Development", "Code review", "Testing", "Bug fixes"]),
                          random.choice([3.5, 4.0, 4.5, 5.0]), status)
                add_entry(user_id, d, acehub_id, sub_map["General"], "Billable",
                          "Client calls and coordination", random.choice([1.5, 2.0]),
                          status)
                add_entry(user_id, d, internal_id, None, "Internal",
                          random.choice(["Team standup", "Internal training", "Documentation"]),
                          random.choice([1.0, 1.5, 2.0]), status)

    # Add one Leave entry for Emma
    leave_day = monday + timedelta(days=7)  # second week Monday
    if leave_day <= today:
        c.execute("DELETE FROM timesheet_entries WHERE user_id=? AND entry_date=?",
                  (emp_id, leave_day.isoformat()))
        add_entry(emp_id, leave_day, leave_id, None, "Leave", "Annual Leave", 8, "Submitted")

    conn.commit()
    conn.close()
    print("Seeded: 3 users, 4 projects, 4 sub-projects, ~2 weeks of entries.")
    print("Login: aparna@vineinfotech.com | mark@vine.com | emma@vine.com  (password: password123)")


if __name__ == "__main__":
    seed()
