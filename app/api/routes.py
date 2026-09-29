from datetime import datetime, timedelta
import io
import logging
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
import pandas as pd
from app.ai.executive_insights import ExecutiveInsightsEngine
from app.connectors.smart_column_mapper import SmartColumnMapper
from app.reports.report_factory import ReportFactory

logger = logging.getLogger("metrika.api")
router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

# Memory storage for last uploaded dataset (per session/instance)
_LAST_UPLOADED_DF: Optional[pd.DataFrame] = None


def get_cached_or_default_dataframe() -> pd.DataFrame:
    """
    Returns the currently active uploaded dataset from memory.
    If not in memory, auto-loads the most recent persisted dataset (or glpi(3).xlsx).
    Ensures the dashboard always loads with complete operational data.
    """
    global _LAST_UPLOADED_DF
    if _LAST_UPLOADED_DF is not None and not _LAST_UPLOADED_DF.empty:
        return _LAST_UPLOADED_DF

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    candidates = [
        os.path.join(base_dir, "last_uploaded_dataset.xlsx"),
        os.path.join(base_dir, "glpi(3).xlsx"),
        os.path.join(base_dir, "glpi.xlsx"),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                logger.info(f"Auto-loading initial dataset from {c}")
                _LAST_UPLOADED_DF = pd.read_excel(c)
                return _LAST_UPLOADED_DF
            except Exception as e:
                logger.warning(f"Could not load candidate dataset {c}: {e}")

    return pd.DataFrame()


def filter_dataframe_by_days(df: pd.DataFrame, days: int, report_engine: Any = None) -> pd.DataFrame:
    """
    Filters uploaded dataframe by the last N days relative to the latest record date.
    If days <= 0 or days >= 999, returns all records (Tüm Veri).
    """
    if df is None or df.empty or days is None or days <= 0 or days >= 999:
        return df.copy() if df is not None else pd.DataFrame()

    try:
        mapped_df, _ = SmartColumnMapper.map_dataframe(df)
        date_series = None
        if "created_at" in mapped_df.columns:
            date_series = pd.to_datetime(mapped_df["created_at"], errors="coerce", dayfirst=True)

        if date_series is None or date_series.notna().sum() == 0:
            for col in df.columns:
                col_l = str(col).lower()
                if any(k in col_l for k in ["açılış", "acilis", "tarih", "date", "created"]):
                    date_series = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
                    if date_series.notna().sum() > 0:
                        break

        if date_series is not None and date_series.notna().sum() > 0:
            max_date = date_series.dropna().max()
            cutoff_date = max_date - pd.Timedelta(days=days)
            filtered_df = df[date_series >= cutoff_date].copy()
            logger.info(
                f"Filtered uploaded DF: {len(filtered_df)} / {len(df)} rows "
                f"(days={days}, cutoff={cutoff_date}, max_date={max_date})"
            )
            return filtered_df
    except Exception as e:
        logger.warning(f"Failed to filter dataframe by {days} days: {e}")

    return df.copy()


@router.get("/types")
async def get_report_types():
    """
    List registered report templates and data sources.
    """
    return {
        "reports": ReportFactory.list_reports(),
        "connectors": ReportFactory.list_connectors(),
    }


@router.get("/{report_type}/metrics")
async def get_report_metrics(
    report_type: str,
    days: int = Query(7, ge=0, le=3650, description="Filtrelenecek gün sayısı (0 = Tüm Veri)"),
    source: str = Query("upload", description="Veri kaynağı ('upload', 'glpi', 'mock')"),
    segment: str = Query("all", description="Operasyonel ekip segmenti ('all', 'service_desk', 'system_ops')"),
    include_llm: bool = Query(False, description="Qwen LLM detaylı özetini tetikle"),
):
    """
    Returns calculated operational metrics, SLA ratios, and technician matrices.
    Instant response (<10ms) using expert heuristic rules by default without freezing on Qwen.
    """
    global _LAST_UPLOADED_DF
    try:
        report_engine = ReportFactory.get_report(report_type)

        if source.lower() == "upload":
            active_df = get_cached_or_default_dataframe()
            if active_df is None or active_df.empty:
                raise HTTPException(status_code=400, detail="Henüz yüklenmiş bir Excel/CSV verisi bulunmuyor.")
            df = filter_dataframe_by_days(active_df, days, report_engine)
        elif source.lower() == "glpi":
            connector = ReportFactory.get_connector(source)
            effective_days = days if days > 0 else 365
            try:
                df = await connector.fetch_tickets(days=effective_days)
            except Exception as conn_err:
                logger.warning(f"GLPI connector error: {conn_err}. Seamlessly falling back to cached dataset.")
                active_df = get_cached_or_default_dataframe()
                if active_df is not None and not active_df.empty:
                    df = filter_dataframe_by_days(active_df, days, report_engine)
                else:
                    mock_conn = ReportFactory.get_connector("mock")
                    df = await mock_conn.fetch_tickets(days=effective_days)
        else:
            connector = ReportFactory.get_connector(source)
            effective_days = days if days > 0 else 365
            df = await connector.fetch_tickets(days=effective_days)

        if hasattr(report_engine, "calculate_metrics") and "segment" in report_engine.calculate_metrics.__code__.co_varnames:
            metrics = report_engine.calculate_metrics(df, segment=segment)
        else:
            metrics = report_engine.calculate_metrics(df)

        # Generate Executive Insights: Fast Heuristic by default for instant UI responsiveness
        ai_engine = ExecutiveInsightsEngine()
        if include_llm:
            insights = await ai_engine.generate_summary(metrics)
        else:
            insights = ai_engine.generate_heuristic_summary(metrics)
        metrics["executive_insights"] = insights
        metrics["meta"] = {
            "report_type": report_type,
            "source": source,
            "days": days,
            "segment": segment,
            "include_llm": include_llm,
            "generated_at": datetime.now().isoformat(),
        }

        return metrics
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing metrics for {report_type}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Metrik hesaplama hatası: {str(e)}")


@router.get("/{report_type}/ai-summary")
async def get_ai_summary(
    report_type: str,
    days: int = Query(7, ge=0, le=3650),
    source: str = Query("upload"),
    segment: str = Query("all"),
):
    """
    On-demand dedicated Qwen LLM summary generation.
    Returns detailed executive insights synthesized by Qwen 3.5 without blocking regular dashboard metrics.
    """
    try:
        report_engine = ReportFactory.get_report(report_type)
        if source.lower() == "upload":
            active_df = get_cached_or_default_dataframe()
            if active_df is None or active_df.empty:
                raise HTTPException(status_code=400, detail="Yüklü veri seti bulunamadı.")
            df = filter_dataframe_by_days(active_df, days, report_engine)
        else:
            connector = ReportFactory.get_connector(source)
            df = await connector.fetch_tickets(days=days if days > 0 else 365)

        if hasattr(report_engine, "calculate_metrics") and "segment" in report_engine.calculate_metrics.__code__.co_varnames:
            metrics = report_engine.calculate_metrics(df, segment=segment)
        else:
            metrics = report_engine.calculate_metrics(df)

        ai_engine = ExecutiveInsightsEngine()
        insights = await ai_engine.generate_summary(metrics)
        return {"executive_insights": insights}
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{report_type}/export-excel")
async def export_report_excel(
    report_type: str,
    days: int = Query(7, ge=0, le=3650, description="Filtrelenecek gün sayısı (0 = Tüm Veri)"),
    source: str = Query("upload", description="Veri kaynağı ('upload', 'glpi', 'mock')"),
    segment: str = Query("all", description="Operasyonel ekip segmenti ('all', 'service_desk', 'system_ops')"),
):
    """
    Streams a fully formatted corporate Navy/Slate styled Excel (.xlsx) file in memory.
    """
    global _LAST_UPLOADED_DF
    try:
        report_engine = ReportFactory.get_report(report_type)

        if source.lower() == "upload":
            active_df = get_cached_or_default_dataframe()
            if active_df is None or active_df.empty:
                raise HTTPException(status_code=400, detail="Henüz yüklenmiş bir Excel/CSV dosyası yok.")
            df = filter_dataframe_by_days(active_df, days, report_engine)
        elif source.lower() == "glpi":
            connector = ReportFactory.get_connector(source)
            effective_days = days if days > 0 else 365
            try:
                df = await connector.fetch_tickets(days=effective_days)
            except Exception:
                active_df = get_cached_or_default_dataframe()
                df = filter_dataframe_by_days(active_df, days, report_engine) if not active_df.empty else pd.DataFrame()
        else:
            connector = ReportFactory.get_connector(source)
            effective_days = days if days > 0 else 365
            df = await connector.fetch_tickets(days=effective_days)

        if hasattr(report_engine, "calculate_metrics") and "segment" in report_engine.calculate_metrics.__code__.co_varnames:
            metrics = report_engine.calculate_metrics(df, segment=segment)
        else:
            metrics = report_engine.calculate_metrics(df)

        excel_buffer = report_engine.render_excel(metrics, df)

        date_stamp = datetime.now().strftime("%Y%m%d_%H%M")
        period_str = "TumVeri" if days == 0 else f"{days}Gun"
        seg_str = f"_{segment}" if segment != "all" else ""
        filename = f"METRIKA_Belgenet_Servis_Masasi_Raporu_{period_str}{seg_str}_{date_stamp}.xlsx"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        }

        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Excel export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Excel üretim hatası: {str(e)}")


@router.post("/{report_type}/upload")
async def upload_dataset(
    report_type: str,
    file: UploadFile = File(..., description="Ham GLPI Excel (.xlsx, .xls) veya CSV dosyası"),
):
    """
    Upload a raw GLPI export file (Excel or CSV).
    Instantly parses the data, normalizes columns, calculates KPIs, and updates the dashboard.
    """
    global _LAST_UPLOADED_DF
    try:
        report_engine = ReportFactory.get_report(report_type)
        contents = await file.read()
        filename = file.filename or "upload"

        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(contents), encoding="latin1")
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Yalnızca .xlsx, .xls veya .csv formatı desteklenir.")

        if df.empty:
            raise HTTPException(status_code=400, detail="Yüklenen dosya boş veri içeriyor.")

        # Cache in memory and persist on disk for persistence across restarts
        _LAST_UPLOADED_DF = df
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            persist_path = os.path.join(base_dir, "last_uploaded_dataset.xlsx")
            df.to_excel(persist_path, index=False)
            logger.info(f"Persisted uploaded dataset to {persist_path}")
        except Exception as pe:
            logger.warning(f"Could not persist uploaded file to disk: {pe}")

        metrics = report_engine.calculate_metrics(df)
        ai_engine = ExecutiveInsightsEngine()
        metrics["executive_insights"] = ai_engine.generate_heuristic_summary(metrics)
        metrics["meta"] = {
            "report_type": report_type,
            "source": "upload",
            "filename": filename,
            "row_count": len(df),
            "generated_at": datetime.now().isoformat(),
        }

        diagnostics = metrics.get("column_diagnostics", {})
        matched_info = [
            f"Teknisyen: '{diagnostics.get('mapped_columns', {}).get('technician_raw', 'Atanmamış')}'",
            f"Kurum: '{diagnostics.get('mapped_columns', {}).get('institution', 'Belirtilmemiş')}'",
            f"İlk Yanıt: '{diagnostics.get('mapped_columns', {}).get('first_response_time_str', 'Bulunamadı')}'",
            f"Çözüm Süresi: '{diagnostics.get('mapped_columns', {}).get('total_resolution_time_str', 'Bulunamadı')}'",
        ]

        return {
            "message": f"'{filename}' başarıyla yüklendi ve {len(df)} kayıt akıllı sütun eşleyici ile işlendi.",
            "mapping_summary": " | ".join(matched_info),
            "diagnostics": diagnostics,
            "metrics": metrics,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dosya okuma ve işleme hatası: {str(e)}")


@router.post("/{report_type}/export-from-upload")
async def export_from_upload(
    report_type: str,
    file: UploadFile = File(..., description="Ham Excel veya CSV dosyası"),
):
    """
    One-click transform: Takes uploaded raw Excel/CSV and directly downloads
    the formatted corporate Navy/Slate Excel report.
    """
    try:
        report_engine = ReportFactory.get_report(report_type)
        contents = await file.read()
        filename = file.filename or "upload"

        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(contents), encoding="latin1")
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Yalnızca .xlsx veya .csv desteklenir.")

        metrics = report_engine.calculate_metrics(df)
        excel_buffer = report_engine.render_excel(metrics, df)

        date_stamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_filename = f"METRIKA_Kurumsal_Rapor_{date_stamp}.xlsx"

        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{out_filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload transform export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rapor dönüştürme hatası: {str(e)}")
