"""
Janus REST API – FastAPI application.

Run locally with:
    uvicorn janus.server.app:app --reload

Supports optional LXD container queue for pre-provisioned compute nodes.
Enable with: LXD_SOCKET or LXD_CLUSTER_ENDPOINT environment variables.
"""

from __future__ import annotations

import os
import uuid
import shutil
import sqlite3
import logging
import json
import subprocess
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends, Header, Query, UploadFile, File
from typing import List, Optional

from .models import (
    NodeRequestPayload,
    NodeRequestResponse,
    NodeInfo,
    RegisterNodePayload,
    ApiKeyResponse,
    RegisterPayload,
    LoginPayload,
    LoginResponse,
    UserResponse,
    MessageResponse,
    ModelInfo,
    RunModelRequest,
    RunModelResponse,
)
from .node_registry import NodeRegistry
from . import database as db
from . import auth
from janus import const

logger = logging.getLogger(__name__)

# ── App & shared state ────────────────────────────────────────────────────────

app = FastAPI(title="Janus Broker API", version="0.1.0")

# Optional: LXD container queue for pre-provisioned nodes
container_queue = None
try:
    lxd_socket = os.environ.get("LXD_SOCKET") or os.environ.get("LXD_CLUSTER_ENDPOINT")
    if lxd_socket:
        from .container_queue import ContainerQueue
        queue_size = int(os.environ.get("CONTAINER_QUEUE_SIZE", "5"))
        container_queue = ContainerQueue(target_size=queue_size)
        logger.info(f"LXD container queue initialized (target size: {queue_size})")
except Exception as exc:
    logger.warning(f"Failed to initialize container queue: {exc}")

# Node registry (with optional container queue backing)
registry = NodeRegistry(container_queue=container_queue)

# In-memory model metadata store:  model_id -> ModelInfo dict
model_store: dict[str, dict] = {}

# Directory where uploaded model files are saved.
MODEL_UPLOAD_DIR = os.environ.get("JANUS_MODEL_DIR", os.path.join(os.path.dirname(__file__), "_models"))

# LXD command location (usually at /snap/bin/lxc)
LXC_CMD = "/snap/bin/lxc"


# ── Lifecycle events ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Start the container queue on app startup."""
    if container_queue:
        container_queue.start()
        logger.info("Container queue started")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up container queue on app shutdown."""
    if container_queue:
        container_queue.cleanup_all()
        logger.info("Container queue stopped")


# ── Helpers ───────────────────────────────────────────────────────────────────

def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    Validate the ``Authorization: Bearer <jwt>`` header and return the
    decoded JWT payload (contains ``sub``, ``email``, etc.).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")
    try:
        return auth.decode_jwt(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=MessageResponse, status_code=201)
def register_user(payload: RegisterPayload):
    """Register a new user account and send a verification email."""
    password_hash = auth.hash_password(payload.password)
    try:
        user = db.create_user(email=payload.email, password_hash=password_hash)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Send verification token via email
    token = auth.create_email_token(payload.email)
    auth.send_verification_email(payload.email, token)
    return MessageResponse(message="Registration successful. Check your email to verify your account.")


@app.get("/auth/verify-email", response_model=MessageResponse)
def verify_email(token: str = Query(..., description="Signed email-verification token")):
    """Verify a user's email address via the token sent in the verification email."""
    try:
        email = auth.verify_email_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    updated = db.verify_user_email(email)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return MessageResponse(message=f"Email {email} verified successfully.")


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginPayload):
    """Log in with email + password.

    Returns a JWT bearer token **and** a fresh single-use API key.
    Only verified users may log in.  The API key is stored in the database
    and entitles the holder to register exactly one compute node.
    """
    user = db.get_user_by_email(payload.email)
    if user is None or not auth.check_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user["email_verified"]:
        raise HTTPException(status_code=403, detail="Email not verified. Please check your inbox.")

    jwt_token = auth.create_jwt(user_id=user["id"], email=user["email"])
    api_key_record = db.generate_api_key(user_id=user["id"])
    return LoginResponse(
        token=jwt_token,
        api_key=api_key_record["key"],
        user_id=user["id"],
        email=user["email"],
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Simple liveness probe."""
    health_info = {"status": "ok"}
    if container_queue:
        health_info["queue_status"] = container_queue.queue_status()
    return health_info


@app.get("/queue-status")
def get_queue_status(claims: dict = Depends(verify_token)):
    """Get current container queue statistics (requires authentication)."""
    if not container_queue:
        raise HTTPException(status_code=503, detail="Container queue not enabled")
    return container_queue.queue_status()


@app.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
def create_api_key(claims: dict = Depends(verify_token)):
    """Generate a new single-use API key.

    The key entitles the holder to register exactly one compute node via
    ``POST /nodes``.  Requires a valid JWT from a verified user.
    """
    # Double-check the user's email is still verified
    user = db.get_user_by_id(claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user["email_verified"]:
        raise HTTPException(status_code=403, detail="Email not verified")

    return db.generate_api_key(user_id=claims["sub"])


@app.get("/api-keys/{key}", response_model=ApiKeyResponse)
def get_api_key(key: str, claims: dict = Depends(verify_token)):
    """Look up metadata for an existing API key."""
    info = db.get_api_key_info(key)
    if info is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return ApiKeyResponse(
        key=info["key"],
        created_at=info["created_at"],
        used=bool(info["used"]),
        node_id=info["node_id"],
    )


@app.post("/nodes", response_model=NodeInfo, status_code=201)
def register_node(
    payload: RegisterNodePayload,
    x_api_key: str = Header(..., description="Single-use API key for node registration"),
):
    """Register a new compute node with the broker.

    Every node is created equal – the server auto-generates the node ID.
    Requires a valid, unused API key passed via the ``X-API-Key`` header.
    Each key can only be used once – to register exactly one node.
    """
    # Validate the key
    try:
        db.validate_api_key(x_api_key)
    except KeyError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    entry = registry.register()

    # Mark the key as consumed
    db.mark_key_used(x_api_key, node_id=entry.id)

    return NodeInfo(
        id=entry.id,
        status=entry.status,
        container_backed=entry.container_backed,
        container_name=entry.container_name,
    )


@app.get("/nodes", response_model=List[NodeInfo])
def list_nodes(available_only: bool = False):
    """List registered nodes, optionally filtered to available ones."""
    entries = registry.list_available() if available_only else registry.list_all()
    return [
        NodeInfo(
            id=e.id,
            status=e.status,
            container_backed=e.container_backed,
            container_name=e.container_name,
        )
        for e in entries
    ]


@app.post("/sessions/request_node", response_model=NodeRequestResponse)
def request_node(
    payload: NodeRequestPayload,
    claims: dict = Depends(verify_token),
):
    """
    Assign an available node to a session.

    The server automatically picks the first available node – the user does
    not choose.  The ``user_id`` is taken from the JWT claims.
    
    If the container queue is enabled, pre-provisioned containers are assigned
    first for lower latency. Falls back to traditional nodes if queue is empty.
    """
    user_id = claims["sub"]
    try:
        entry = registry.assign_any(
            session_id=payload.session_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return NodeRequestResponse(
        assigned=True,
        node_id=entry.id,
        session_id=payload.session_id,
        message=f"Node {entry.id} assigned to session {payload.session_id}",
    )


@app.post("/sessions/release_node/{node_id}", response_model=NodeInfo)
def release_node(node_id: str, claims: dict = Depends(verify_token)):
    """Release a node so it becomes available again.
    
    If the node is container-backed, it's returned to the queue for recycling.
    Health checks are performed before re-adding to the queue.
    """
    try:
        entry = registry.release(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    return NodeInfo(
        id=entry.id,
        status=entry.status,
        container_backed=entry.container_backed,
        container_name=entry.container_name,
    )


# ── TensorFlow model upload / run ────────────────────────────────────────────

@app.post("/models/upload", response_model=ModelInfo, status_code=201)
async def upload_model(
    file: UploadFile = File(...),
    node_id: Optional[str] = Query(None, description="Optional node to associate the model with"),
    claims: dict = Depends(verify_token),
):
    """Upload a TensorFlow SavedModel or .h5 file.

    The file is stored on the server and a ``model_id`` is returned that
    can be used with ``POST /models/{model_id}/run`` to execute inference.
    Supported extensions: ``.zip`` (SavedModel directory zipped), ``.h5``,
    ``.keras``.
    """
    allowed_extensions = (".zip", ".h5", ".keras")
    filename = file.filename or "model"
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}",
        )

    # If a node_id was given, make sure it exists
    if node_id is not None:
        entry = registry.get(node_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    model_id = str(uuid.uuid4())
    os.makedirs(MODEL_UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(MODEL_UPLOAD_DIR, f"{model_id}_{filename}")

    with open(dest, "wb") as fp:
        shutil.copyfileobj(file.file, fp)

    info = {
        "model_id": model_id,
        "filename": filename,
        "node_id": node_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "path": dest,
    }
    model_store[model_id] = info

    return ModelInfo(**{k: v for k, v in info.items() if k != "path"})


@app.get("/models", response_model=List[ModelInfo])
def list_models(claims: dict = Depends(verify_token)):
    """List all uploaded models."""
    return [
        ModelInfo(
            model_id=m["model_id"],
            filename=m["filename"],
            node_id=m.get("node_id"),
            uploaded_at=m["uploaded_at"],
        )
        for m in model_store.values()
    ]


@app.get("/models/{model_id}", response_model=ModelInfo)
def get_model(model_id: str, claims: dict = Depends(verify_token)):
    """Get metadata for a specific model."""
    m = model_store.get(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return ModelInfo(
        model_id=m["model_id"],
        filename=m["filename"],
        node_id=m.get("node_id"),
        uploaded_at=m["uploaded_at"],
    )


@app.post("/models/{model_id}/run", response_model=RunModelResponse)
def run_model(model_id: str, payload: RunModelRequest, claims: dict = Depends(verify_token)):
    """Run financial inference on an uploaded TensorFlow model.

    The endpoint supports two modes:

    1. **Live mode** – provide ``datastream_url`` to pull real-time market
       data and ``broker_url`` to dispatch the resulting trade signals.
    2. **Offline mode** – provide ``input_data`` directly (e.g. for
       back-testing).

    If both ``datastream_url`` and ``input_data`` are supplied the data
    stream takes priority.  When ``broker_url`` is given the predictions
    are POSTed there as ``{"signals": [[...]]}``.

    If a ``node_id`` is associated with the model, the inference request
    is forwarded to that compute node. Otherwise, requires ``tensorflow``
    to be installed on the broker server.
    """
    import requests as _requests

    m = model_store.get(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")

    model_path = m["path"]
    if not os.path.exists(model_path):
        raise HTTPException(status_code=500, detail="Model file missing from disk")

    # ── resolve input data ────────────────────────────────────────────────
    if payload.datastream_url:
        try:
            ds_resp = _requests.get(payload.datastream_url, timeout=30)
            ds_resp.raise_for_status()
            ds_json = ds_resp.json()
            # Accept {"data": [[...]]} or a bare 2-D list
            input_data = ds_json.get("data", ds_json) if isinstance(ds_json, dict) else ds_json
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch data from datastream: {exc}",
            )
    elif payload.input_data is not None:
        input_data = payload.input_data
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either datastream_url or input_data",
        )

    # ── check if model is associated with a compute node ──────────────────
    node_id = m.get("node_id")
    if node_id:
        node_entry = registry.get(node_id)
        if node_entry and node_entry.container_backed:
            # Forward inference to the compute node via container
            container_name = node_entry.container_name
            try:
                # Copy model file to container
                logger.info(f"Copying model {model_id} to container {container_name}")
                subprocess.run(
                    [LXC_CMD, "file", "push", model_path, f"{container_name}/root/models/"],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                
                # Create inference script that will run on the node
                model_filename = os.path.basename(model_path)
                remote_model_path = f"/root/models/{model_filename}"
                inference_script = f"""
import sys
import json
import numpy as np
import tensorflow as tf

try:
    model_path = "{remote_model_path}"
    if model_path.endswith(".h5") or model_path.endswith(".keras"):
        tf_model = tf.keras.models.load_model(model_path)
    elif model_path.endswith(".zip"):
        import tempfile, zipfile
        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(model_path, "r") as zf:
            zf.extractall(extract_dir)
        tf_model = tf.keras.models.load_model(extract_dir)
    else:
        raise ValueError("Unsupported model format")
    
    # Run inference
    input_data = {json.dumps(input_data)}
    input_array = np.array(input_data, dtype=np.float32)
    predictions = tf_model.predict(input_array).tolist()
    print(json.dumps({{"predictions": predictions}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}), file=sys.stderr)
    sys.exit(1)
"""
                
                # Execute inference on the node
                logger.info(f"Running inference on node container {container_name}")
                result = subprocess.run(
                    [LXC_CMD, "exec", container_name, "--", "python3", "-c", inference_script],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                
                if result.returncode == 0:
                    try:
                        output = json.loads(result.stdout.strip())
                        if "error" in output:
                            logger.warning(f"Node inference error: {output['error']}, falling back to local")
                        else:
                            predictions = output["predictions"]
                            logger.info(f"Successfully ran inference on node {node_id}")
                            
                            # Dispatch to broker if needed
                            broker_dispatched = False
                            if payload.broker_url:
                                try:
                                    broker_resp = _requests.post(
                                        payload.broker_url,
                                        json={"signals": predictions},
                                        timeout=30,
                                    )
                                    broker_resp.raise_for_status()
                                    broker_dispatched = True
                                except Exception as exc:
                                    raise HTTPException(
                                        status_code=502,
                                        detail=f"Failed to dispatch signals to broker: {exc}",
                                    )
                            
                            return RunModelResponse(
                                model_id=model_id,
                                predictions=predictions,
                                broker_url=payload.broker_url,
                                broker_dispatched=broker_dispatched,
                            )
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse node response: {e}, falling back to local")
                else:
                    logger.warning(f"Node inference failed: {result.stderr}, falling back to local")
                    
            except Exception as exc:
                logger.warning(f"Failed to execute inference on node {node_id}: {exc}, falling back to local execution")

    # ── fall back to local inference ──────────────────────────────────────
    try:
        import tensorflow as tf
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="TensorFlow is not installed on this server. Install it with: pip install tensorflow",
        )

    try:
        if model_path.endswith(".h5") or model_path.endswith(".keras"):
            tf_model = tf.keras.models.load_model(model_path)
        elif model_path.endswith(".zip"):
            import tempfile, zipfile

            extract_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(model_path, "r") as zf:
                zf.extractall(extract_dir)
            tf_model = tf.keras.models.load_model(extract_dir)
        else:
            raise HTTPException(status_code=400, detail="Unrecognised model format")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load model: {exc}")

    # ── run inference ─────────────────────────────────────────────────────
    try:
        import numpy as np

        input_array = np.array(input_data, dtype=np.float32)
        predictions = tf_model.predict(input_array).tolist()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Inference failed: {exc}")

    # ── dispatch to broker ────────────────────────────────────────────────
    broker_dispatched = False
    if payload.broker_url:
        try:
            broker_resp = _requests.post(
                payload.broker_url,
                json={"signals": predictions},
                timeout=30,
            )
            broker_resp.raise_for_status()
            broker_dispatched = True
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to dispatch signals to broker: {exc}",
            )

    return RunModelResponse(
        model_id=model_id,
        predictions=predictions,
        broker_url=payload.broker_url,
        broker_dispatched=broker_dispatched,
    )