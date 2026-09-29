from typing import Any, Dict, List, Type
from app.connectors.base_connector import BaseConnector
from app.connectors.glpi_connector import GLPIConnector
from app.connectors.mock_connector import MockConnector
from app.reports.base_report import BaseReport
from app.reports.qa_test_report import QATestReport
from app.reports.service_desk_report import ServiceDeskReport


class ReportFactory:
    """
    Factory class providing registered report templates and data source connectors.
    Enables zero-touch plugin addition for future reports (OpenProject, Jira, SLA audit).
    """

    _REPORTS: Dict[str, Type[BaseReport]] = {
        "service_desk": ServiceDeskReport,
        "qa_testing": QATestReport,
    }

    _CONNECTORS: Dict[str, Type[BaseConnector]] = {
        "glpi": GLPIConnector,
        "mock": MockConnector,
    }

    @classmethod
    def get_report(cls, report_type: str = "service_desk") -> BaseReport:
        report_cls = cls._REPORTS.get(report_type.lower())
        if not report_cls:
            raise ValueError(f"Unknown report type: '{report_type}'. Available: {list(cls._REPORTS.keys())}")
        return report_cls()

    @classmethod
    def get_connector(cls, connector_type: str = "glpi") -> BaseConnector:
        conn_cls = cls._CONNECTORS.get(connector_type.lower())
        if not conn_cls:
            raise ValueError(f"Unknown connector type: '{connector_type}'. Available: {list(cls._CONNECTORS.keys())}")
        return conn_cls()

    @classmethod
    def list_reports(cls) -> List[Dict[str, str]]:
        return [
            {
                "key": "service_desk",
                "name": "Belgenet Servis Masası & Sistem Operasyon Raporu",
                "description": "L1 Servis Masası ve L2 Sistem ayrımı, MTTA, MTTR, Dış Bekleme ve SLA analizleri.",
            },
            {
                "key": "qa_testing",
                "name": "Belgenet Test & QA (Kalite Güvence) Raporu",
                "description": "Koşulan test senaryoları, doğrulama süreleri, hata tespit oranları ve test uzmanı karnesi.",
            },
            {
                "key": "biz_dev",
                "name": "İş Geliştirme & Proje Raporu (Gelecek)",
                "description": "Kurumsal iş geliştirme, proje teslim ve sürüm tamamlama metrikleri.",
            }
        ]

    @classmethod
    def list_connectors(cls) -> List[Dict[str, str]]:
        return [
            {"key": "glpi", "name": "GLPI REST API", "description": "Canlı GLPI oturumu ile veri çekimi."},
            {"key": "mock", "name": "Belgenet Simülasyon Verisi", "description": "Çevrimdışı test ve demo veri seti."},
        ]
