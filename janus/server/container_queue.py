"""Pre-provisioned container queue to reduce user wait time.

This system maintains a pool of warm, ready-to-go containers that can be
instantly assigned to sessions. When a container is consumed, a new one
is provisioned in the background to maintain the pool size.

Configuration via environment variables:
    CONTAINER_QUEUE_SIZE      – Number of pre-provisioned containers (default: 5)
    CONTAINER_PROVISION_DELAY – Time between spawning queue containers (seconds, default: 2)
    CONTAINER_READY_TIMEOUT   – Max time to wait for container ready (seconds, default: 60)
"""

from __future__ import annotations

import os
import logging
import threading
import time
import uuid
from typing import Optional, List
from queue import Queue, Empty
from dataclasses import dataclass
from datetime import datetime, timezone

from .lxd_manager import LXDManager

logger = logging.getLogger(__name__)


@dataclass
class ProvisionedContainer:
    """A pre-provisioned container ready for assignment."""
    node_id: str
    container_name: str
    provisioned_at: str
    ready: bool = False


class ContainerQueue:
    """
    Pre-provisioned container queue that maintains a pool of ready containers.

    The queue operates in a background thread:
    1. Maintains a target pool size of N containers
    2. When a container is consumed, it spawns a new one
    3. Containers are tested for readiness before adding to pool
    4. Expired/unhealthy containers are cleaned up
    """

    def __init__(self, target_size: int = 5):
        self.target_size = target_size
        self.lxd_manager = LXDManager()
        self.provision_delay = float(os.environ.get("CONTAINER_PROVISION_DELAY", "2"))
        self.ready_timeout = float(os.environ.get("CONTAINER_READY_TIMEOUT", "60"))

        # Queue of ready containers: node_id → ProvisionedContainer
        self._ready_queue: Queue[ProvisionedContainer] = Queue(maxsize=target_size)

        # Track all containers by node_id
        self._all_containers: dict[str, ProvisionedContainer] = {}

        # Background provisioning thread
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Provisioning lock to avoid race conditions
        self._lock = threading.Lock()
        
        # Track consecutive provisioning failures to prevent runaway loop
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

    def start(self) -> None:
        """Start the background provisioning thread."""
        if self._running:
            logger.warning("ContainerQueue is already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._provisioning_loop, daemon=True)
        self._thread.start()
        logger.info(f"ContainerQueue started (target size: {self.target_size})")

    def stop(self) -> None:
        """Stop the background provisioning thread and clean up."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("ContainerQueue stopped")

    def _provisioning_loop(self) -> None:
        """Background loop that maintains the queue."""
        while self._running:
            try:
                current_size = self._ready_queue.qsize()
                needed = self.target_size - current_size

                if needed > 0:
                    # If too many consecutive failures, back off instead of spinning
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        logger.warning(f"Too many provisioning failures ({self._consecutive_failures}), backing off for 30s")
                        time.sleep(30)
                        self._consecutive_failures = 0
                        continue
                    
                    logger.info(f"Queue size: {current_size}/{self.target_size} – provisioning {needed} containers")
                    for _ in range(needed):
                        if not self._running:
                            break
                        self._provision_one_container()
                        time.sleep(self.provision_delay)

                # Periodically check health
                time.sleep(5)

            except Exception as exc:
                logger.error(f"Error in provisioning loop: {exc}")
                time.sleep(5)

    def _provision_one_container(self) -> None:
        """Provision a single container and add to queue if ready."""
        node_id = str(uuid.uuid4())
        try:
            logger.info(f"Provisioning container for node {node_id}")
            container_name = self.lxd_manager.provision_container(node_id)

            # Wait for container to be ready
            if self.lxd_manager.is_container_ready(node_id, max_retries=int(self.ready_timeout / 2)):
                pc = ProvisionedContainer(
                    node_id=node_id,
                    container_name=container_name,
                    provisioned_at=datetime.now(timezone.utc).isoformat(),
                    ready=True,
                )
                self._all_containers[node_id] = pc
                self._ready_queue.put(pc)
                logger.info(f"Container ready: {container_name} ({node_id})")
                self._consecutive_failures = 0  # Reset failure count on success
            else:
                logger.warning(f"Container failed to become ready: {node_id}")
                self._consecutive_failures += 1
                self.lxd_manager.teardown_container(node_id)

        except Exception as exc:
            logger.error(f"Failed to provision container: {exc}")
            self._consecutive_failures += 1

    def consume_container(self, timeout: float = 10.0) -> Optional[ProvisionedContainer]:
        """
        Get a pre-provisioned container from the queue.

        Blocks up to `timeout` seconds waiting for a container to become
        available. Returns None if timeout is exceeded.

        On success, the container is removed from the queue and will be
        replaced by a new one in the background.
        """
        try:
            pc = self._ready_queue.get(timeout=timeout)
            logger.info(f"Container consumed: {pc.container_name} ({pc.node_id})")
            return pc

        except Empty:
            logger.warning(f"No container available after {timeout}s timeout")
            return None

    def return_container(self, node_id: str) -> None:
        """
        Return a container to the queue after use.

        The container is checked for health. If healthy, it's re-added to
        the queue. If not, it's destroyed and replaced.
        """
        with self._lock:
            pc = self._all_containers.get(node_id)
            if not pc:
                logger.warning(f"Container {node_id} not in tracking")
                return

            # Check if container is still healthy
            status = self.lxd_manager.get_container_status(node_id)
            if status and status.get("metadata", {}).get("state") == "running":
                logger.info(f"Container returned to queue: {pc.container_name}")
                self._ready_queue.put(pc)
            else:
                logger.warning(f"Container unhealthy, destroying: {node_id}")
                try:
                    self.lxd_manager.teardown_container(node_id)
                except Exception as exc:
                    logger.error(f"Failed to teardown container: {exc}")
                del self._all_containers[node_id]

    def destroy_container(self, node_id: str) -> None:
        """Forcibly destroy a container (e.g., on error)."""
        with self._lock:
            try:
                self.lxd_manager.teardown_container(node_id)
                self._all_containers.pop(node_id, None)
                logger.info(f"Container destroyed: {node_id}")
            except Exception as exc:
                logger.error(f"Failed to destroy container {node_id}: {exc}")

    def queue_status(self) -> dict:
        """Get current queue statistics."""
        return {
            "target_size": self.target_size,
            "ready_count": self._ready_queue.qsize(),
            "total_provisioned": len(self._all_containers),
            "running": self._running,
        }

    def cleanup_all(self) -> None:
        """Destroy all provisioned containers (useful for shutdown)."""
        logger.info("Cleaning up all containers...")
        self.stop()

        for node_id in list(self._all_containers.keys()):
            try:
                self.lxd_manager.teardown_container(node_id)
            except Exception as exc:
                logger.error(f"Error cleaning up {node_id}: {exc}")

        self._all_containers.clear()
        logger.info("Cleanup complete")
