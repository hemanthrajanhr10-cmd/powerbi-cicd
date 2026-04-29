"""
Sync a Fabric workspace from its connected Git repository.
Uses the Fabric REST API long-running operation pattern.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from pbi_client import PowerBIClient


def get_git_status(client: PowerBIClient, workspace_id: str) -> dict:
    return client.fabric_get(f"workspaces/{workspace_id}/git/status")


def sync_workspace(client: PowerBIClient, workspace_id: str, commit_hash: str) -> bool:
    print(f"Fetching current git status for workspace {workspace_id}...")
    status = get_git_status(client, workspace_id)
    workspace_head = status.get("workspaceHead")
    print(f"  workspaceHead : {workspace_head}")
    print(f"  target commit : {commit_hash}")

    body = {
        "workspaceHead": workspace_head,
        "remoteCommitHash": commit_hash or None,
        "conflictResolution": {
            "conflictResolutionType": "Workspace",
            "conflictResolutionPolicy": "PreferRemote",
        },
        "options": {"allowOverrideItems": True},
    }

    print("Triggering updateFromGit...")
    response = client.fabric_post(f"workspaces/{workspace_id}/git/updateFromGit", body)

    if response.status_code == 200:
        print("Sync completed immediately.")
        return True

    if response.status_code == 202:
        operation_id = response.headers.get("x-ms-operation-id") or response.headers.get("Operation-Id")
        location = response.headers.get("Location", "")
        print(f"Long-running operation started: {operation_id or location}")
        return _poll(client, workspace_id, operation_id, location)

    print(f"Unexpected response: {response.status_code} {response.text}")
    return False


def _poll(client: PowerBIClient, workspace_id: str, operation_id: str | None, location: str, timeout: int = 600) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if operation_id:
                result = client.fabric_get(
                    f"workspaces/{workspace_id}/git/updateFromGit/operationResults/{operation_id}"
                )
            elif location:
                import requests
                r = requests.get(location, headers=client._fabric_headers)
                r.raise_for_status()
                result = r.json()
            else:
                print("No operation ID or location to poll — assuming success.")
                return True

            state = result.get("status") or result.get("state") or ""
            print(f"  Status: {state}")

            if state in ("Succeeded", "Completed", "succeeded", "completed"):
                print("Workspace sync succeeded.")
                return True
            if state in ("Failed", "Cancelled", "failed", "cancelled"):
                print(f"Sync failed:\n{json.dumps(result, indent=2)}")
                return False
        except Exception as exc:
            print(f"  Poll error: {exc}")

        time.sleep(15)

    print("Sync timed out.")
    return False


def main():
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    commit_hash = os.environ.get("COMMIT_HASH", "")

    client = PowerBIClient()
    success = sync_workspace(client, workspace_id, commit_hash)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
