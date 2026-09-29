import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.ai.ad_hoc_analytics import AdHocAnalyticsEngine
from app.ai.executive_insights import ExecutiveInsightsEngine
from app.ai.qwen_client import QwenClient
from app.api.routes import filter_dataframe_by_days, get_cached_or_default_dataframe

logger = logging.getLogger("metrika.api.ai")

router = APIRouter(prefix="/api/v1/ai", tags=["AI & Qwen LLM"])


class AdHocQueryRequest(BaseModel):
    prompt: str = Field(..., description="Kullanıcının doğal dildeki analiz/istatistik veya grafik sorgusu")
    report_type: str = Field("service_desk", description="Rapor tipi")
    source: str = Field("upload", description="Veri kaynağı (upload veya glpi)")
    days: int = Field(0, description="Filtrelenecek gün sayısı (0 = tümü)")
    segment: str = Field("all", description="Ekip segmenti ('all', 'service_desk', 'system')")


class GenerateInsightsRequest(BaseModel):
    metrics: Dict[str, Any] = Field(..., description="Hesaplanmış operasyonel metrikler sözlüğü")


class ActionPlanRequest(BaseModel):
    metrics: Dict[str, Any] = Field(..., description="Hesaplanmış operasyonel metrikler sözlüğü")
    focus_area: Optional[str] = Field(None, description="Opsiyonel odak alanı (örn: 'mtta', 'fcr', 'external_wait')")


@router.get("/status")
async def get_ai_status():
    """
    TÜRKSAT PAAS Qwen LLM bağlantı ve sağlık durumunu test eder.
    (qwen35-122b-a10b-fp8)
    """
    client = QwenClient()
    return await client.check_health()


@router.post("/generate-actions")
async def generate_executive_actions(req: ActionPlanRequest):
    """
    Qwen LLM üzerinden operasyonel metrikler ve darboğazlar için
    önceliklendirilmiş (Acil/Kısa Vadeli ve Stratejik İyileştirme) aksiyon planı üretir.
    """
    client = QwenClient()
    plan = await client.generate_action_plan(metrics=req.metrics, focus_area=req.focus_area)
    if not plan:
        # Fallback to engine
        engine = ExecutiveInsightsEngine(client)
        summary = await engine.generate_summary(req.metrics)
        return {
            "source": summary.get("source"),
            "health_status": summary.get("health_status"),
            "health_color": summary.get("health_color"),
            "executive_summary": summary.get("executive_summary"),
            "immediate_actions": summary.get("immediate_actions", []),
            "strategic_actions": summary.get("strategic_actions", []),
            "alerts": summary.get("alerts", []),
            "recommendations": summary.get("recommendations", []),
        }
    return plan


@router.post("/generate-summary")
async def generate_executive_insights(req: GenerateInsightsRequest):
    """
    Verilen metrikler için Qwen LLM üzerinden yönetici özeti ve aksiyon önerileri üretir.
    """
    engine = ExecutiveInsightsEngine()
    insights = await engine.generate_summary(req.metrics)
    return insights


@router.post("/query")
async def execute_ad_hoc_query(req: AdHocQueryRequest):
    """
    Doğal dille yazılmış operasyonel soruları analiz eder,
    operasyonel kapsam dışıysa koruma kuralıyla (guardrail) reddeder,
    kapsam dahilindeyse Pandas ile sıfır-halüsinasyon kesin sayısal hesaplama yapar,
    Chart.js grafik konfigürasyonu, KPI kartları ve yönetici özeti döner.
    """
    engine = AdHocAnalyticsEngine()
    df = get_cached_or_default_dataframe()
    if df is None or df.empty:
        raise HTTPException(
            status_code=400,
            detail="Analiz yapılacak aktif veri kümesi bulunamadı. Lütfen bir veri dosyası yükleyiniz."
        )

    filtered_df = filter_dataframe_by_days(df, req.days)
    result = await engine.execute_query(
        prompt=req.prompt,
        df=filtered_df,
        days=req.days,
        segment=req.segment,
    )
    return result
