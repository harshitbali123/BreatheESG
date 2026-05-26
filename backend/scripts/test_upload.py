import sys
import requests
import subprocess

def main():
    base_url = "http://127.0.0.1:8000"
    
    # 1. Login
    print("Logging in to get JWT token...")
    login_url = f"{base_url}/api/auth/login/"
    login_data = {"username": "admin", "password": "breathe123"}
    resp = requests.post(login_url, json=login_data)
    if resp.status_code != 200:
        print(f"Login failed! Status: {resp.status_code}, Response: {resp.text}")
        sys.exit(1)
        
    token = resp.json().get("access")
    headers = {"Authorization": f"Bearer {token}"}
    print("Logged in successfully!")

    # Helper function to delete prior run with the same hash if any, to avoid 409 conflict
    def clear_existing_runs(source_type):
        runs_url = f"{base_url}/api/ingestion/runs/?source_type={source_type}"
        r = requests.get(runs_url, headers=headers)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                print(f"Found existing runs for {source_type}, removing to prevent 409 duplicate errors...")
                cmd = (
                    f"from apps.normalization.models import NormalizedActivity; "
                    f"from apps.ingestion.models import RawRow, IngestionRun; "
                    f"NormalizedActivity.objects.filter(ingestion_run__source_type='{source_type}').delete(); "
                    f"RawRow.objects.filter(ingestion_run__source_type='{source_type}').delete(); "
                    f"IngestionRun.objects.filter(source_type='{source_type}').delete()"
                )
                subprocess.run([
                    sys.executable, "manage.py", "shell", "-c", cmd
                ], check=True, capture_output=True)

    # 2. Test Travel Ingestion
    print("\n--- Testing Travel Ingestion ---")
    clear_existing_runs("travel")
    
    travel_file_path = "../test/test_travel.csv"
    upload_url = f"{base_url}/api/ingestion/upload/"
    
    with open(travel_file_path, "rb") as f:
        files = {"file": ( "test_travel.csv", f, "text/csv" )}
        data = {"source_type": "travel", "reporting_year": 2024}
        r = requests.post(upload_url, headers=headers, data=data, files=files)
        
    print(f"Upload Status Code: {r.status_code}")
    if r.status_code in (200, 201):
        res = r.json()
        print("Travel Ingestion Successful:")
        print(f"  Status: {res['status']}")
        print(f"  Total Rows: {res['row_count_total']}")
        print(f"  Success Rows: {res['row_count_success']}")
        print(f"  Failed Rows: {res['row_count_failed']}")
        print(f"  Flagged Rows: {res['row_count_flagged']}")
        if res['row_count_failed'] > 0:
            print("  Warning: There are failed rows in travel ingestion.")
    else:
        print(f"Travel Ingestion Failed! Response: {r.text}")

    # 3. Test Utility Ingestion
    print("\n--- Testing Utility Ingestion ---")
    clear_existing_runs("utility")
    
    utility_file_path = "../test/test_utility.csv"
    
    with open(utility_file_path, "rb") as f:
        files = {"file": ( "test_utility.csv", f, "text/csv" )}
        data = {"source_type": "utility", "reporting_year": 2024}
        r = requests.post(upload_url, headers=headers, data=data, files=files)
        
    print(f"Upload Status Code: {r.status_code}")
    if r.status_code in (200, 201):
        res = r.json()
        print("Utility Ingestion Successful:")
        print(f"  Status: {res['status']}")
        print(f"  Total Rows: {res['row_count_total']}")
        print(f"  Success Rows: {res['row_count_success']}")
        print(f"  Failed Rows: {res['row_count_failed']}")
        print(f"  Flagged Rows: {res['row_count_flagged']}")
        if res['row_count_failed'] > 0:
            print("  Warning: There are failed rows in utility ingestion.")
    else:
        print(f"Utility Ingestion Failed! Response: {r.text}")

if __name__ == "__main__":
    main()
