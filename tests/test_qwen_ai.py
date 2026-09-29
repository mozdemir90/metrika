import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.ai.executive_insights import ExecutiveInsightsEngine
from app.ai.qwen_client import QwenClient
from app.main import app

client = TestClient(app)


def test_qwen_client_json_extractor():
    raw_markdown = """
    İşte analiz sonucu:
    ```json
    {
      "category": "Hata",
      "priority": "Yüksek",
      "confidence": 0.95
    }
    ```
    İyi çalışmalar dilerim.
    """
    extracted = QwenClient._extract_json(raw_markdown)
    assert extracted is not None
    assert '"category": "Hata"' in extracted

    raw_braces = 'Metin başı {"status": "ok", "value": 42} metin sonu'
    extracted_braces = QwenClient._extract_json(raw_braces)
    assert extracted_braces == '{"status": "ok", "value": 42}'


@pytest.mark.asyncio
async def test_qwen_executive_report_fallback():
    # Test when Qwen is disabled or fails, falls back gracefully to heuristic engine
    engine = ExecutiveInsightsEngine()
    dummy_metrics = {
        "summary": {
            "total_tickets": 100,
            "resolved_tickets": 60,
            "open_tickets": 40,
            "resolution_rate": 60.0,
            "fcr_rate": 20.0,
            "reopen_rate": 3.0,
            "avg_mtta_minutes": 25.0,
            "avg_net_mttr_hours": 12.0,
            "avg_external_wait_hours": 2.0,
        },
        "technicians": [],
        "top_institutions": [],
    }
    insights = await engine.generate_summary(dummy_metrics)
    assert "health_status" in insights
    assert "observations" in insights
    assert len(insights["observations"]) > 0
    assert "recommendations" in insights
    assert "immediate_actions" in insights
    assert "strategic_actions" in insights


def test_api_ai_status_endpoint():
    response = client.get("/api/v1/ai/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "model" in data
    assert data["model"] == "qwen35-122b-a10b-fp8"


def test_api_ai_generate_summary_endpoint():
    dummy_metrics = {
        "summary": {
            "total_tickets": 80,
            "resolved_tickets": 72,
            "open_tickets": 8,
            "resolution_rate": 90.0,
            "fcr_rate": 45.0,
            "reopen_rate": 2.5,
            "avg_mtta_minutes": 18.0,
            "avg_net_mttr_hours": 5.0,
            "avg_external_wait_hours": 3.5,
        },
        "technicians": [],
        "top_institutions": [],
    }
    response = client.post(
        "/api/v1/ai/generate-summary",
        json={"metrics": dummy_metrics}
    )
    assert response.status_code == 200
    data = response.json()
    assert "health_status" in data
    assert "executive_summary" in data
    assert "observations" in data
    assert "recommendations" in data


def test_api_ai_generate_actions_endpoint():
    dummy_metrics = {
        "summary": {
            "total_tickets": 80,
            "resolved_tickets": 72,
            "open_tickets": 8,
            "resolution_rate": 90.0,
            "fcr_rate": 45.0,
            "reopen_rate": 2.5,
            "avg_mtta_minutes": 18.0,
            "avg_net_mttr_hours": 5.0,
            "avg_external_wait_hours": 3.5,
        },
        "technicians": [],
        "top_institutions": [],
    }
    response = client.post(
        "/api/v1/ai/generate-actions",
        json={"metrics": dummy_metrics, "focus_area": "fcr"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "immediate_actions" in data
    assert "strategic_actions" in data
    assert len(data["immediate_actions"]) > 0


def test_ad_hoc_guardrail():
    from app.ai.ad_hoc_analytics import AdHocAnalyticsEngine
    engine = AdHocAnalyticsEngine()

    # Valid operational queries
    assert engine.is_operational_query("Cumhurbaşkanlığı'nın sistem sepetindeki çağrıları kaç tane?") is True
    assert engine.is_operational_query("En çok hata açan ilk 5 kurum ve sepet dağılımı") is True
    assert engine.is_operational_query("Öneri ve ek geliştirme talepleri hangi sepetlere gidiyor?") is True
    assert engine.is_operational_query("Servis masası ve sistem ekibi çağrı sayısı") is True

    # Invalid off-topic queries
    assert engine.is_operational_query("Bugün Ankara'da hava durumu nasıl?") is False
    assert engine.is_operational_query("Bana lezzetli bir kek tarifi ver") is False
    assert engine.is_operational_query("Futbol maçını kim kazandı?") is False
    assert engine.is_operational_query("ab") is False


def test_api_ai_query_endpoint():
    # Ensure canonical dataset is loaded for the test
    import app.api.routes as routes
    routes._LAST_UPLOADED_DF = None

    # 1. Non-operational query test
    off_topic_resp = client.post(
        "/api/v1/ai/query",
        json={"prompt": "Bugün hava durumu nasıl?"}
    )
    assert off_topic_resp.status_code == 200
    off_topic_data = off_topic_resp.json()
    assert off_topic_data["is_applicable"] is False
    assert "Kapsam Dışı Soru" in off_topic_data["answer_text"]
    assert off_topic_data["chart"]["has_chart"] is False

    # 2. Operational query test (with cached/default glpi(3).xlsx)
    op_resp = client.post(
        "/api/v1/ai/query",
        json={"prompt": "Hata ve arıza taleplerinin sepet dağılımı nedir?"}
    )
    assert op_resp.status_code == 200
    op_data = op_resp.json()
    assert op_data["is_applicable"] is True
    assert op_data["matched_count"] > 0
    assert op_data["chart"]["has_chart"] is True
    assert len(op_data["summary_cards"]) >= 2
    assert op_data["table"]["has_table"] is True


