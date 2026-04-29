"""
Trigger a Power BI semantic model (dataset) refresh and poll until completion.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from pbi_client import PowerBIClient


def trigger_refresh(client: PowerBIClient, workspace_id: str, dataset_id: str) -> bool:
    print(f"Triggering refresh — workspace: {workspace_id}  dataset: {dataset_id}")

    response = client.pbi_post(
        f"groups/{workspace_id}/datasets/{dataset_id}/refreshes",
        {"notifyOption": "MailOnFailure"},
    )

    if response.status_code in (200, 202):
        print("Refresh request accepted. Polling for completion...")
        return _poll_refresh(client, workspace_id, dataset_id)

    print(f"Unexpected response: {response.status_code} {response.text}")
    return False


def _poll_refresh(
    client: PowerBIClient,
    workspace_id: str,
    dataset_id: str,
    timeout: int = 900,
    interval: int = 30,
) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = client.pbi_get(
                f"groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top=1"
            )
            refreshes = result.get("value", [])
            if not refreshes:
                time.sleep(interval)
                continue

            latest = refreshes[0]
            status = latest.get("status", "")
            print(f"  Refresh status: {status}")

            if status == "Completed":
                print("Refresh completed successfully.")
                return True
            if status in ("Failed", "Cancelled"):
                print(f"Refresh failed:\n{json.dumps(latest, indent=2)}")
                return False
        except Exception as exc:
            print(f"  Poll error: {exc}")

        time.sleep(interval)

    print("Refresh polling timed out.")
    return False


def main():
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    dataset_id = os.environ["DATASET_ID"]

    client = PowerBIClient()
    success = trigger_refresh(client, workspace_id, dataset_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
