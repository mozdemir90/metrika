from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import pandas as pd


class BaseConnector(ABC):
    """
    Abstract Base Class for Data Source Connectors.
    Allows easy expansion to OpenProject, Jira, Direct SQL or GLPI.
    """

    @abstractmethod
    async def fetch_tickets(self, days: int = 7, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Fetch raw ticket data from the underlying source and return as pandas DataFrame.
        """
        pass

    @abstractmethod
    async def check_health(self) -> Dict[str, Any]:
        """
        Check health and connection status of the source.
        """
        pass
