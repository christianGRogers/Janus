"""High-level Python client for the Janus financial inference platform.

Usage::

    from janus import Client

    client = Client()                         # uses default API URL
    client.register("you@example.com", "pw")  # sends verification email
    client.verify_email(token)                # paste token from email
    client.login("you@example.com", "pw")     # stores JWT + API key
    client.register_node()                    # server assigns node ID
    session = client.create_session("sess-1") # pre-configured Session
    session.request_node()                    # auto-assigned by server
    session.run_model(model_id)               # datastream → model → broker
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import requests

from . import const
from .session import Session


class Client:
    """Stateful client that manages authentication and API keys.

    After :meth:`login` succeeds the JWT bearer token and the single-use
    API key are stored internally so every subsequent call is automatically
    authenticated.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url: str = (base_url or const.BRADENSBAY_API_URL).rstrip("/")

        # Credentials – populated by login()
        self.token: str | None = None
        self.api_key: str | None = None
        self.user_id: str | None = None
        self.email: str | None = None

    # ── helpers ───────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        """Return ``Authorization: Bearer …`` headers.

        Raises:
            RuntimeError: if :meth:`login` has not been called yet.
        """
        if not self.token:
            raise RuntimeError("Not logged in. Call client.login() first.")
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _raise_for_error(resp: requests.Response) -> None:
        """Raise a clear error using the API's ``detail`` field when possible."""
        if resp.ok:
            return
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise requests.exceptions.HTTPError(
            f"{resp.status_code}: {detail}", response=resp,
        )

    # ── auth ──────────────────────────────────────────────────────────────

    def register(self, email: str, password: str) -> dict:
        """Create a new account.  A verification email will be sent.

        Returns the API response dict (contains a ``message`` field).
        """
        resp = requests.post(
            f"{self.base_url}/auth/register",
            json={"email": email, "password": password},
        )
        self._raise_for_error(resp)
        return resp.json()

    def verify_email(self, token: str) -> dict:
        """Verify the user's email address using the token from the email.

        Returns the API response dict.
        """
        resp = requests.get(
            f"{self.base_url}/auth/verify-email",
            params={"token": token},
        )
        self._raise_for_error(resp)
        return resp.json()

    def login(self, email: str, password: str) -> dict:
        """Log in and store the JWT token and API key for subsequent calls.

        Returns the full login response dict.
        """
        resp = requests.post(
            f"{self.base_url}/auth/login",
            json={"email": email, "password": password},
        )
        self._raise_for_error(resp)
        data = resp.json()

        self.token = data["token"]
        self.api_key = data["api_key"]
        self.user_id = data["user_id"]
        self.email = data["email"]

        return data

    # ── API keys ──────────────────────────────────────────────────────────

    def request_api_key(self) -> str:
        """Generate an additional single-use API key.

        The new key is stored as ``self.api_key`` (replacing the previous
        one) and also returned.
        """
        resp = requests.post(
            f"{self.base_url}/api-keys",
            headers=self._auth_headers(),
        )
        self._raise_for_error(resp)
        key = resp.json()["key"]
        self.api_key = key
        return key

    # ── nodes ─────────────────────────────────────────────────────────────

    def register_node(self) -> dict:
        """Register a compute node using the stored API key.

        Every node is created equal — the server auto-generates the node
        ID and all configuration.  The API key is consumed after this call.
        If you need to register another node, call :meth:`request_api_key`
        first.

        Returns the node info dict from the server.
        """
        if not self.api_key:
            raise RuntimeError(
                "No API key available. Log in or call client.request_api_key() first."
            )
        resp = requests.post(
            f"{self.base_url}/nodes",
            json={},
            headers={"X-API-Key": self.api_key},
        )
        self._raise_for_error(resp)

        # Key is now consumed – clear it so the user doesn't accidentally
        # try to reuse it.
        self.api_key = None
        return resp.json()

    # ── sessions ──────────────────────────────────────────────────────────

    def create_session(self, session_id: str | None = None) -> Session:
        """Create a :class:`Session` pre-configured with the stored JWT.

        If *session_id* is omitted a random UUID is generated.
        """
        if not self.token or not self.user_id:
            raise RuntimeError("Not logged in. Call client.login() first.")

        return Session(
            id=session_id or str(uuid.uuid4()),
            user_id=self.user_id,
            token=self.token,
            created_at=datetime.now(timezone.utc).isoformat(),
            broker_url=self.base_url,
            datastream_url=self.base_url,
        )

    # ── models (TensorFlow) ──────────────────────────────────────────────

    def upload_model(
        self,
        file_path: str,
        node_id: str | None = None,
    ) -> dict:
        """Upload a TensorFlow model file to the server.

        Supports ``.h5``, ``.keras``, and ``.zip`` (zipped SavedModel
        directory) files.  Returns the model info dict including the
        assigned ``model_id``.
        """
        import os as _os

        params: dict = {}
        if node_id is not None:
            params["node_id"] = node_id

        filename = _os.path.basename(file_path)
        with open(file_path, "rb") as fh:
            resp = requests.post(
                f"{self.base_url}/models/upload",
                files={"file": (filename, fh)},
                params=params,
                headers=self._auth_headers(),
            )
        self._raise_for_error(resp)
        return resp.json()

    def list_models(self) -> list:
        """Return a list of all uploaded model info dicts."""
        resp = requests.get(
            f"{self.base_url}/models",
            headers=self._auth_headers(),
        )
        self._raise_for_error(resp)
        return resp.json()

    def run_model(
        self,
        model_id: str,
        input_data: list | None = None,
        datastream_url: str | None = None,
        broker_url: str | None = None,
    ) -> dict:
        """Run financial inference on an uploaded model.

        In **live mode** supply *datastream_url* (market data source) and
        *broker_url* (trade execution target).  In **offline mode** pass
        raw *input_data* (2-D list of floats) for back-testing.

        Returns a dict with ``model_id``, ``predictions``,
        ``broker_url``, and ``broker_dispatched``.
        """
        body: dict = {}
        if datastream_url is not None:
            body["datastream_url"] = datastream_url
        if broker_url is not None:
            body["broker_url"] = broker_url
        if input_data is not None:
            body["input_data"] = input_data

        resp = requests.post(
            f"{self.base_url}/models/{model_id}/run",
            json=body,
            headers=self._auth_headers(),
        )
        self._raise_for_error(resp)
        return resp.json()
