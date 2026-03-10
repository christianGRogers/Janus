#!/usr/bin/env python3
"""
Janus – End-to-End Use Case
============================

This script demonstrates the complete lifecycle of the Janus financial
inference platform:

  1. Start a local Janus server
  2. Register a new user & verify their email
  3. Log in (receive JWT + single-use API key)
  4. Register a compute node
  5. Train & upload a TensorFlow model
  6. Create a session (with datastream + broker URLs)
  7. Request a node for the session
  8. Run live inference  (datastream → model → broker)
  9. Run offline back-test (raw input_data → model)

Prerequisites
-------------
    pip install tensorflow numpy

Run
---
    python examples/end_to_end.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import threading
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── 0. Ensure the repo root is on the path ──────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Spin up mock datastream & broker servers + the Janus API
# ══════════════════════════════════════════════════════════════════════════════

def _start_mock_services():
    """Start a tiny HTTP server that acts as both a data stream and a broker.

    • GET  /market-data  → returns 5 rows of fake OHLCV data
    • POST /execute      → prints the received trade signals
    """
    received_signals: list = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # silence request logs

        def do_GET(self):
            if self.path == "/market-data":
                data = {
                    "data": [
                        [100.0, 102.0, 99.5, 101.0, 5000.0],
                        [101.0, 103.5, 100.0, 103.0, 6200.0],
                        [103.0, 104.0, 101.5, 102.5, 4800.0],
                        [102.5, 106.0, 102.0, 105.5, 7100.0],
                        [105.5, 107.0, 104.0, 106.0, 5500.0],
                    ]
                }
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/execute":
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length)) if length else {}
                received_signals.append(payload)
                n_signals = len(payload.get("signals", []))
                print(f"\n   🏦 Broker received {n_signals} trade signal(s)")
                body = json.dumps({"status": "ok", "executed": n_signals}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

    server = HTTPServer(("127.0.0.1", 5050), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)
    return received_signals


def _start_janus_server():
    """Start the Janus FastAPI server on port 8000 in a background thread."""
    import uvicorn
    from janus.server.app import app
    from janus.server import database as db

    # Fresh in-memory DB for the demo
    db.init_db(":memory:")

    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1)
    return app


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Create a tiny TensorFlow model and save it to disk
# ══════════════════════════════════════════════════════════════════════════════

def _create_demo_model() -> str:
    """Build a trivial Keras model (5 OHLCV features → 1 signal) and save it.

    Returns the path to the saved ``.keras`` file.
    """
    import numpy as np

    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # silence TF logs
    import tensorflow as tf

    # Simple model: 5 float inputs → Dense(8) → 1 float output
    model = tf.keras.Sequential([
        tf.keras.layers.Dense(8, activation="relu", input_shape=(5,)),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy")

    # Quick "training" on random data so the weights are non-trivial
    X = np.random.rand(50, 5).astype(np.float32)
    y = (X[:, 3] > X[:, 0]).astype(np.float32)  # 1 if close > open
    model.fit(X, y, epochs=3, verbose=0)

    path = os.path.join(tempfile.mkdtemp(), "demo_model.keras")
    model.save(path)
    print(f"   💾 Model saved to {path}")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — The main end-to-end flow using the Janus Client
# ══════════════════════════════════════════════════════════════════════════════

def main():
    JANUS_URL = "http://127.0.0.1:8000"
    DATASTREAM_URL = "http://127.0.0.1:5050/market-data"
    BROKER_URL = "http://127.0.0.1:5050/execute"

    banner = lambda msg: print(f"\n{'─' * 60}\n  {msg}\n{'─' * 60}")

    # ── 1. Start servers ─────────────────────────────────────────────────
    banner("1 ▸ Starting Janus server + mock datastream & broker")
    received_signals = _start_mock_services()
    _start_janus_server()
    print("   ✅ All services running")

    # ── 2. Train & save model ────────────────────────────────────────────
    banner("2 ▸ Creating demo TensorFlow model")
    model_path = _create_demo_model()

    # ── 3. Register + verify + login via Janus Client ────────────────────
    banner("3 ▸ User registration & authentication")
    from janus import Client
    client = Client(base_url=JANUS_URL)

    # Register
    result = client.register("alice@example.com", "SuperSecret123!")
    print(f"   📧 {result['message']}")

    # In production the user copies the token from the email.  Here we
    # grab it from the server's sent-email log (stub mode).
    from janus.server.auth import get_sent_emails
    emails = get_sent_emails()
    token = emails[-1]["token"]

    result = client.verify_email(token)
    print(f"   ✅ {result['message']}")

    # Login – stores JWT + API key
    login_data = client.login("alice@example.com", "SuperSecret123!")
    print(f"   🔑 Logged in as {login_data['email']}  (user_id={login_data['user_id']})")

    # ── 4. Register a compute node ───────────────────────────────────────
    banner("4 ▸ Registering a compute node")
    node = client.register_node()
    print(f"   🖥️  Node {node['id']} registered  (status={node['status']})")

    # ── 5. Upload the model ──────────────────────────────────────────────
    banner("5 ▸ Uploading TensorFlow model")
    model_info = client.upload_model(model_path, node_id=node["id"])
    model_id = model_info["model_id"]
    print(f"   📦 Model uploaded: {model_info['filename']}  (model_id={model_id})")

    # List models to confirm
    models = client.list_models()
    print(f"   📋 {len(models)} model(s) on server")

    # ── 6. Create a session with financial URLs ──────────────────────────
    banner("6 ▸ Creating a session")
    session = client.create_session("trading-session-1")
    # Override the default URLs with our mock services
    session.datastream_url = DATASTREAM_URL
    session.broker_url = BROKER_URL
    print(f"   📡 Session: {session}")

    # ── 7. Request a node for the session ────────────────────────────────
    banner("7 ▸ Requesting a node for the session")
    assign = session.request_node()
    print(f"   ✅ {assign['message']}")

    # ── 8. LIVE MODE — datastream → model → broker ──────────────────────
    banner("8 ▸ Running LIVE inference (datastream → model → broker)")
    live_result = client.run_model(
        model_id=model_id,
        datastream_url=DATASTREAM_URL,
        broker_url=BROKER_URL,
    )
    print(f"   📊 Predictions : {live_result['predictions']}")
    print(f"   📡 Broker URL  : {live_result['broker_url']}")
    print(f"   ✅ Dispatched  : {live_result['broker_dispatched']}")

    # ── 9. OFFLINE MODE — back-test with manual data ─────────────────────
    banner("9 ▸ Running OFFLINE back-test (raw input → model)")
    backtest_data = [
        [98.0, 100.0, 97.0, 99.5, 4200.0],
        [99.5, 101.0, 98.5, 100.0, 3800.0],
    ]
    offline_result = client.run_model(
        model_id=model_id,
        input_data=backtest_data,
    )
    print(f"   📊 Predictions : {offline_result['predictions']}")
    print(f"   📡 Broker URL  : {offline_result.get('broker_url', 'N/A')}")
    print(f"   ✅ Dispatched  : {offline_result['broker_dispatched']}")

    # ── 10. LIVE VIA SESSION — session.run_model() auto-injects URLs ────
    banner("10 ▸ Running inference via Session (auto datastream + broker)")
    session_result = session.run_model(model_id)
    print(f"   📊 Predictions : {session_result['predictions']}")
    print(f"   📡 Broker URL  : {session_result.get('broker_url', 'N/A')}")
    print(f"   ✅ Dispatched  : {session_result.get('broker_dispatched', False)}")

    # ── Summary ──────────────────────────────────────────────────────────
    banner("🎉  End-to-End Complete!")
    print(f"""
   User          : alice@example.com
   Node          : {node['id']}
   Model         : {model_id}  ({model_info['filename']})
   Session       : {session.id}
   Datastream    : {DATASTREAM_URL}
   Broker        : {BROKER_URL}
   Signals sent  : {len(received_signals)} dispatch(es) to broker
    """)


if __name__ == "__main__":
    main()
