import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from src.ports.fleet import IFleetProvider
from src.config import settings


class JsonFleetAdapter(IFleetProvider):
    """
    Outbound adapter loading simulated compute node topology from static JSON fixtures.
    Fulfills the hardware agnosticism and 32-node cluster requirement.
    """

    def __init__(self, fixture_path: Optional[str] = None):
        self.fixture_path = Path(fixture_path or settings.FLEET_FIXTURE_PATH)
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.fixture_path.is_absolute():
            # Try relative to current working directory or file directory
            base_dir = Path(__file__).resolve().parents[3]
            candidate = base_dir / self.fixture_path
            if candidate.exists():
                path = candidate
            else:
                path = self.fixture_path
        else:
            path = self.fixture_path

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"cluster_name": "Academic AI Compute Fabric", "total_nodes": 0, "nodes": []}

    def get_cluster_summary(self) -> Dict[str, Any]:
        return {
            "cluster_name": self._data.get("cluster_name", "Academic AI Compute Fabric"),
            "total_nodes": len(self._data.get("nodes", [])),
            "healthy_nodes": sum(1 for n in self._data.get("nodes", []) if n.get("status") == "HEALTHY"),
            "total_vram_gb": sum(n.get("total_vram_gb", 0) for n in self._data.get("nodes", []))
        }

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        return self._data.get("nodes", [])

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        for node in self._data.get("nodes", []):
            if node.get("node_id") == node_id:
                return node
        return None
