"""In-memory registry that tracks nodes and their assignments.

Extended with LXD container support: nodes can be backed by pre-provisioned
containers from a queue to reduce assignment latency.
"""

from __future__ import annotations
import uuid
import logging
from typing import Dict, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .container_queue import ContainerQueue

logger = logging.getLogger(__name__)


class NodeEntry:
    """Internal record for a registered node, optionally backed by an LXD container."""

    def __init__(self, id: str | None = None, container_name: str | None = None):
        self.id = id or str(uuid.uuid4())
        self.status: str = "available"          # available | assigned
        self.assigned_session_id: Optional[str] = None
        self.model_id: Optional[str] = None     # uploaded model reference
        self.container_name: Optional[str] = container_name  # LXD container backing this node
        self.container_backed: bool = container_name is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "assigned_session_id": self.assigned_session_id,
            "model_id": self.model_id,
            "container_backed": self.container_backed,
            "container_name": self.container_name,
        }


class NodeRegistry:
    """
    In-memory store of compute nodes with optional LXD container queue integration.

    Nodes can be:
    1. Created via API key registration (classic mode)
    2. Pulled from a pre-provisioned container queue (queue mode)

    Queue mode requires ContainerQueue to be initialized and started.
    """

    def __init__(self, container_queue=None) -> None:
        self._nodes: Dict[str, NodeEntry] = {}
        self.container_queue = container_queue

    # ── mutators ──────────────────────────────────────────────────────────

    def register(self, id: str | None = None) -> NodeEntry:
        """Register a new node (or re-register an existing one).

        If container_queue is available, pulls a pre-provisioned container
        to back this node (reducing assignment latency).
        """
        entry = NodeEntry(id=id)

        # Try to get a pre-provisioned container
        if self.container_queue:
            pc = self.container_queue.consume_container(timeout=1.0)
            if pc:
                entry.id = pc.node_id
                entry.container_name = pc.container_name
                entry.container_backed = True
                logger.info(f"Node {entry.id} backed by container {pc.container_name}")
            else:
                logger.warning(f"No pre-provisioned container available, using fallback node")

        self._nodes[entry.id] = entry
        return entry

    def assign(self, node_id: str, session_id: str, user_id: str) -> NodeEntry:
        """
        Assign a specific node to a session.

        Raises:
            KeyError  – node_id not found
            ValueError – node is already assigned
        """
        entry = self._get_or_raise(node_id)
        if entry.status == "assigned":
            raise ValueError(
                f"Node {node_id} is already assigned to session {entry.assigned_session_id}"
            )
        entry.status = "assigned"
        entry.assigned_session_id = session_id
        return entry

    def assign_any(self, session_id: str, user_id: str) -> NodeEntry:
        """
        Assign the first available node to a session.

        Tries queue first (instant assignment), then falls back to
        existing available nodes.

        Raises:
            ValueError – no available nodes
        """
        # Try to get from queue first (pre-provisioned, faster)
        if self.container_queue:
            pc = self.container_queue.consume_container(timeout=0.5)
            if pc:
                entry = NodeEntry(id=pc.node_id, container_name=pc.container_name)
                entry.container_backed = True
                entry.status = "assigned"
                entry.assigned_session_id = session_id
                self._nodes[entry.id] = entry
                logger.info(f"Assigned queue container {entry.id} to session {session_id}")
                return entry

        # Fall back to existing available nodes
        available = self.list_available()
        if not available:
            raise ValueError("No available nodes")

        entry = available[0]
        entry.status = "assigned"
        entry.assigned_session_id = session_id
        return entry

    def release(self, node_id: str) -> NodeEntry:
        """Release a previously-assigned node so it becomes available again.

        If the node is container-backed, returns it to the queue for reuse.
        """
        entry = self._get_or_raise(node_id)
        entry.status = "available"
        entry.assigned_session_id = None

        # Return container to queue if backed by one
        if entry.container_backed and self.container_queue:
            self.container_queue.return_container(node_id)
            logger.info(f"Container {node_id} returned to queue")

        return entry

    # ── queries ───────────────────────────────────────────────────────────

    def get(self, node_id: str) -> Optional[NodeEntry]:
        return self._nodes.get(node_id)

    def list_all(self) -> List[NodeEntry]:
        return list(self._nodes.values())

    def list_available(self) -> List[NodeEntry]:
        return [n for n in self._nodes.values() if n.status == "available"]

    # ── helpers ───────────────────────────────────────────────────────────

    def _get_or_raise(self, node_id: str) -> NodeEntry:
        entry = self._nodes.get(node_id)
        if entry is None:
            raise KeyError(f"Node {node_id} not found in registry")
        return entry
