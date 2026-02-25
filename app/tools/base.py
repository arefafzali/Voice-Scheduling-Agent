from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class Tool(ABC):
    name: str

    @abstractmethod
    def execute(self, payload: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        raise NotImplementedError
