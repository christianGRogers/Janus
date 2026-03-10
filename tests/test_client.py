"""Tests for the janus.Client Python API wrapper."""

import pytest
import requests
from unittest.mock import Mock, patch, MagicMock

from janus import Client


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_response(status_code=200, json_data=None):
    """Build a mock requests.Response."""
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    return resp


# ── Client.__init__ ──────────────────────────────────────────────────────────

def test_default_base_url():
    c = Client()
    assert c.base_url == "https://api.bradensbay.com"


def test_custom_base_url():
    c = Client(base_url="http://localhost:8000/")
    assert c.base_url == "http://localhost:8000"  # trailing slash stripped


def test_initial_state():
    c = Client()
    assert c.token is None
    assert c.api_key is None
    assert c.user_id is None
    assert c.email is None


# ── register ─────────────────────────────────────────────────────────────────

def test_register_success():
    c = Client(base_url="http://test")
    mock_resp = _mock_response(201, {"message": "Registration successful."})

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.register("a@b.com", "pw")

    assert result["message"] == "Registration successful."
    mock_post.assert_called_once_with(
        "http://test/auth/register",
        json={"email": "a@b.com", "password": "pw"},
    )


def test_register_duplicate_raises():
    c = Client(base_url="http://test")
    mock_resp = _mock_response(409, {"detail": "Email already registered"})

    with patch("janus.client.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError, match="409"):
            c.register("a@b.com", "pw")


# ── verify_email ─────────────────────────────────────────────────────────────

def test_verify_email_success():
    c = Client(base_url="http://test")
    mock_resp = _mock_response(200, {"message": "Email verified."})

    with patch("janus.client.requests.get", return_value=mock_resp) as mock_get:
        result = c.verify_email("tok123")

    assert result["message"] == "Email verified."
    mock_get.assert_called_once_with(
        "http://test/auth/verify-email",
        params={"token": "tok123"},
    )


# ── login ────────────────────────────────────────────────────────────────────

def test_login_stores_credentials():
    c = Client(base_url="http://test")
    mock_resp = _mock_response(200, {
        "token": "jwt-xyz",
        "api_key": "janus_key123",
        "user_id": "uid-1",
        "email": "a@b.com",
    })

    with patch("janus.client.requests.post", return_value=mock_resp):
        result = c.login("a@b.com", "pw")

    assert c.token == "jwt-xyz"
    assert c.api_key == "janus_key123"
    assert c.user_id == "uid-1"
    assert c.email == "a@b.com"
    assert result["token"] == "jwt-xyz"


def test_login_bad_password_raises():
    c = Client(base_url="http://test")
    mock_resp = _mock_response(401, {"detail": "Invalid email or password"})

    with patch("janus.client.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError, match="401"):
            c.login("a@b.com", "wrong")

    assert c.token is None


# ── auth_headers guard ───────────────────────────────────────────────────────

def test_auth_headers_before_login_raises():
    c = Client()
    with pytest.raises(RuntimeError, match="Not logged in"):
        c._auth_headers()


# ── request_api_key ──────────────────────────────────────────────────────────

def test_request_api_key_replaces_stored_key():
    c = Client(base_url="http://test")
    c.token = "jwt"
    c.api_key = "old-key"

    mock_resp = _mock_response(201, {"key": "janus_new", "created_at": "t", "used": False, "node_id": None})

    with patch("janus.client.requests.post", return_value=mock_resp):
        key = c.request_api_key()

    assert key == "janus_new"
    assert c.api_key == "janus_new"


# ── register_node ────────────────────────────────────────────────────────────

def test_register_node_uses_and_clears_api_key():
    c = Client(base_url="http://test")
    c.token = "jwt"
    c.api_key = "janus_key"

    mock_resp = _mock_response(201, {
        "id": "n1", "status": "available",
    })

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.register_node()

    assert result["id"] == "n1"
    # API key should be cleared after use
    assert c.api_key is None
    # Verify the key was sent in the header
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-API-Key"] == "janus_key"


def test_register_node_no_key_raises():
    c = Client(base_url="http://test")
    c.token = "jwt"
    c.api_key = None

    with pytest.raises(RuntimeError, match="No API key"):
        c.register_node()


# ── create_session ───────────────────────────────────────────────────────────

def test_create_session_returns_configured_session():
    c = Client(base_url="http://test")
    c.token = "jwt-xyz"
    c.user_id = "uid-1"

    session = c.create_session("s1")
    assert session.id == "s1"
    assert session.user_id == "uid-1"
    assert session.token == "jwt-xyz"
    assert session.broker_url == "http://test"


def test_create_session_auto_id():
    c = Client(base_url="http://test")
    c.token = "jwt"
    c.user_id = "uid"

    session = c.create_session()
    assert len(session.id) > 0  # UUID was generated


def test_create_session_before_login_raises():
    c = Client()
    with pytest.raises(RuntimeError, match="Not logged in"):
        c.create_session()


# ── full flow (mocked) ──────────────────────────────────────────────────────

def test_full_flow():
    """register → verify → login → register_node → create_session."""
    c = Client(base_url="http://test")

    register_resp = _mock_response(201, {"message": "Check your email."})
    verify_resp = _mock_response(200, {"message": "Verified."})
    login_resp = _mock_response(200, {
        "token": "jwt", "api_key": "janus_k", "user_id": "u1", "email": "a@b.com",
    })
    node_resp = _mock_response(201, {
        "id": "n1", "status": "available",
    })

    with patch("janus.client.requests.post") as mock_post, \
         patch("janus.client.requests.get", return_value=verify_resp):

        mock_post.side_effect = [register_resp, login_resp, node_resp]

        c.register("a@b.com", "pw")
        c.verify_email("tok")
        c.login("a@b.com", "pw")

        assert c.token == "jwt"
        assert c.api_key == "janus_k"

        c.register_node()
        assert c.api_key is None  # consumed

        session = c.create_session("s1")
        assert session.token == "jwt"
        assert session.user_id == "u1"


# ── upload_model ─────────────────────────────────────────────────────────────

def test_upload_model_success(tmp_path):
    c = Client(base_url="http://test")
    c.token = "jwt"

    model_file = tmp_path / "model.h5"
    model_file.write_bytes(b"fake-model-data")

    mock_resp = _mock_response(201, {
        "model_id": "m1",
        "filename": "model.h5",
        "node_id": None,
        "uploaded_at": "2025-01-01T00:00:00",
    })

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.upload_model(str(model_file))

    assert result["model_id"] == "m1"
    assert result["filename"] == "model.h5"
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "files" in kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer jwt"


def test_upload_model_with_node_id(tmp_path):
    c = Client(base_url="http://test")
    c.token = "jwt"

    model_file = tmp_path / "model.h5"
    model_file.write_bytes(b"data")

    mock_resp = _mock_response(201, {
        "model_id": "m1", "filename": "model.h5",
        "node_id": "n1", "uploaded_at": "t",
    })

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.upload_model(str(model_file), node_id="n1")

    assert result["node_id"] == "n1"
    _, kwargs = mock_post.call_args
    assert kwargs["params"]["node_id"] == "n1"


def test_upload_model_before_login_raises(tmp_path):
    c = Client(base_url="http://test")
    model_file = tmp_path / "m.h5"
    model_file.write_bytes(b"x")

    with pytest.raises(RuntimeError, match="Not logged in"):
        c.upload_model(str(model_file))


# ── list_models ──────────────────────────────────────────────────────────────

def test_list_models():
    c = Client(base_url="http://test")
    c.token = "jwt"

    mock_resp = _mock_response(200, [
        {"model_id": "m1", "filename": "a.h5", "node_id": None, "uploaded_at": "t"},
    ])

    with patch("janus.client.requests.get", return_value=mock_resp):
        result = c.list_models()

    assert len(result) == 1
    assert result[0]["model_id"] == "m1"


# ── run_model ────────────────────────────────────────────────────────────────

def test_run_model_with_input_data():
    c = Client(base_url="http://test")
    c.token = "jwt"

    mock_resp = _mock_response(200, {
        "model_id": "m1",
        "predictions": [[0.9, 0.1]],
        "broker_url": None,
        "broker_dispatched": False,
    })

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.run_model("m1", input_data=[[1.0, 2.0, 3.0]])

    assert result["predictions"] == [[0.9, 0.1]]
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["input_data"] == [[1.0, 2.0, 3.0]]


def test_run_model_with_datastream_and_broker():
    c = Client(base_url="http://test")
    c.token = "jwt"

    mock_resp = _mock_response(200, {
        "model_id": "m1",
        "predictions": [[0.8]],
        "broker_url": "http://broker.example/signals",
        "broker_dispatched": True,
    })

    with patch("janus.client.requests.post", return_value=mock_resp) as mock_post:
        result = c.run_model(
            "m1",
            datastream_url="http://datastream.example/live",
            broker_url="http://broker.example/signals",
        )

    assert result["broker_dispatched"] is True
    assert result["broker_url"] == "http://broker.example/signals"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["datastream_url"] == "http://datastream.example/live"
    assert kwargs["json"]["broker_url"] == "http://broker.example/signals"


def test_run_model_before_login_raises():
    c = Client(base_url="http://test")
    with pytest.raises(RuntimeError, match="Not logged in"):
        c.run_model("m1", input_data=[[1.0]])