import os
import requests
import msal


class PowerBIClient:
    PBI_BASE = "https://api.powerbi.com/v1.0/myorg"
    FABRIC_BASE = "https://api.fabric.microsoft.com/v1"

    def __init__(self):
        self.tenant_id = os.environ["POWERBI_TENANT_ID"]
        self.client_id = os.environ["POWERBI_CLIENT_ID"]
        self.client_secret = os.environ["POWERBI_CLIENT_SECRET"]
        self._tokens: dict[str, str] = {}

    def _get_token(self, scope: str) -> str:
        if scope in self._tokens:
            return self._tokens[scope]
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=[scope])
        if "access_token" not in result:
            raise RuntimeError(
                f"Token acquisition failed: {result.get('error_description', result)}"
            )
        self._tokens[scope] = result["access_token"]
        return self._tokens[scope]

    @property
    def _pbi_headers(self) -> dict:
        token = self._get_token("https://analysis.windows.net/powerbi/api/.default")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @property
    def _fabric_headers(self) -> dict:
        token = self._get_token("https://api.fabric.microsoft.com/.default")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Power BI REST ──────────────────────────────────────────────────────────

    def pbi_get(self, path: str) -> dict:
        r = requests.get(f"{self.PBI_BASE}/{path}", headers=self._pbi_headers)
        r.raise_for_status()
        return r.json()

    def pbi_post(self, path: str, body: dict | None = None) -> requests.Response:
        r = requests.post(
            f"{self.PBI_BASE}/{path}",
            headers=self._pbi_headers,
            json=body or {},
        )
        r.raise_for_status()
        return r

    # ── Fabric REST ───────────────────────────────────────────────────────────

    def fabric_get(self, path: str) -> dict:
        r = requests.get(f"{self.FABRIC_BASE}/{path}", headers=self._fabric_headers)
        r.raise_for_status()
        return r.json()

    def fabric_post(self, path: str, body: dict | None = None) -> requests.Response:
        r = requests.post(
            f"{self.FABRIC_BASE}/{path}",
            headers=self._fabric_headers,
            json=body or {},
        )
        r.raise_for_status()
        return r
