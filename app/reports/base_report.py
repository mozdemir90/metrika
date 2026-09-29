from abc import ABC, abstractmethod
import io
from typing import Any, Dict
import pandas as pd


class BaseReport(ABC):
    """
    Abstract Base Class for Report Generators.
    Implements Strategy Pattern allowing different report templates (Service Desk, OpenProject, etc.)
    to calculate custom metrics and render formatted outputs.
    """

    @abstractmethod
    def calculate_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Process the raw ticket/task DataFrame and calculate business KPIs.
        """
        pass

    @abstractmethod
    def render_excel(self, metrics: Dict[str, Any], df: pd.DataFrame) -> io.BytesIO:
        """
        Render a fully formatted, corporate Excel workbook in memory and return as BytesIO.
        """
        pass
