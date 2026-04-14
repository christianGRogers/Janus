#!/usr/bin/env python3
"""Minimal script: register, login, grab node, upload trivial model."""

import os
import sys
import tempfile

# Add repo to path if needed
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from janus import Client
import requests

# ─── Configuration ───────────────────────────────────────────────────────────
JANUS_URL = "https://janus.bradensbay.com"
EMAIL = "christiangrrogers@gmail.com"
PASSWORD = "TestPassword123!"

# ─── Step 1: Create a trivial TensorFlow model ───────────────────────────────
print("📦 Creating trivial TensorFlow model...")
try:
    import numpy as np
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # silence TF logs
    import tensorflow as tf

    model = tf.keras.Sequential([
        tf.keras.layers.Dense(4, activation="relu", input_shape=(5,)),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])
    model.compile(optimizer="adam", loss="binary_crossentropy")

    # Quick fit on random data
    X = np.random.rand(20, 5).astype(np.float32)
    y = (X[:, 0] > 0.5).astype(np.float32)
    model.fit(X, y, epochs=2, verbose=0)

    model_path = os.path.join(tempfile.mkdtemp(), "trivial_model.keras")
    model.save(model_path)
    print(f"   ✅ Model saved to {model_path}")
except ImportError as e:
    print(f"   ⚠️  TensorFlow not available: {e}")
    print("   Using pre-built model file instead...")
    # Use the existing demo model from examples
    model_path = "janus/server/_models/6e03ac72-1eed-48ba-aa50-a0c0611d13b0_demo_model.keras"
    if not os.path.exists(model_path):
        print(f"   ❌ Model file not found at {model_path}")
        sys.exit(1)
    print(f"   ✅ Using existing model: {model_path}")

# ─── Step 2: Register account ────────────────────────────────────────────────
print(f"\n📧 Registering account {EMAIL}...")
client = Client(base_url=JANUS_URL)
try:
    result = client.register(EMAIL, PASSWORD)
    print(f"   ✅ {result['message']}")
    
    # ─── Step 3: Verify email (user inputs token) ──────────────────────────────
    print("\n✉️  Verifying email...")
    print(f"   📨 Check your email inbox for a verification token.")
    token = input("   🔑 Paste the token here: ").strip()
    result = client.verify_email(token)
    print(f"   ✅ {result['message']}")
except requests.exceptions.HTTPError as e:
    if "already registered" in str(e):
        print(f"   ℹ️  Account already exists, skipping registration and verification")
    else:
        raise

# ─── Step 4: Log in ──────────────────────────────────────────────────────────
print(f"\n🔑 Logging in...")
login_data = client.login(EMAIL, PASSWORD)
print(f"   ✅ Logged in: {login_data['email']} (user_id={login_data['user_id']})")

# ─── Step 5: Register a node ────────────────────────────────────────────────
print(f"\n🖥️  Registering compute node...")
node = client.register_node()
node_id = node["id"]
print(f"   ✅ Node registered: {node_id} (status={node['status']})")

# ─── Step 6: Upload model to the node ───────────────────────────────────
print(f"\n📤 Uploading model to node {node_id}...")
model_info = client.upload_model(model_path, node_id=node_id)
model_id = model_info["model_id"]
print(f"   ✅ Model uploaded: {model_info['filename']} (model_id={model_id})")

# ─── Step 7: Run the model with offline data ─────────────────────────────────
print(f"\n🚀 Running model inference...")
sample_data = [
    [100.0, 102.0, 99.5, 101.0, 5000.0],
    [101.0, 103.5, 100.0, 103.0, 6200.0],
    [103.0, 104.0, 101.5, 102.5, 4800.0],
]
run_result = client.run_model(model_id=model_id, input_data=sample_data)
print(f"   ✅ Predictions: {run_result['predictions']}")
print(f"   ✅ Broker dispatched: {run_result['broker_dispatched']}")

# ─── Summary ─────────────────────────────────────────────────────────
print(f"""
✨ Done!
   Email     : {EMAIL}
   User ID   : {login_data['user_id']}
   Node ID   : {node_id}
   Model ID  : {model_id}
   File      : {model_info['filename']}
   Predictions: {run_result['predictions']}
""")
