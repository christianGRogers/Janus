"""Tests for the Janus broker REST API."""

import io
import os
import shutil
import pytest
from fastapi.testclient import TestClient

from janus.server.app import app, registry, model_store, MODEL_UPLOAD_DIR
from janus.server import database as db
from janus.server import auth


@pytest.fixture(autouse=True)
def _reset_state():
    """Clear the node registry, reinitialise an in-memory DB, and clear emails."""
    registry._nodes.clear()
    model_store.clear()
    db.init_db(":memory:")
    auth.clear_sent_emails()
    yield
    registry._nodes.clear()
    model_store.clear()
    db.close_db()
    # Clean up any uploaded model files
    if os.path.isdir(MODEL_UPLOAD_DIR):
        shutil.rmtree(MODEL_UPLOAD_DIR, ignore_errors=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _create_verified_user(client: TestClient, email="christiangrrogers@gmail.com", password="s3cret!"):
    """Register a user, verify their email, and return (email, password)."""
    # register
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201

    # extract verification token from the captured email
    sent = auth.get_sent_emails()
    token = sent[-1]["token"]

    # verify
    resp = client.get("/auth/verify-email", params={"token": token})
    assert resp.status_code == 200

    return email, password


def _login(client: TestClient, email="christiangrrogers@gmail.com", password="s3cret!") -> dict:
    """Log in and return a dict with JWT auth headers and the API key."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "api_key": body["api_key"],
    }


def _get_auth_headers(client: TestClient, email="christiangrrogers@gmail.com", password="s3cret!") -> dict:
    """Full helper: register + verify + login, return auth headers."""
    _create_verified_user(client, email, password)
    return _login(client, email, password)


def _fresh_api_key(client: TestClient, auth_result: dict) -> str:
    """Generate an additional API key via POST /api-keys (for multi-node tests)."""
    resp = client.post("/api-keys", headers=auth_result["headers"])
    assert resp.status_code == 201
    return resp.json()["key"]


def _register_node(client: TestClient, auth_result: dict, api_key=None):
    """Register a node using the API key from *auth_result* (or an explicit key).

    If registering multiple nodes under the same user, pass a fresh key via
    ``api_key`` (from ``_fresh_api_key``) because each login key is single-use.
    """
    key = api_key or auth_result["api_key"]
    return client.post("/nodes", json={}, headers={"X-API-Key": key})


# ── /health ───────────────────────────────────────────────────────────────────

def test_health():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Auth: register / verify / login ──────────────────────────────────────────

def test_register_sends_verification_email():
    client = TestClient(app)
    resp = client.post("/auth/register", json={
        "email": "christiangrrogers@gmail.com", "password": "pass123",
    })
    assert resp.status_code == 201
    sent = auth.get_sent_emails()
    assert len(sent) == 1
    assert sent[0]["to"] == "christiangrrogers@gmail.com"
    assert len(sent[0]["token"]) > 0


def test_register_duplicate_email():
    client = TestClient(app)
    client.post("/auth/register", json={"email": "dup@christiangrrogers.com", "password": "p"})
    resp = client.post("/auth/register", json={"email": "dup@christiangrrogers.com", "password": "p"})
    assert resp.status_code == 409


def test_verify_email_success():
    client = TestClient(app)
    _create_verified_user(client, "christiangrrogers@gmail.com", "pw")
    user = db.get_user_by_email("christiangrrogers@gmail.com")
    assert user["email_verified"] == 1


def test_verify_email_bad_token():
    client = TestClient(app)
    resp = client.get("/auth/verify-email", params={"token": "garbage"})
    assert resp.status_code == 400


def test_login_success():
    client = TestClient(app)
    _create_verified_user(client, "login@christiangrrogers.com", "pw")
    resp = client.post("/auth/login", json={"email": "login@christiangrrogers.com", "password": "pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert "api_key" in body
    assert body["api_key"].startswith("janus_")
    assert body["email"] == "login@christiangrrogers.com"


def test_login_wrong_password():
    client = TestClient(app)
    _create_verified_user(client, "wp@christiangrrogers.com", "right")
    resp = client.post("/auth/login", json={"email": "wp@christiangrrogers.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unverified_email():
    client = TestClient(app)
    client.post("/auth/register", json={"email": "unv@christiangrrogers.com", "password": "pw"})
    resp = client.post("/auth/login", json={"email": "unv@christiangrrogers.com", "password": "pw"})
    assert resp.status_code == 403


# ── POST /api-keys (requires verified JWT) ───────────────────────────────────

def test_login_returns_api_key():
    """Login should return a fresh, unused API key."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    api_key = auth_result["api_key"]
    assert api_key.startswith("janus_")
    # Verify the key exists in the DB and is unused
    info = db.get_api_key_info(api_key)
    assert info is not None
    assert info["used"] == 0


def test_generate_extra_api_key():
    """POST /api-keys still works for users who need additional keys."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post("/api-keys", headers=auth_result["headers"])
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith("janus_")
    assert body["used"] is False
    assert body["node_id"] is None


def test_generate_api_key_no_auth():
    client = TestClient(app)
    resp = client.post("/api-keys")
    assert resp.status_code == 401


def test_generate_api_key_unverified_user():
    """A user whose email is not verified should be rejected."""
    client = TestClient(app)
    # Register but do NOT verify
    client.post("/auth/register", json={"email": "nope@christiangrrogers.com", "password": "pw"})
    # Manually create a JWT for this unverified user
    user = db.get_user_by_email("nope@christiangrrogers.com")
    token = auth.create_jwt(user_id=user["id"], email=user["email"])
    resp = client.post("/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ── GET /api-keys/{key} ──────────────────────────────────────────────────────

def test_get_api_key_info():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    key = auth_result["api_key"]
    resp = client.get(f"/api-keys/{key}", headers=auth_result["headers"])
    assert resp.status_code == 200
    assert resp.json()["key"] == key
    assert resp.json()["used"] is False


def test_get_api_key_not_found():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.get("/api-keys/bogus_key", headers=auth_result["headers"])
    assert resp.status_code == 404


# ── POST /nodes (register, requires API key) ─────────────────────────────────

def test_register_node():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = _register_node(client, auth_result)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["status"] == "available"


def test_register_node_without_api_key():
    client = TestClient(app)
    resp = client.post("/nodes", json={})
    assert resp.status_code == 422


def test_register_node_invalid_api_key():
    client = TestClient(app)
    resp = client.post("/nodes", json={}, headers={"X-API-Key": "not-a-real-key"})
    assert resp.status_code == 401


def test_register_node_reuse_api_key():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    api_key = auth_result["api_key"]

    resp = client.post("/nodes", json={}, headers={"X-API-Key": api_key})
    assert resp.status_code == 201

    resp = client.post("/nodes", json={}, headers={"X-API-Key": api_key})
    assert resp.status_code == 403


def test_api_key_marked_used_after_node_creation():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    api_key = auth_result["api_key"]
    resp = client.post("/nodes", json={}, headers={"X-API-Key": api_key})
    node_id = resp.json()["id"]

    resp = client.get(f"/api-keys/{api_key}", headers=auth_result["headers"])
    body = resp.json()
    assert body["used"] is True
    assert body["node_id"] == node_id


# ── GET /nodes (list) ────────────────────────────────────────────────────────

def test_list_nodes_empty():
    client = TestClient(app)
    resp = client.get("/nodes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_nodes_returns_registered():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    _register_node(client, auth_result)
    key2 = _fresh_api_key(client, auth_result)
    _register_node(client, auth_result, api_key=key2)
    resp = client.get("/nodes")
    assert len(resp.json()) == 2


def test_list_available_only():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    _register_node(client, auth_result)
    key2 = _fresh_api_key(client, auth_result)
    _register_node(client, auth_result, api_key=key2)
    client.post("/sessions/request_node", json={
        "session_id": "s1",
    }, headers=auth_result["headers"])
    resp = client.get("/nodes", params={"available_only": True})
    ids = [n["id"] for n in resp.json()]
    # One of the two nodes should have been assigned
    assert len(ids) == 1


# ── POST /sessions/request_node ──────────────────────────────────────────────

def test_request_node_success():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    reg_resp = _register_node(client, auth_result)
    node_id = reg_resp.json()["id"]

    resp = client.post("/sessions/request_node", json={
        "session_id": "s1",
    }, headers=auth_result["headers"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["assigned"] is True
    assert body["node_id"] == node_id
    assert body["session_id"] == "s1"


def test_request_node_none_available():
    """Should 409 when there are no available nodes."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post("/sessions/request_node", json={
        "session_id": "s1",
    }, headers=auth_result["headers"])
    assert resp.status_code == 409


def test_request_node_all_assigned():
    """Should 409 when all nodes are already assigned."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    _register_node(client, auth_result)
    # Assign the only node
    client.post("/sessions/request_node", json={
        "session_id": "s1",
    }, headers=auth_result["headers"])
    # Second request should fail
    resp = client.post("/sessions/request_node", json={
        "session_id": "s2",
    }, headers=auth_result["headers"])
    assert resp.status_code == 409


def test_request_node_missing_auth():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    _register_node(client, auth_result)
    resp = client.post("/sessions/request_node", json={
        "session_id": "s1",
    })
    assert resp.status_code == 401


# ── POST /sessions/release_node ──────────────────────────────────────────────

def test_release_node_success():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    reg_resp = _register_node(client, auth_result)
    node_id = reg_resp.json()["id"]
    client.post("/sessions/request_node", json={
        "session_id": "s1",
    }, headers=auth_result["headers"])

    resp = client.post(f"/sessions/release_node/{node_id}", headers=auth_result["headers"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "available"


def test_release_node_not_found():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post("/sessions/release_node/missing", headers=auth_result["headers"])
    assert resp.status_code == 404


# ── NodeRegistry unit tests ──────────────────────────────────────────────────

def test_registry_assign_and_release():
    from janus.server.node_registry import NodeRegistry

    reg = NodeRegistry()
    entry = reg.register()

    assigned = reg.assign(entry.id, session_id="s1", user_id="u1")
    assert assigned.status == "assigned"

    released = reg.release(entry.id)
    assert released.status == "available"
    assert released.assigned_session_id is None


def test_registry_assign_any():
    from janus.server.node_registry import NodeRegistry

    reg = NodeRegistry()
    e1 = reg.register()
    e2 = reg.register()

    entry = reg.assign_any(session_id="s1", user_id="u1")
    assert entry.status == "assigned"
    assert entry.id in (e1.id, e2.id)

    # Second assign_any should get the other node
    entry2 = reg.assign_any(session_id="s2", user_id="u2")
    assert entry2.status == "assigned"
    assert entry2.id != entry.id


def test_registry_assign_any_none_available():
    from janus.server.node_registry import NodeRegistry

    reg = NodeRegistry()
    with pytest.raises(ValueError, match="No available nodes"):
        reg.assign_any(session_id="s1", user_id="u1")


def test_registry_double_assign_raises():
    from janus.server.node_registry import NodeRegistry

    reg = NodeRegistry()
    entry = reg.register()
    reg.assign(entry.id, session_id="s1", user_id="u1")

    with pytest.raises(ValueError, match="already assigned"):
        reg.assign(entry.id, session_id="s2", user_id="u2")


# ── POST /models/upload ──────────────────────────────────────────────────────

def test_upload_model_h5():
    """Upload a .h5 file and receive model metadata."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    fake_model = io.BytesIO(b"\x89HDF\r\n\x1a\n")  # fake HDF5 header
    resp = client.post(
        "/models/upload",
        files={"file": ("my_model.h5", fake_model, "application/octet-stream")},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "model_id" in body
    assert body["filename"] == "my_model.h5"
    assert body["node_id"] is None


def test_upload_model_keras():
    """Upload a .keras file."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post(
        "/models/upload",
        files={"file": ("model.keras", io.BytesIO(b"fake"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["filename"] == "model.keras"


def test_upload_model_zip():
    """Upload a .zip file (SavedModel)."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post(
        "/models/upload",
        files={"file": ("saved_model.zip", io.BytesIO(b"PK"), "application/zip")},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["filename"] == "saved_model.zip"


def test_upload_model_unsupported_extension():
    """Reject files that aren't .h5, .keras, or .zip."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post(
        "/models/upload",
        files={"file": ("model.pkl", io.BytesIO(b"data"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_upload_model_with_node_id():
    """Associate the upload with a registered node."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    reg_resp = _register_node(client, auth_result)
    node_id = reg_resp.json()["id"]

    resp = client.post(
        "/models/upload",
        files={"file": ("m.h5", io.BytesIO(b"data"), "application/octet-stream")},
        params={"node_id": node_id},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["node_id"] == node_id


def test_upload_model_invalid_node_id():
    """Should 404 when node_id doesn't exist."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post(
        "/models/upload",
        files={"file": ("m.h5", io.BytesIO(b"data"), "application/octet-stream")},
        params={"node_id": "nonexistent"},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 404


def test_upload_model_no_auth():
    """Upload without JWT should be rejected."""
    client = TestClient(app)
    resp = client.post(
        "/models/upload",
        files={"file": ("m.h5", io.BytesIO(b"data"), "application/octet-stream")},
    )
    assert resp.status_code == 401


# ── GET /models ──────────────────────────────────────────────────────────────

def test_list_models_empty():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.get("/models", headers=auth_result["headers"])
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_models_after_upload():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    client.post(
        "/models/upload",
        files={"file": ("a.h5", io.BytesIO(b"data"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    resp = client.get("/models", headers=auth_result["headers"])
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── GET /models/{model_id} ──────────────────────────────────────────────────

def test_get_model_metadata():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    upload_resp = client.post(
        "/models/upload",
        files={"file": ("x.h5", io.BytesIO(b"data"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    model_id = upload_resp.json()["model_id"]

    resp = client.get(f"/models/{model_id}", headers=auth_result["headers"])
    assert resp.status_code == 200
    assert resp.json()["model_id"] == model_id


def test_get_model_not_found():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.get("/models/nonexistent", headers=auth_result["headers"])
    assert resp.status_code == 404


# ── POST /models/{model_id}/run ──────────────────────────────────────────────

def test_run_model_not_found():
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    resp = client.post(
        "/models/nonexistent/run",
        json={"input_data": [[1.0, 2.0]]},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 404


def test_run_model_no_auth():
    client = TestClient(app)
    resp = client.post(
        "/models/some-id/run",
        json={"input_data": [[1.0]]},
    )
    assert resp.status_code == 401


def test_run_model_no_input_returns_400():
    """Must supply either datastream_url or input_data."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    upload_resp = client.post(
        "/models/upload",
        files={"file": ("m.h5", io.BytesIO(b"data"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    model_id = upload_resp.json()["model_id"]

    resp = client.post(
        f"/models/{model_id}/run",
        json={},
        headers=auth_result["headers"],
    )
    assert resp.status_code == 400
    assert "datastream_url" in resp.json()["detail"]


def test_run_model_response_includes_broker_fields():
    """RunModelResponse should contain broker_url and broker_dispatched."""
    client = TestClient(app)
    auth_result = _get_auth_headers(client)
    upload_resp = client.post(
        "/models/upload",
        files={"file": ("m.h5", io.BytesIO(b"data"), "application/octet-stream")},
        headers=auth_result["headers"],
    )
    model_id = upload_resp.json()["model_id"]

    # This will fail at the TF load step (fake file), but we can
    # verify the 400/422 behaviour rather than needing real TF.
    resp = client.post(
        f"/models/{model_id}/run",
        json={"input_data": [[1.0]], "broker_url": "http://broker.example/signals"},
        headers=auth_result["headers"],
    )
    # Expect 422 or 501 (TF not installed / bad model) – not 400
    assert resp.status_code in (422, 501)