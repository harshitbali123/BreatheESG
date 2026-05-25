"""Simple smoke test script for API endpoints.

Usage: activate the venv then run:
    python scripts/smoke_test.py --base http://localhost:8000

The script will:
 - log in to obtain JWT
 - hit ingestion runs list
 - hit review activities list
 - attempt an approve action (if any activity exists)
 - fetch review summary
 - list tenants
 - list audit logs

Requires: `requests` installed in the project's environment.
"""
import argparse
import requests
import sys
import subprocess
import time
from datetime import datetime, timedelta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="password")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    session = requests.Session()

    # Check unauthenticated access first
    print("Checking unauthenticated responses (expect 401)...")
    unauth_checks = [
        ("Ingestion runs", f"{base}/api/ingestion/runs/"),
        ("Review activities", f"{base}/api/review/activities/"),
        ("Review summary", f"{base}/api/review/summary/"),
    ]
    for name, url in unauth_checks:
        r = session.get(url)
        print("[unauth]", name, "->", r.status_code)

    # Obtain token
    print("Logging in...")
    r = session.post(f"{base}/api/auth/login/", json={"username": args.username, "password": args.password})
    if r.status_code != 200:
        print("Login failed:", r.status_code, r.text)
        sys.exit(1)
    token = r.json().get("access")
    session.headers.update({"Authorization": f"Bearer {token}"})
    print("Got JWT, testing endpoints...")

    endpoints = [
        ("Ingestion runs", f"{base}/api/ingestion/runs/"),
        ("Normalization activities", f"{base}/api/normalization/activities/"),
        ("Review activities", f"{base}/api/review/activities/"),
        ("Review summary", f"{base}/api/review/summary/"),
        ("Tenants", f"{base}/api/tenants/"),
        ("Audit logs", f"{base}/api/audit/logs/"),
    ]

    for name, url in endpoints:
        r = session.get(url)
        print(name, url, "->", r.status_code)

    # If no activities exist, attempt to seed dev data (if manage.py available)
    r = session.get(f"{base}/api/review/activities/?page_size=1")
    if r.status_code != 200 or not r.json().get("results"):
        print("No activities found. Attempting to run seed_dev...")
        try:
            proc = subprocess.run([sys.executable, "manage.py", "seed_dev"], check=True, capture_output=True, text=True)
            print(proc.stdout)
        except Exception as e:
            print("Failed to run seed_dev:", e)
            print("Please run `python manage.py seed_dev` manually and re-run this script.")
            return
        # allow DB to settle
        time.sleep(1)

    # Refresh activities
    r = session.get(f"{base}/api/review/activities/?page_size=100")
    if r.status_code != 200:
        print("Failed to fetch activities:", r.status_code, r.text)
        return

    # Try approve action on the first review activity
    print("Attempting approve action (if any activity exists)...")
    r = session.get(f"{base}/api/review/activities/?page_size=1")
    if r.status_code == 200 and r.json().get("results"):
        activity = r.json()["results"][0]
        aid = activity["id"]

        # Check tenant scoping: fetch tenant id and confirm activity.tenant matches
        tenants = session.get(f"{base}/api/tenants/")
        tenant_ok = True
        if tenants.status_code == 200 and tenants.json().get("results"):
            tenant_id = tenants.json()["results"][0]["id"]
            # activity may include tenant field
            act_tenant = activity.get("tenant")
            if act_tenant and act_tenant != tenant_id:
                print("Tenant mismatch: activity tenant", act_tenant, "!=", tenant_id)
                tenant_ok = False
        else:
            print("Could not verify tenant list; skipping tenant-scope check.")

        # Get pre-approve audit logs count for this activity
        logs_before = session.get(f"{base}/api/audit/logs/?page_size=200").json().get("results", [])
        before_count = sum(1 for l in logs_before if l.get("target_id") == aid)

        appr = session.post(f"{base}/api/review/activities/{aid}/approve/", json={})
        print("Approve ->", appr.status_code, appr.text)

        # verify audit log written
        logs_after = session.get(f"{base}/api/audit/logs/?page_size=200").json().get("results", [])
        after_count = sum(1 for l in logs_after if l.get("target_id") == aid)
        if after_count > before_count:
            print("Audit log written for activity", aid)
        else:
            print("No new audit log found for activity", aid)

        # Attempt approve on a locked record (should return 409)
        locked = session.get(f"{base}/api/review/activities/?review_status=locked&page_size=1")
        if locked.status_code == 200 and locked.json().get("results"):
            locked_id = locked.json()["results"][0]["id"]
            resp = session.post(f"{base}/api/review/activities/{locked_id}/approve/", json={})
            print("Approve locked ->", resp.status_code)
            if resp.status_code == 409:
                print("Locked-approve correctly returned 409")
            else:
                print("Locked-approve did not return 409; response:", resp.status_code, resp.text)
        else:
            print("No locked activities to test locked-approve behavior.")

        # Check summary totals
        summary = session.get(f"{base}/api/review/summary/")
        if summary.status_code == 200:
            data = summary.json()
            print("Summary:", data)
            totals_nonzero = any(int(v) if isinstance(v, (int, str)) and str(v).isdigit() else True for v in [
                data.get("review_status_counts", {}).get("approved", 0),
                data.get("review_status_counts", {}).get("flagged", 0),
            ])
            if totals_nonzero:
                print("Summary contains non-zero counts (good)")
            else:
                print("Summary counts appear zero — check seed data")
        else:
            print("Failed to fetch summary:", summary.status_code, summary.text)
    else:
        print("No activities found or failed to fetch activities.")


if __name__ == '__main__':
    main()
