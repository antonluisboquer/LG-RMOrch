"""Encompass API client for the RM Orchestrator agent.

Uses the Encompass REST API directly (no copilotagent dependency).
Authentication: 2-step OAuth (password grant + token exchange for impersonation),
falling back to the client_credentials grant.

In addition to field read/write, this client exposes the endpoints the RM
workflow needs to *act* on a loan:
- underwriting condition listing / status updates
- milestone completion
- conversation-log notes
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_MODULE_CLIENT_CACHE: dict = {}
_workflow_env: Optional[str] = None


def reset_encompass_state():
    """Reset cached workflow env and client cache for a fresh run."""
    global _workflow_env
    _workflow_env = None
    _MODULE_CLIENT_CACHE.clear()


def _get_env_var(name: str, env_prefix: Optional[str] = None) -> Optional[str]:
    if env_prefix:
        val = os.getenv(f"{env_prefix}{name}")
        if val:
            return val
    return os.getenv(name)


class EncompassClient:
    """Lightweight Encompass REST client with auto-refresh."""

    def __init__(
        self,
        api_base_url: str,
        client_id: str,
        client_secret: str,
        instance_id: str,
        username: str,
        password: str,
        subject_user_id: str = "",
        scope: str = "lp",
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance_id = instance_id
        self.username = username
        self.password = password
        self.subject_user_id = subject_user_id
        self.scope = scope or "lp"
        self.access_token: Optional[str] = None
        # Super-admin (password-grant) token, kept even when we impersonate a
        # subject user. Admins can see settings/templates that impersonated
        # users cannot, so this is used for template listing.
        self.actor_token: Optional[str] = None
        # Cached integration-level token (client_credentials grant). Used for
        # settings/template endpoints whose visibility is filtered per-user.
        self._client_credentials_token: Optional[str] = None

    def authenticate(self) -> str:
        """Authenticate via password grant (+ impersonation), falling back to
        the client_credentials grant if the password grant fails."""
        token_url = f"{self.api_base_url}/oauth2/v1/token"

        try:
            # Step 1: Super Admin token
            r1 = requests.post(token_url, data={
                "grant_type": "password",
                "username": f"{self.username}@encompass:{self.instance_id}",
                "password": self.password,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            }, timeout=15)
            r1.raise_for_status()
            actor_token = r1.json()["access_token"]
            self.actor_token = actor_token

            if self.subject_user_id:
                # Step 2: Impersonation token
                r2 = requests.post(token_url, data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "subject_user_id": self.subject_user_id,
                    "actor_token": actor_token,
                    "scope": self.scope,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }, timeout=15)
                r2.raise_for_status()
                self.access_token = r2.json()["access_token"]
            else:
                self.access_token = actor_token

            logger.info("[ENCOMPASS] Authenticated via password grant")
            return self.access_token
        except Exception as exc:
            detail = ""
            resp = getattr(exc, "response", None)
            if resp is not None:
                try:
                    body = resp.json()
                    detail = f" — {body.get('error')}: {body.get('error_description')}"
                except Exception:
                    detail = f" — {(resp.text or '')[:200]}"
            logger.warning(
                f"[ENCOMPASS] Password grant failed ({exc}){detail}; "
                "falling back to client_credentials (integration token — "
                "conditions/milestones/conversation-log may be forbidden)"
            )
            self.access_token = self.get_client_credentials_token(force=True)
            return self.access_token

    def get_client_credentials_token(self, force: bool = False) -> str:
        """Mint (and cache) an integration-level token via client_credentials."""
        if self._client_credentials_token and not force:
            return self._client_credentials_token

        token_url = f"{self.api_base_url}/oauth2/v1/token"
        r = requests.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
            "instance_id": self.instance_id,
        }, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(
                f"client_credentials HTTP {r.status_code} at {token_url}: "
                f"{(r.text or '')[:400]}"
            )
        self._client_credentials_token = r.json()["access_token"]
        logger.info("[ENCOMPASS] Obtained client_credentials token")
        return self._client_credentials_token

    def get_actor_token(self) -> Optional[str]:
        """Return the super-admin (password-grant) token, authenticating if needed."""
        if not self.actor_token:
            self._ensure_token()
        return self.actor_token

    def _headers(self, content_type: str = "application/json") -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": content_type,
            "Accept": "application/json",
        }

    def _ensure_token(self):
        if not self.access_token:
            self.authenticate()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request, retry once on 401 with a fresh token."""
        self._ensure_token()
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", 30)

        r = requests.request(method, url, **kwargs)
        if r.status_code == 401:
            logger.info("[ENCOMPASS] 401 — refreshing token and retrying")
            self.authenticate()
            kwargs["headers"] = self._headers()
            r = requests.request(method, url, **kwargs)
        return r

    # ── Search ──

    def search_loans(self, loan_number: str) -> List[Dict[str, Any]]:
        """Search by loan number via v3 loanPipeline."""
        url = f"{self.api_base_url}/encompass/v3/loanPipeline"
        payload = {
            "fields": ["Loan.Guid", "Loan.LoanNumber", "Loan.BorrowerName"],
            "filter": {
                "canonicalName": "Loan.LoanNumber",
                "value": loan_number,
                "matchType": "exact",
            },
            "includeArchivedLoans": True,
            "loanOwnership": "AllLoans",
        }
        r = self._request("POST", url, json=payload)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("rows", [])
        results = []
        for row in rows:
            fields = row.get("fields", {})
            results.append({
                "loanGuid": row.get("loanId"),
                "loanNumber": fields.get("Loan.LoanNumber"),
                "borrowerName": fields.get("Loan.BorrowerName"),
            })
        return results

    # ── Field I/O ──

    def read_fields(self, loan_id: str, field_ids: List[str]) -> Dict[str, Any]:
        """Read fields via POST /fieldReader."""
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/fieldReader"
        r = self._request("POST", url, json=field_ids)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return data
        result = {}
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    result[entry.get("fieldId", "")] = entry.get("value")
                elif isinstance(entry, str) and len(field_ids) == 1:
                    result[field_ids[0]] = entry
        return result

    def get_application_id(self, loan_id: str) -> str:
        """Get the first application ID from the loan entity."""
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}?view=entity"
        r = self._request("GET", url)
        r.raise_for_status()
        apps = r.json().get("applications", [])
        return apps[0].get("id", "") if apps else ""

    def write_fields(self, loan_id: str, updates: Dict[str, Any]) -> bool:
        """Write fields via the v3 fieldWriter endpoint."""
        if not updates:
            return True

        top_fields = {fid: val for fid, val in updates.items()}

        if top_fields:
            url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/fieldWriter"
            payload = [{"id": fid, "value": str(val)} for fid, val in top_fields.items()]
            r = self._request("POST", url, json=payload)
            if r.status_code not in (200, 204):
                logger.error(f"[ENCOMPASS] fieldWriter error {r.status_code}: {r.text[:300]}")
                r.raise_for_status()

        logger.info(f"[ENCOMPASS] Wrote {len(updates)} fields to loan {loan_id[:12]}")
        return True

    # ── Underwriting conditions ──

    def get_conditions(self, loan_id: str) -> List[Dict[str, Any]]:
        """List the loan's underwriting conditions.

        Returns the raw condition objects from the v3 underwritingConditions
        endpoint. Each condition typically includes: id, title, description,
        status, priorTo, category, source, dateAdded.
        """
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/underwritingConditions"
        r = self._request("GET", url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("conditions", [])

    def update_condition(
        self,
        loan_id: str,
        condition_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Patch a single underwriting condition (e.g. status, description).

        ``updates`` keys are Encompass condition attributes, e.g.
        {"status": "Cleared"} or {"status": "Requested", "description": "..."}.
        """
        url = (
            f"{self.api_base_url}/encompass/v3/loans/{loan_id}"
            f"/underwritingConditions/{condition_id}"
        )
        r = self._request("PATCH", url, json=updates)
        if r.status_code not in (200, 204):
            logger.error(
                f"[ENCOMPASS] update_condition error {r.status_code}: {r.text[:300]}"
            )
            r.raise_for_status()
        logger.info(f"[ENCOMPASS] Updated condition {condition_id} on loan {loan_id[:12]}")
        return True

    # ── Milestones ──

    def get_milestones(self, loan_id: str) -> List[Dict[str, Any]]:
        """List the loan's milestones (log entries)."""
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/milestones"
        r = self._request("GET", url)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("milestones", [])

    def complete_milestone(self, loan_id: str, milestone_name: str) -> Dict[str, Any]:
        """Mark a milestone complete by its name (e.g. 'TPO Cond Submitted').

        Finds the milestone id by matching ``milestoneName``/``title`` and
        PATCHes it complete. Returns a small result dict.
        """
        milestones = self.get_milestones(loan_id)
        target = None
        wanted = milestone_name.strip().lower()
        for ms in milestones:
            name = str(ms.get("milestoneName") or ms.get("title") or "").strip().lower()
            if name == wanted or wanted in name:
                target = ms
                break

        if not target:
            available = [ms.get("milestoneName") or ms.get("title") for ms in milestones]
            return {
                "success": False,
                "error": f"Milestone '{milestone_name}' not found",
                "available": available,
            }

        ms_id = target.get("id")
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/milestones/{ms_id}"
        r = self._request(
            "PATCH", url,
            params={"action": "finish"},
            json={"milestoneComplete": True},
        )
        if r.status_code not in (200, 204):
            logger.error(
                f"[ENCOMPASS] complete_milestone error {r.status_code}: {r.text[:300]}"
            )
            r.raise_for_status()
        return {"success": True, "milestone_id": ms_id, "milestone_name": milestone_name}

    # ── Conversation log ──

    def add_conversation_log_note(self, loan_id: str, note: str) -> Dict[str, Any]:
        """Append a note to the loan conversation log.

        Encompass exposes conversation-log entries via the loan's
        ``conversationLog`` collection. This posts a new note entry.
        """
        url = f"{self.api_base_url}/encompass/v3/loans/{loan_id}/conversationLog"
        r = self._request("POST", url, json={"notes": note})
        if r.status_code not in (200, 201, 204):
            logger.error(
                f"[ENCOMPASS] add_conversation_log_note error {r.status_code}: {r.text[:300]}"
            )
            r.raise_for_status()
        return {"success": True, "note": note}


# ── Factory ──

def get_encompass_client(env: str = None, state: dict = None, use_cache: bool = True) -> EncompassClient:
    """Get an initialized EncompassClient.

    Environment priority: explicit env > state["env"] > cached > "TEST".
    """
    global _workflow_env

    env_mode = None
    if env:
        env_mode = env.upper()
    elif state and state.get("env"):
        env_mode = state["env"].upper()
    elif _workflow_env:
        env_mode = _workflow_env
    else:
        env_mode = "TEST"

    if env_mode not in ("TEST", "PROD"):
        env_mode = "TEST"

    if _workflow_env is None:
        _workflow_env = env_mode
        logger.info(f"[ENCOMPASS] Workflow env: {env_mode}")

    env_prefix = f"{env_mode}_"
    instance_id = _get_env_var("ENCOMPASS_INSTANCE_ID", env_prefix) or ""
    cache_key = f"{env_mode}_{instance_id}" if instance_id else env_mode

    if use_cache and cache_key in _MODULE_CLIENT_CACHE:
        return _MODULE_CLIENT_CACHE[cache_key]

    client = EncompassClient(
        api_base_url=_get_env_var("ENCOMPASS_API_BASE_URL", env_prefix) or "https://api.elliemae.com",
        client_id=_get_env_var("ENCOMPASS_CLIENT_ID", env_prefix) or "",
        client_secret=_get_env_var("ENCOMPASS_CLIENT_SECRET", env_prefix) or "",
        instance_id=instance_id,
        username=_get_env_var("ENCOMPASS_USERNAME", env_prefix) or "",
        password=_get_env_var("ENCOMPASS_PASSWORD", env_prefix) or "",
        subject_user_id=_get_env_var("ENCOMPASS_SUBJECT_USER_ID", env_prefix) or "",
        scope=_get_env_var("ENCOMPASS_SCOPE", env_prefix) or "lp",
    )

    if use_cache:
        _MODULE_CLIENT_CACHE[cache_key] = client

    return client


class FieldIds:
    """Common Encompass field IDs used by the RM workflow.

    NOTE: TPO / custom field IDs (marked below) are best-effort defaults and
    should be confirmed against the target Encompass instance before writes are
    taken out of dry-run mode.
    """
    LOAN_NUMBER = "364"
    BORROWER_FIRST_NAME = "4000"
    BORROWER_LAST_NAME = "4002"
    LOAN_PURPOSE = "19"           # Purchase / Refinance / Cash-Out Refinance
    LOAN_AMOUNT = "1109"
    PROPERTY_STATE = "14"
    LOAN_TYPE = "1172"

    # Estimated Closing Date (Borrower Summary)
    ESTIMATED_CLOSING_DATE = "763"

    # Milestone / status context
    CURRENT_MILESTONE = "MS.STATUS"      # Current milestone name (confirmed)

    # TPO / submission dates (confirm per-instance)
    TPO_SUBMISSION_DATE = "CX.TPO.SUBMISSION.DATE"     # placeholder — confirm
    INITIAL_SUBMITTAL_DATE = "3142"                    # Initial Submittal / App received

    # Deal Fell Through (DFT) — Processor Details reasons (confirm per-instance)
    DFT_REASON = "CX.DFT.REASON"                        # placeholder — confirm

    # TPO Information: "Cond's Ready for Review" checkbox (confirm per-instance)
    CONDS_READY_FOR_REVIEW = "CX.TPO.CONDS.READY"       # placeholder — confirm
