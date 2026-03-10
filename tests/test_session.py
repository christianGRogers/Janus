import pytest
import requests
from unittest.mock import Mock, patch

from janus import Session


def make_session():
    return Session(
        id="s1",
        user_id="u1",
        token="tok",
        created_at="2026-03-09T00:00:00Z",
        broker_url="https://broker.example",
        datastream_url="https://ds.example",
    )


def test_request_node_success():
    session = make_session()

    expected = {"assigned": True, "node_id": "n1", "session_id": "s1", "message": "Node n1 assigned"}

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = expected

    with patch("janus.session.requests.post", return_value=mock_resp) as mock_post:
        result = session.request_node()

        assert result == expected
        assert session.node is not None
        assert session.node.id == "n1"
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["session_id"] == "s1"
        assert "node_id" not in kwargs["json"]
        assert "user_id" not in kwargs["json"]
        assert "Authorization" in kwargs["headers"]


def test_request_node_http_error_raises():
    session = make_session()

    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.RequestException("bad")

    with patch("janus.session.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.RequestException):
            session.request_node()


def test_add_inference_model_detects_frameworks():
    session = make_session()

    # simulate a torch model
    TorchFake = type("TorchFake", (), {})
    TorchFake.__module__ = "torch.nn"
    torch_obj = TorchFake()
    session.add_inference_model(torch_obj)
    assert session.model_type == "pytorch"

    # simulate a tensorflow model
    TFFake = type("TFFake", (), {})
    TFFake.__module__ = "tensorflow.keras"
    tf_obj = TFFake()
    session.add_inference_model(tf_obj)
    assert session.model_type == "tensorflow"

    # unknown
    Unknown = type("Unknown", (), {})
    Unknown.__module__ = "some.random.module"
    unk = Unknown()
    session.add_inference_model(unk)
    assert session.model_type == "unknown"


def test_request_node_sets_node_status():
    """Node created after request_node should have status 'assigned'."""
    session = make_session()

    expected = {"assigned": True, "node_id": "n1", "session_id": "s1", "message": "ok"}

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = expected

    with patch("janus.session.requests.post", return_value=mock_resp):
        session.request_node()
        assert session.node.status == "assigned"


def test_run_model_sends_datastream_and_broker():
    """Session.run_model() should send its datastream_url and broker_url."""
    session = make_session()

    expected = {
        "model_id": "m1",
        "predictions": [[0.95, 0.05]],
        "broker_url": "https://broker.example",
        "broker_dispatched": True,
    }

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = expected

    with patch("janus.session.requests.post", return_value=mock_resp) as mock_post:
        result = session.run_model("m1")

        assert result == expected
        assert result["broker_dispatched"] is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["datastream_url"] == "https://ds.example"
        assert kwargs["json"]["broker_url"] == "https://broker.example"
        assert "input_data" not in kwargs["json"]
        assert "Authorization" in kwargs["headers"]


def test_run_model_with_input_data_override():
    """Passing input_data should include it in the payload (offline mode)."""
    session = make_session()

    expected = {
        "model_id": "m1",
        "predictions": [[1.0]],
        "broker_url": "https://broker.example",
        "broker_dispatched": True,
    }

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = expected

    with patch("janus.session.requests.post", return_value=mock_resp) as mock_post:
        result = session.run_model("m1", input_data=[[1.0, 2.0]])

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input_data"] == [[1.0, 2.0]]
        # datastream_url is still sent – server gives it priority over input_data
        assert kwargs["json"]["datastream_url"] == "https://ds.example"


def test_run_model_http_error_raises():
    session = make_session()

    mock_resp = Mock()
    mock_resp.raise_for_status.side_effect = requests.exceptions.RequestException("bad")

    with patch("janus.session.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.RequestException):
            session.run_model("m1")