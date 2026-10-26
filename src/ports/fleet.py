from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class IFleetProvider(ABC):
    """Abstract port for cluster fleet topology inspection."""

    @abstractmethod
    def get_cluster_summary(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_all_nodes(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        pass
