# Janus

Janus is a financial inference platform that connects TensorFlow models to live market data streams and trade execution brokers. Register an account, spin up compute nodes, upload trained models, and run inference — market data flows in from a data stream, predictions flow out to your broker of choice.

## Installation

```bash
pip install -e .
```

For development (includes pytest and httpx):

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Start the server

```bash
uvicorn janus.server.app:app --reload
```

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

## How It Works

```
┌──────────────┐       ┌────────────────┐       ┌──────────────┐
│  Data Stream  │──────▶│  Janus Server  │──────▶│    Broker    │
│  (market data)│       │  (TF model)    │       │  (trade exec)│
└──────────────┘       └────────────────┘       └──────────────┘
```

1. **Data Stream** — Janus fetches live market data from your `datastream_url` (expects JSON with a `"data"` key or a bare 2-D array).
2. **Inference** — The uploaded TensorFlow model runs on the data and produces trade signals.
3. **Broker** — Signals are dispatched as `{"signals": [[...]]}` via POST to your `broker_url`.

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
