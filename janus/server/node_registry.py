"""In-memory registry that tracks nodes and their assignments."""

from __future__ import annotations
import uuid
from typing import Dict, Optional, List


class NodeEntry:
    """Internal record for a registered node."""

    def __init__(self, id: str | None = None):
        self.id = id or str(uuid.uuid4())
        self.status: str = "available"          # available | assigned
        self.assigned_session_id: Optional[str] = None
        self.model_id: Optional[str] = None     # uploaded model reference

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "assigned_session_id": self.assigned_session_id,
            "model_id": self.model_id,
        }


class NodeRegistry:
    """
    Simple in-memory store of compute nodes.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeEntry] = {}

    # ── mutators ──────────────────────────────────────────────────────────

    def register(self, id: str | None = None) -> NodeEntry:
        """Register a new node (or re-register an existing one)."""
        entry = NodeEntry(id=id)
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

        Raises:
            ValueError – no available nodes
        """
        available = self.list_available()
        if not available:
            raise ValueError("No available nodes")
        entry = available[0]
        entry.status = "assigned"
        entry.assigned_session_id = session_id
        return entry

    def release(self, node_id: str) -> NodeEntry:
        """Release a previously-assigned node so it becomes available again."""
        entry = self._get_or_raise(node_id)
        entry.status = "available"
        entry.assigned_session_id = None
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
