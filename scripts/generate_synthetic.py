"""Generate synthetic versioned company policies with PLANTED contradictions.

Outputs (all under data/synthetic/):
  <company>/<doc>/<YYYY-MM-DD>.md   the documents (one file per version)
  manifest.json                     same format as data/raw/manifest.json (loader reads it)
  ground_truth.json                 every fact, every version change, every planted conflict
  questions.json                    evaluation questions with expected answer + expected version

Conflict kinds in the ground truth:
  version_change   a value legitimately changed between versions (expected: answer from the current one)
  stale_faq        a CURRENT FAQ still states the OLD value -> real contradiction between two current docs
  consistent_faq   a current FAQ that agrees with its policy -> negative control (must NOT be flagged)

Usage: python scripts/generate_synthetic.py        (deterministic, seed=42)
"""
import json
import random
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "synthetic"
SEED = 42

COMPANIES = ["Northwind Labs", "Brightpath Logistics", "Crestline Financial",
             "Helios Renewables", "Maple & Finch Retail", "Orbital Health", "Tidewater Foods"]

POLICIES = {
    "leave_policy": {
        "title": "Leave Policy",
        "purpose": "This policy sets out how {company} grants and manages paid time away from work so that employees can rest and plan with confidence.",
        "scope": "It applies to all full-time employees of {company}. Contractors and interns are covered by their own agreements.",
        "exceptions": "Exceptions require written approval from the Head of People. Local statutory entitlements always take precedence where they are more generous.",
        "params": {
            "annual_leave_days": dict(heading="Annual Leave", values=[15, 18, 20, 22, 24, 25, 28, 30],
                q="How many days of paid annual leave do full-time employees get",
                t=["Full-time employees are entitled to {v} days of paid annual leave per calendar year.",
                   "Each full-time employee receives {v} days of paid annual leave every calendar year.",
                   "The paid annual leave allowance for full-time staff is {v} days per year."]),
            "sick_leave_days": dict(heading="Sick Leave", values=[6, 8, 10, 12, 14],
                q="How many days of paid sick leave are employees allowed per year",
                t=["Employees may take up to {v} days of paid sick leave per year.",
                   "The yearly paid sick leave allowance is {v} days.",
                   "Paid sick leave is capped at {v} days in any calendar year."]),
            "carryover_days": dict(heading="Carry-over", values=[0, 3, 5, 7, 10],
                q="How many unused annual leave days can be carried over to the next year",
                t=["Up to {v} unused annual leave days may be carried over into the next calendar year.",
                   "Employees can carry over a maximum of {v} unused leave days to the following year.",
                   "The carry-over limit for unused annual leave is {v} days."]),
            "leave_notice_days": dict(heading="Notice for Leave Requests", values=[3, 5, 7, 10, 14],
                q="How many days in advance must leave requests be submitted",
                t=["Leave requests must be submitted at least {v} days in advance.",
                   "Employees should request leave no later than {v} days before the first day of absence.",
                   "A minimum notice period of {v} days applies to all leave requests."]),
            "parental_leave_weeks": dict(heading="Parental Leave", values=[8, 12, 16, 18, 26],
                q="How many weeks of paid parental leave do primary caregivers receive",
                t=["Primary caregivers receive {v} weeks of paid parental leave.",
                   "Paid parental leave for a primary caregiver lasts {v} weeks.",
                   "The company provides {v} weeks of fully paid leave to primary caregivers."]),
        },
    },
    "expense_policy": {
        "title": "Travel and Expense Policy",
        "purpose": "This policy explains which business expenses {company} reimburses and how claims are submitted and approved.",
        "scope": "It applies to every employee of {company} who incurs costs on the company's behalf, including travel, meals and equipment.",
        "exceptions": "The Finance Director may approve exceptions in writing. Expenses that breach this policy without approval will not be reimbursed.",
        "params": {
            "meal_limit_usd": dict(heading="Meals", values=[30, 40, 50, 60, 75],
                q="What is the daily meal allowance during business travel in US dollars",
                t=["The daily meal allowance during business travel is ${v}.",
                   "Employees on business travel may claim up to ${v} per day for meals.",
                   "Meal expenses are reimbursed up to a limit of ${v} per day."]),
            "receipt_threshold_usd": dict(heading="Receipts", values=[10, 20, 25, 50],
                q="From what amount in US dollars is a receipt required for an expense claim",
                t=["Receipts are required for every expense of ${v} or more.",
                   "An itemised receipt must accompany any claim of ${v} or above.",
                   "Claims of ${v} and over must include a receipt."]),
            "approval_threshold_usd": dict(heading="Manager Approval", values=[250, 500, 750, 1000, 1500],
                q="Above what amount in US dollars does an expense need prior manager approval",
                t=["Expenses above ${v} require prior approval from a manager.",
                   "Any single expense over ${v} needs a manager's approval before purchase.",
                   "Manager pre-approval is mandatory for purchases exceeding ${v}."]),
            "claim_deadline_days": dict(heading="Claim Deadline", values=[14, 30, 45, 60, 90],
                q="Within how many days must an expense claim be submitted",
                t=["Expense claims must be submitted within {v} days of the expense.",
                   "Claims submitted more than {v} days after the expense date will be rejected.",
                   "The submission deadline for expense claims is {v} days from the date incurred."]),
            "mileage_rate_cents": dict(heading="Mileage", values=[30, 45, 55, 60, 67],
                q="At how many cents per mile is personal vehicle use reimbursed",
                t=["Personal vehicle use is reimbursed at {v} cents per mile.",
                   "The mileage reimbursement rate is {v} cents per mile driven.",
                   "Employees using their own car are paid {v} cents for each mile."]),
        },
    },
    "security_policy": {
        "title": "IT Security and Remote Work Policy",
        "purpose": "This policy defines the security rules that protect {company} systems and data, including when working remotely.",
        "scope": "It applies to all employees, contractors and any device that connects to {company} systems.",
        "exceptions": "The Chief Information Security Officer may grant time-limited exceptions. All exceptions are logged and reviewed every quarter.",
        "params": {
            "password_min_length": dict(heading="Passwords", values=[8, 10, 12, 14, 16],
                q="What is the minimum password length in characters",
                t=["Passwords must be at least {v} characters long.",
                   "The minimum password length is {v} characters.",
                   "All account passwords require a minimum of {v} characters."]),
            "password_rotation_days": dict(heading="Password Rotation", values=[60, 90, 120, 180],
                q="How often in days must passwords be changed",
                t=["Passwords must be changed every {v} days.",
                   "Password rotation is required at intervals of {v} days.",
                   "Employees must renew their passwords every {v} days."]),
            "incident_report_hours": dict(heading="Incident Reporting", values=[4, 12, 24, 48, 72],
                q="Within how many hours must a security incident be reported",
                t=["Security incidents must be reported within {v} hours of discovery.",
                   "Staff are required to report any security incident within {v} hours.",
                   "The reporting window for security incidents is {v} hours from detection."]),
            "remote_days_per_week": dict(heading="Remote Work", values=[1, 2, 3, 4],
                q="How many days per week may employees work remotely",
                t=["Employees may work remotely up to {v} days per week.",
                   "Remote working is permitted for a maximum of {v} days each week.",
                   "The weekly remote work allowance is {v} days."]),
            "session_timeout_minutes": dict(heading="Session Timeout", values=[5, 10, 15, 30],
                q="After how many minutes of inactivity are sessions locked automatically",
                t=["Inactive sessions are locked automatically after {v} minutes.",
                   "Devices lock themselves after {v} minutes of inactivity.",
                   "The idle session timeout is {v} minutes."]),
        },
    },
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def pick_other(rng, values, current):
    return rng.choice([x for x in values if x != current])


def build_policy_versions(rng, spec):
    """-> list of {date, values, changed:[param,...]} in date order."""
    n = rng.choice([2, 3, 3, 4])
    d = date(2021, 1, 1) + timedelta(days=rng.randint(0, 540))
    values = {p: rng.choice(c["values"]) for p, c in spec["params"].items()}
    versions = [{"date": d, "values": dict(values), "changed": []}]
    for _ in range(n - 1):
        d = d + timedelta(days=rng.randint(200, 420))
        changed = rng.sample(list(values), rng.choice([1, 2]))
        for p in changed:
            values[p] = pick_other(rng, spec["params"][p]["values"], values[p])
        versions.append({"date": d, "values": dict(values), "changed": changed})
    return versions


def header(company, title, n, d):
    return (f"# {company} - {title}\n\n**Document version:** v{n}  \n"
            f"**Effective date:** {d.isoformat()}\n\n")


def render_policy(rng, company, spec, n, d, values):
    out = header(company, spec["title"], n, d)
    out += f"## 1. Purpose\n\n{spec['purpose'].format(company=company)}\n\n"
    out += f"## 2. Scope\n\n{spec['scope'].format(company=company)}\n\n## 3. Provisions\n\n"
    for p, c in spec["params"].items():
        out += f"### {c['heading']}\n\n{rng.choice(c['t']).format(v=values[p])}\n\n"
    out += f"## 4. Exceptions\n\n{spec['exceptions']}\n"
    return out


def render_faq(rng, company, spec, n, d, values):
    out = header(company, spec["title"] + " FAQ", n, d)
    out += "## Frequently asked questions\n\n"
    for p, c in spec["params"].items():
        out += f"**Q: {c['q']}?**\n\nA: {rng.choice(c['t']).format(v=values[p])}\n\n"
    return out


def write_doc(folder, d, text):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{d.isoformat()}.md"
    f.write_text(text, encoding="utf-8")
    return str(f.relative_to(ROOT)).replace("\\", "/")


def main():
    rng = random.Random(SEED)
    if OUT.exists():
        shutil.rmtree(OUT)
    manifest, facts, changes, conflicts, questions = [], [], [], [], []
    k = 0  # policy counter -> decides which policies get a FAQ

    for company in COMPANIES:
        for kind, spec in POLICIES.items():
            k += 1
            title = f"{company} - {spec['title']}"
            vers = build_policy_versions(rng, spec)
            files = []
            for i, v in enumerate(vers):
                text = render_policy(rng, company, spec, i + 1, v["date"], v["values"])
                files.append({"effective_date": v["date"].isoformat(),
                              "file": write_doc(OUT / slug(company) / kind, v["date"], text)})
            manifest.append({"title": title, "doc_family": kind, "is_synthetic": True,
                             "versions": files})

            for p, c in spec["params"].items():
                facts.append({"doc": title, "param": p, "question": c["q"],
                              "history": [{"version": f"v{i+1}", "effective_date": v["date"].isoformat(),
                                           "value": v["values"][p]} for i, v in enumerate(vers)]})
            for i in range(1, len(vers)):
                for p in vers[i]["changed"]:
                    changes.append({"type": "version_change", "doc": title, "param": p,
                                    "from_version": f"v{i}", "to_version": f"v{i+1}",
                                    "old_value": vers[i-1]["values"][p], "new_value": vers[i]["values"][p],
                                    "effective_date": vers[i]["date"].isoformat()})

            # companion FAQ for every other policy; 2 of every 3 FAQs are stale on one parameter
            stale_param, faq_title = None, None
            if k % 2 == 0:
                faq_title = f"{company} - {spec['title']} FAQ"
                last = vers[-1]
                is_stale = (k // 2) % 3 != 0
                faq_vals_latest = dict(last["values"])
                if is_stale:
                    stale_param = rng.choice(last["changed"])
                    faq_vals_latest[stale_param] = vers[-2]["values"][stale_param]  # the OLD value
                d1 = vers[0]["date"] + timedelta(days=30)
                d2 = last["date"] + timedelta(days=45)
                faq_files = []
                for n, d, vals in [(1, d1, vers[0]["values"]), (2, d2, faq_vals_latest)]:
                    faq_files.append({"effective_date": d.isoformat(),
                                      "file": write_doc(OUT / slug(company) / (kind + "_faq"), d,
                                                        render_faq(rng, company, spec, n, d, vals))})
                manifest.append({"title": faq_title, "doc_family": "faq", "is_synthetic": True,
                                 "versions": faq_files})
                for p, c in spec["params"].items():
                    conflicts.append({
                        "type": "stale_faq" if p == stale_param else "consistent_faq",
                        "param": p, "policy_doc": title, "policy_version": f"v{len(vers)}",
                        "policy_value": last["values"][p],
                        "faq_doc": faq_title, "faq_version": "v2", "faq_value": faq_vals_latest[p],
                        "contradiction": p == stale_param})

            # evaluation questions
            ever_changed = {p for v in vers[1:] for p in v["changed"]}
            for p in sorted(ever_changed):
                c = spec["params"][p]
                questions.append({
                    "id": f"q{len(questions)+1}", "type": "current", "doc": title, "param": p,
                    "question": f"{c['q']} at {company}?",
                    "expected_value": vers[-1]["values"][p], "expected_version": f"v{len(vers)}",
                    "faq_conflict_expected": p == stale_param})
                older = [i for i in range(len(vers) - 1) if vers[i]["values"][p] != vers[-1]["values"][p]]
                if older:
                    i = rng.choice(older)
                    gap = (vers[i + 1]["date"] - vers[i]["date"]).days
                    as_of = vers[i]["date"] + timedelta(days=gap // 2)
                    questions.append({
                        "id": f"q{len(questions)+1}", "type": "as_of", "doc": title, "param": p,
                        "as_of": as_of.isoformat(),
                        "question": f"As of {as_of.isoformat()}, {c['q'][0].lower() + c['q'][1:]} at {company}?",
                        "expected_value": vers[i]["values"][p], "expected_version": f"v{i+1}",
                        "faq_conflict_expected": False})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "ground_truth.json").write_text(json.dumps(
        {"facts": facts, "version_changes": changes, "cross_doc_conflicts": conflicts}, indent=2), encoding="utf-8")
    (OUT / "questions.json").write_text(json.dumps(questions, indent=2), encoding="utf-8")

    n_v = sum(len(d["versions"]) for d in manifest)
    stale = sum(c["type"] == "stale_faq" for c in conflicts)
    ctrl = sum(c["type"] == "consistent_faq" for c in conflicts)
    print(f"Documents: {len(manifest)}  versions: {n_v}")
    print(f"Version changes: {len(changes)}  planted stale-FAQ conflicts: {stale}  "
          f"consistent controls: {ctrl}  questions: {len(questions)}")


if __name__ == "__main__":
    main()
