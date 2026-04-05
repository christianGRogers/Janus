# Janus

Janus is a financial inference platform that connects TensorFlow models to live market data streams and trade execution brokers. Register an account, spin up compute nodes, upload trained models, and run inference — market data flows in from a data stream, predictions flow out to your broker of choice.

## Installation

### Server (local development)

```bash
pip install -e .
```

For development (includes pytest and httpx):

```bash
pip install -e ".[dev]"
```

### Production with LXD Container Queue

Janus can provision compute nodes on-demand using LXD containers. Each container runs a pre-built image with all dependencies and a Python venv at `/opt/janus-env`.

**Setup the image once:**

```bash
bash setup-lxd-queue.sh
```

This creates the `from-instance-flying-oarfish` LXD image with TensorFlow, NumPy, and other ML libraries pre-installed.

See [`deploy/SETUP_COMPUTE_NODE_IMAGE.md`](deploy/SETUP_COMPUTE_NODE_IMAGE.md) for detailed instructions.

## Quick Start

### 1. Start the server (local development)

```bash
uvicorn janus.server.app:app --reload
```

### 1. Start the server with LXD container queue (production)

```bash
bash start-server-with-lxd.sh
```

This starts the server and enables the container queue. Compute nodes are provisioned on-demand from the `from-instance-flying-oarfish` image.

### 2. Register, log in, deploy a financial model

```python
from janus import Client

# Point at your running server
client = Client(base_url="http://localhost:8000")

# Create an account (sends a verification email)
client.register("you@example.com", "your-password")

# Verify your email (paste the token from the email you received)
client.verify_email("the-token-from-your-email")

# Log in (stores JWT + API key automatically)
client.login("you@example.com", "your-password")

# Register a compute node (server auto-generates the node ID)
node = client.register_node()
node_id = node["id"]

# Upload your trained TensorFlow model
result = client.upload_model("path/to/my_model.h5", node_id=node_id)
model_id = result["model_id"]

# Create a session wired to your data stream and broker
session = client.create_session()
session.datastream_url = "https://your-market-data-provider.com/live"
session.broker_url = "https://your-broker-api.com/signals"

# Request a node for the session
session.request_node()

# Run inference: data stream → model → broker
result = session.run_model(model_id)
print(result["predictions"])        # model output (trade signals)
print(result["broker_dispatched"])  # True if signals were sent to broker
```

### Offline back-testing

You can also pass raw data directly instead of a live data stream:

```python
result = session.run_model(model_id, input_data=[[1.23, 4.56, 7.89]])
print(result["predictions"])
```

## Deployment Architecture

### Local Development

Single-machine setup: Janus server runs locally, models run in-process.

```
┌─────────────────────────────────────┐
│  Janus Server (local)               │
│  ├─ TensorFlow (in-process)         │
│  ├─ Model uploads & storage         │
│  └─ User API                        │
└─────────────────────────────────────┘
```

Start with: `uvicorn janus.server.app:app --reload`

### Production with LXD

Distributed setup: Janus server orchestrates containerized compute nodes.

```
┌─────────────────────────────────────┐
│  Janus Server (on LXD host)         │
│  ├─ Model registry                  │
│  ├─ Container queue manager         │
│  └─ User API                        │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│  LXD Container Pool                 │
│  ├─ [Compute Node 1]                │
│  │  └─ /opt/janus-env venv          │
│  │  └─ TensorFlow + dependencies    │
│  ├─ [Compute Node 2]                │
│  │  └─ /opt/janus-env venv          │
│  │  └─ TensorFlow + dependencies    │
│  └─ [... pre-provisioned pool ...]  │
└─────────────────────────────────────┘
```

**Key features:**

- **Pre-provisioned queue:** Containers are always ready (no startup latency)
- **Auto-scaling:** New containers spawn in background to maintain pool size
- **Venv activation:** Python dependencies auto-activated per-container
- **Efficient:** Shared image + copy-on-write storage = minimal overhead

Start with: `bash start-server-with-lxd.sh`

## How It Works

### Local (In-Process)

```
┌──────────────┐       ┌────────────────┐       ┌──────────────┐
│  Data Stream  │──────▶│  Janus Server  │──────▶│    Broker    │
│  (market data)│       │  (TF model)    │       │  (trade exec)│
└──────────────┘       └────────────────┘       └──────────────┘
```

### Containerized (LXD)

```
┌──────────────┐       ┌────────────────┐  Container  ┌──────────────┐
│  Data Stream  │──────▶│  Janus Server  │─Queue──────▶│  LXD Node    │
│  (market data)│       │  (orchestrate) │             │ (TF model)   │
└──────────────┘       └────────────────┘             └──────────────┘
                                │                         │
                                └─────────Activate venv──┘
                                  /opt/janus-env/bin/activate
                                     │
                                     └─→ python3 (with all packages)
                                          ├─ TensorFlow
                                          ├─ NumPy
                                          ├─ Pandas
                                          └─ scikit-learn
```

**Flow:**

1. **Data Stream** — Janus fetches live market data from your `datastream_url`.
2. **Queue Assignment** — Janus picks a pre-provisioned container from the queue.
3. **Venv Activation** — Container's Python venv (`/opt/janus-env`) is auto-activated.
4. **Inference** — TensorFlow model runs in the container and produces trade signals.
5. **Broker** — Signals are dispatched via POST to your `broker_url`.
6. **Queue Refresh** — Container is returned to the pool; a new one is spawned in background.

## API Reference

### Authentication

| Endpoint | Method | Description |
|---|---|---|
| `/auth/register` | POST | Create a new account. Sends a verification email. |
| `/auth/verify-email?token=` | GET | Verify email address using the token from the email. |
| `/auth/login` | POST | Log in. Returns a JWT and a single-use API key. |

### API Keys

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api-keys` | POST | JWT | Generate an additional single-use API key. |
| `/api-keys/{key}` | GET | JWT | Look up metadata for an existing API key. |

### Nodes

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/nodes` | POST | API Key | Register a new compute node. Server auto-generates the ID. |
| `/nodes` | GET | — | List all registered nodes. Use `?available_only=true` to filter. |

### Sessions

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/sessions/request_node` | POST | JWT | Auto-assign an available node to a session. |
| `/sessions/release_node/{node_id}` | POST | JWT | Release a node back to the available pool. |

### Models (TensorFlow)

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/models/upload` | POST | JWT | Upload a `.h5`, `.keras`, or `.zip` (SavedModel) file. |
| `/models` | GET | JWT | List all uploaded models. |
| `/models/{model_id}` | GET | JWT | Get metadata for a specific model. |
| `/models/{model_id}/run` | POST | JWT | Run inference. Accepts `datastream_url`, `broker_url`, and/or `input_data`. |

### Health

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness probe. Returns `{"status": "ok"}`. |

## Client Methods

| Method | Description |
|---|---|
| `Client(base_url=None)` | Create a client. Defaults to `https://api.bradensbay.com`. |
| `client.register(email, password)` | Register a new account. |
| `client.verify_email(token)` | Verify email with the token from the verification email. |
| `client.login(email, password)` | Log in. Stores JWT + API key for subsequent calls. |
| `client.request_api_key()` | Generate an additional single-use API key. |
| `client.register_node()` | Register a node (consumes the API key). |
| `client.create_session(session_id=None)` | Create a `Session` pre-configured with the stored JWT. |
| `client.upload_model(file_path, node_id=None)` | Upload a TensorFlow model file. |
| `client.list_models()` | List all uploaded models. |
| `client.run_model(model_id, ...)` | Run inference with optional `datastream_url`, `broker_url`, `input_data`. |

## Session

Each `Session` holds a `datastream_url` (market data source) and a `broker_url` (trade execution target). When you call `session.run_model(model_id)`, those URLs are sent to the server automatically:

| Property / Method | Description |
|---|---|
| `session.datastream_url` | URL the server fetches market data from. |
| `session.broker_url` | URL the server POSTs trade signals to. |
| `session.run_model(model_id, input_data=None)` | Run inference. Uses the session's data stream and broker. |
| `session.request_node()` | Auto-assign a compute node to this session. |

## Notes

- **Financial inference** — models consume live market data from a data stream and output trade signals to a broker API.
- **Nodes are uniform** — `register_node()` takes no arguments. The server assigns a UUID automatically.
- **API keys are single-use** — each key registers exactly one node. Call `client.request_api_key()` before registering additional nodes.
- **Model inference requires TensorFlow** on the server. Supported upload formats: `.h5`, `.keras`, `.zip` (zipped SavedModel directory).
- **Email verification** is required before you can log in or generate API keys.

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

[GPL-3.0](LICENSE)
