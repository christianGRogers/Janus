# Deployment Changes Summary

This document summarizes the changes made to support containerized inference with automatic Python venv activation.

## Overview

The Janus project now assumes that the LXD image (`from-instance-flying-oarfish`) has a Python venv pre-installed at `/opt/janus-env` with all necessary dependencies. The venv is **automatically activated** whenever inference commands are executed in containers.

## Key Changes

### 1. **setup-lxd-queue.sh** – Image Creation
- **Changed:** Updated to create and use a Python venv at `/opt/janus-env`
- **Before:** Installed packages to system Python (`pip3`)
- **After:** Creates venv first, then installs packages to `/opt/janus-env/bin/pip`
- **Benefit:** Isolates dependencies; no conflicts with system packages

**Key lines:**
```bash
lxc exec "$TEMP_CONTAINER" -- python3 -m venv /opt/janus-env
lxc exec "$TEMP_CONTAINER" -- /opt/janus-env/bin/pip install tensorflow numpy ...
```

### 2. **lxd_manager.py** – Command Execution Wrapper
- **Changed:** Modified `execute_command()` to wrap all container commands with venv activation
- **Before:** Commands ran as-is in containers
- **After:** All commands automatically activate `/opt/janus-env/bin/activate` before execution

**Implementation:**
```python
wrapped_command = [
    "bash",
    "-c",
    f"source /opt/janus-env/bin/activate && {' '.join(command)}"
]
```

**Benefit:** No manual activation needed; Python packages are always available.

### 3. **start-server-with-lxd.sh** – Documentation Update
- **Added:** Explicit comment documenting the venv assumption
- **Purpose:** Makes it clear that the image must have `/opt/janus-env` pre-configured

### 4. **README.md** – Documentation & Architecture
- **Added:** Deployment architecture diagrams (local vs. LXD)
- **Added:** New "Installation" section with separate instructions for dev vs. production
- **Added:** Containerized workflow explanation with venv activation flow
- **Reorganized:** Quick Start section to show both dev and production paths

### 5. **deploy/SETUP_COMPUTE_NODE_IMAGE.md** – New Setup Guide
- **Created:** Comprehensive guide for building the `from-instance-flying-oarfish` image
- **Includes:** Automated script instructions + manual step-by-step
- **Covers:** Venv creation, package installation, image publishing, troubleshooting

## Deployment Workflow

### Step 1: Create the LXD Image (One-time)
```bash
bash setup-lxd-queue.sh
```
This creates `from-instance-flying-oarfish` with `/opt/janus-env` venv.

### Step 2: Start Janus Server with Container Queue
```bash
bash start-server-with-lxd.sh
```
The server:
- Verifies the `from-instance-flying-oarfish` image exists
- Starts the pre-provisioning queue (maintains N warm containers)
- Automatically activates `/opt/janus-env` when running inference

### Step 3: Deploy Models & Run Inference
```python
from janus import Client
client = Client(base_url="http://localhost:8000")
client.register("user@example.com", "password")
client.login("user@example.com", "password")
node = client.register_node()
model_id = client.upload_model("model.h5", node_id=node["id"])["model_id"]
result = client.run_model(model_id, input_data=[[1, 2, 3]])
```

When `run_model` is called:
1. Server picks a pre-provisioned container from the queue
2. `lxd_manager.py` wraps the inference command with venv activation
3. TensorFlow model runs with all dependencies available
4. Predictions are returned
5. Container is returned to the pool

## Environment Variables

### Required (for production):
- `LXD_SOCKET` – Unix socket path (default: `/var/snap/lxd/common/lxd/unix.socket`)
- `LXD_IMAGE_FINGERPRINT` – LXD image fingerprint (default: `b03058e361bf`, see `janus.const.LXD_COMPUTE_NODE_FINGERPRINT`)

### Optional (tuning):
- `LXD_CPU_LIMIT` – CPU cores per container (default: 2)
- `LXD_MEMORY_LIMIT` – Memory per container in MB (default: 2048)
- `CONTAINER_QUEUE_SIZE` – Number of pre-provisioned containers (default: 5)
- `CONTAINER_PROVISION_DELAY` – Seconds between spawning (default: 2)
- `CONTAINER_READY_TIMEOUT` – Max wait for container ready (default: 60)

## File Changes Summary

| File | Change | Reason |
|------|--------|--------|
| `setup-lxd-queue.sh` | Create `/opt/janus-env` venv | Isolate dependencies |
| `lxd_manager.py` | Wrap commands with venv activation | Auto-activate on execution |
| `start-server-with-lxd.sh` | Add documentation comment | Clarify assumptions |
| `README.md` | Add deployment architecture section | Explain local vs. containerized |
| `deploy/SETUP_COMPUTE_NODE_IMAGE.md` | New guide | Document image creation |

## Assumptions

The solution assumes:

1. ✅ LXD is installed and running on the host
2. ✅ The `from-instance-flying-oarfish` image has been created (via `setup-lxd-queue.sh`)
3. ✅ Each container in the image has `/opt/janus-env` venv pre-installed
4. ✅ All Python packages (TensorFlow, NumPy, etc.) are installed in the venv
5. ✅ The venv's `bash` and `python3` can be activated via `source /opt/janus-env/bin/activate`

## Testing

### Verify Image Creation
```bash
lxc image info from-instance-flying-oarfish
```

### Verify Venv in Container
```bash
lxc launch from-instance-flying-oarfish test-node
lxc exec test-node -- /opt/janus-env/bin/python3 -c "import tensorflow; print('OK')"
lxc delete test-node -f
```

### Verify Server with Queue
```bash
bash start-server-with-lxd.sh
# In another terminal:
curl http://localhost:8000/health
```

## Future Enhancements

- [ ] Add GPU support (requires NVIDIA in LXD)
- [ ] Multi-venv images (Python 3.9, 3.10, 3.11 side-by-side)
- [ ] Automatic image updates via CI/CD
- [ ] Health checks for venv + packages
- [ ] Custom package lists per image variant

## Support

For issues:

1. Check `deploy/SETUP_COMPUTE_NODE_IMAGE.md` troubleshooting section
2. Verify container is running: `lxc list`
3. Check venv: `lxc exec janus-node-<id> -- ls -la /opt/janus-env/`
4. Check TensorFlow: `lxc exec janus-node-<id> -- /opt/janus-env/bin/python3 -c "import tensorflow"`
5. Review Janus server logs: `stderr` from `start-server-with-lxd.sh`
