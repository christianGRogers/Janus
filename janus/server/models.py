"""Pydantic models for API request / response payloads."""

from pydantic import BaseModel, EmailStr
from typing import Optional, List


# ── Requests ──────────────────────────────────────────────────────────────────

class NodeRequestPayload(BaseModel):
    """Body sent by the client's Session.request_node()."""
    session_id: str


# ── Responses ─────────────────────────────────────────────────────────────────

class NodeRequestResponse(BaseModel):
    assigned: bool
    node_id: str
    session_id: str
    message: str


class NodeInfo(BaseModel):
    id: str
    status: str
    container_backed: bool = False
    container_name: Optional[str] = None


class RegisterNodePayload(BaseModel):
    """Body for registering a new node with the broker.

    Every node is created equal – the server auto-generates the ID.
    The payload is intentionally empty but exists so the endpoint keeps a
    JSON-body contract for future extensibility.
    """
    pass


# ── API Keys ──────────────────────────────────────────────────────────────────

class ApiKeyResponse(BaseModel):
    """Returned when a new API key is generated."""
    key: str
    created_at: str
    used: bool = False
    node_id: Optional[str] = None


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterPayload(BaseModel):
    """Body for user registration."""
    email: EmailStr
    password: str


class LoginPayload(BaseModel):
    """Body for user login."""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Returned on successful login."""
    token: str
    api_key: str
    user_id: str
    email: str


class UserResponse(BaseModel):
    """Public user info."""
    id: str
    email: str
    email_verified: bool
    created_at: str


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# ── Models (TensorFlow – Financial Inference) ─────────────────────────────────

class ModelInfo(BaseModel):
    """Metadata about an uploaded TensorFlow model."""
    model_id: str
    filename: str
    node_id: Optional[str] = None
    uploaded_at: str


class RunModelRequest(BaseModel):
    """Input payload for running financial inference on an uploaded model.

    The model reads market data from ``datastream_url`` and sends its
    trade signals to ``broker_url``.  Alternatively, raw ``input_data``
    can be supplied directly for back-testing or offline evaluation.
    """
    datastream_url: Optional[str] = None
    broker_url: Optional[str] = None
    input_data: Optional[List[List[float]]] = None


class RunModelResponse(BaseModel):
    """Inference results from a financial model run."""
    model_id: str
    predictions: List[List[float]]
    broker_url: Optional[str] = None
    broker_dispatched: bool = False


# ── Container Queue ──────────────────────────────────────────────────────────

class QueueStatus(BaseModel):
    """Status of the pre-provisioned container queue."""
    target_size: int
    ready_count: int
    total_provisioned: int
    running: bool
    broker_dispatched: bool = False
