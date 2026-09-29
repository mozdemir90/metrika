import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter, column_index_from_string
import pandas as pd
from app.connectors.smart_column_mapper import SmartColumnMapper
from app.reports.base_report import BaseReport


class ServiceDeskReport(BaseReport):
    """
    Belgenet GLPI Service Desk & Systems Operations Performance & SLA Report Engine.
    Supports multi-team segmentation (Service Desk L1 / BNSM vs System Ops L2 / BN),
    calculates operational KPIs with clear terminology, and renders a 5-sheet
    corporate Navy/Slate styled Excel workbook.
    """

    COLOR_NAVY_DARK = "0F172A"       # Primary Title & Header Fill
    COLOR_NAVY_LIGHT = "1E3A8A"      # Subheader Fill
    COLOR_SLATE_HEADER = "334155"    # Table Header
    COLOR_SLATE_BG = "F8FAFC"        # Zebra row light
    COLOR_BORDER = "CBD5E1"          # Border gray
    COLOR_KPI_BG = "F1F5F9"          # KPI Card background
    COLOR_WHITE = "FFFFFF"

    # Status Colors
    COLOR_SUCCESS_BG = "D1FAE5"      # Green light
    COLOR_SUCCESS_TEXT = "065F46"    # Green dark
    COLOR_WARN_BG = "FEF3C7"         # Amber light
    COLOR_WARN_TEXT = "92400E"       # Amber dark
    COLOR_DANGER_BG = "FEE2E2"       # Red light
    COLOR_DANGER_TEXT = "991B1B"     # Red dark

    RESOLVED_STATUS_KEYWORDS = [
        "çözüldü", "cozuldu", "çözülmüş", "cozulmus",
        "kapandı", "kapandi", "kapalı", "kapali",
        "kapatıldı", "kapatildi", "closed", "solved"
    ]

    @staticmethod
    def split_technician_names(raw_name: Any) -> List[str]:
        """
        Splits GLPI technician strings that contain multiple assignees (e.g. separated by newlines,
        carriage returns, commas or semicolons) and cleans 'glpi' prefixes and extra spaces.
        """
        if raw_name is None or pd.isna(raw_name):
            return ["Atanmamış"]

        text = str(raw_name).strip()
        if not text or text.lower() in ("nan", "none", "null", "", "-"):
            return ["Atanmamış"]

        parts = re.split(r"[\r\n,;]+", text)
        cleaned = []
        for p in parts:
            p = re.sub(r"^glpi\s*", "", p, flags=re.IGNORECASE).strip()
            p = re.sub(r"\s{2,}", " ", p).strip()
            if p and p.lower() not in ("nan", "none", "null", "", "-"):
                cleaned.append(p)
        return cleaned if cleaned else ["Atanmamış"]

    @staticmethod
    def normalize_technician_name(raw_name: Any) -> str:
        """
        Cleans GLPI dirty technician names and joins multiple assignees with comma:
        'glpi \\nBurak Çıkrık\\nHasan Karakaşoğlu' -> 'Burak Çıkrık, Hasan Karakaşoğlu'.
        """
        names = ServiceDeskReport.split_technician_names(raw_name)
        return ", ".join(names)

    @classmethod
    def parse_duration_to_minutes(cls, val: Any) -> float:
        """
        Parses duration strings like '1 gün 4 saat 30 dakika 15 saniye' into total minutes.
        """
        if val is None or pd.isna(val):
            return 0.0

        if isinstance(val, (int, float)):
            return float(val)

        text = str(val).strip().lower()
        if not text or text in ("0", "0.0", "-", "yok", "0 saniye"):
            return 0.0

        total_minutes = 0.0

        # Day match
        days_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:gün|gun|days?|d)\b", text)
        if days_match:
            total_minutes += float(days_match.group(1).replace(",", ".")) * 1440.0

        # Hour match
        hours_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:saat|hours?|h|hr|hrs)\b", text)
        if hours_match:
            total_minutes += float(hours_match.group(1).replace(",", ".")) * 60.0

        # Minute match
        mins_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:dakika|dk|mins?|m)\b", text)
        if mins_match:
            total_minutes += float(mins_match.group(1).replace(",", "."))

        # Second match
        secs_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:saniye|sn|seconds?|s)\b", text)
        if secs_match:
            total_minutes += float(secs_match.group(1).replace(",", ".")) / 60.0

        # Fallback if no unit found but has numeric
        if total_minutes == 0.0:
            num_match = re.search(r"^(\d+(?:[.,]\d+)?)$", text)
            if num_match:
                total_minutes = float(num_match.group(1).replace(",", "."))

        return round(total_minutes, 2)

    @classmethod
    def parse_duration_to_hours(cls, val: Any) -> float:
        """
        Parses duration strings into total hours.
        """
        minutes = cls.parse_duration_to_minutes(val)
        return round(minutes / 60.0, 2)

    def standardize_dataframe(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Applies SmartColumnMapper, classifies tickets into team segments
        (Servis Masası BNSM vs Sistem BN), and enriches records with SLA metrics.
        """
        mapped_df, diagnostics = SmartColumnMapper.map_dataframe(df)
        work_df = mapped_df.copy()

        # 1. Clean Ticket ID
        work_df["ticket_id"] = work_df["ticket_id"].astype(str).str.replace(" ", "").str.strip()

        # 2. Normalize Technician Names & Multi-Assignee List
        work_df["technician_list"] = work_df["technician_raw"].apply(self.split_technician_names)
        work_df["technician"] = work_df["technician_list"].apply(lambda names: ", ".join(names))

        # 3. Clean Institution
        work_df["institution"] = work_df["institution"].astype(str).str.strip()

        # 4. Parse Durations
        work_df["first_response_minutes"] = work_df["first_response_time_str"].apply(self.parse_duration_to_minutes)
        work_df["total_resolution_hours"] = work_df["total_resolution_time_str"].apply(self.parse_duration_to_hours)
        work_df["external_wait_hours"] = work_df["external_wait_time_str"].apply(self.parse_duration_to_hours)

        # Fallback for total_resolution_hours:
        # If total_resolution_hours is completely 0 across the dataset (e.g. GLPI exports where SLA delay fields are unconfigured),
        # but created_at and resolved_at timestamps exist, compute (resolved_at - created_at) in hours for resolved tickets.
        if work_df["total_resolution_hours"].sum() == 0.0 and "created_at" in work_df.columns and "resolved_at" in work_df.columns:
            try:
                c_dt = pd.to_datetime(work_df["created_at"], dayfirst=True, errors="coerce")
                r_dt = pd.to_datetime(work_df["resolved_at"], dayfirst=True, errors="coerce")
                diff_h = (r_dt - c_dt).dt.total_seconds() / 3600.0
                is_res = work_df["status"].astype(str).str.lower().apply(
                    lambda s: any(k in s for k in self.RESOLVED_STATUS_KEYWORDS)
                )
                valid_mask = is_res & diff_h.notna() & (diff_h >= 0)
                work_df.loc[valid_mask, "total_resolution_hours"] = diff_h[valid_mask].round(2)
            except Exception:
                pass

        # 5. Net Working Duration (Net Efor = Total - External Waiting)
        work_df["net_resolution_hours"] = (work_df["total_resolution_hours"] - work_df["external_wait_hours"]).clip(lower=0.0)


        # 6. Team Segmentation: Servis Masası (BNSM) vs Sistem Ekibi (BN)
        def classify_team_segment(row: pd.Series) -> str:
            raw_id = str(row.get("ticket_id", "")).upper()
            gorev_tipi = (str(row.get("op_task_type", "")) or str(row.get("openproject_task_id", ""))).lower()
            cat = str(row.get("category", "")).lower()
            title = str(row.get("title", "")).lower()

            # Rule 1: Semantic ID explicit check (BN- vs BNSM-)
            if "BN-" in raw_id and "BNSM" not in raw_id:
                return "Sistem"

            # Rule 2: Görev Tipi / Task Type check (Veritabanı, Deploy, Altyapı, Sistem)
            if any(w in gorev_tipi for w in ("veritabani", "veritabanı", "deploy", "ugd", "altyapi", "altyapı", "sistem", "sunucu")):
                return "Sistem"

            # Rule 3: Category check
            if any(w in cat for w in ("sistem", "veritabani", "veritabanı", "deploy", "sunucu", "altyapı")):
                return "Sistem"

            # Default to Servis Masası (L1)
            return "Servis Masası"

        work_df["team_segment"] = work_df.apply(classify_team_segment, axis=1)

        # 7. OpenProject Fields & Root Cause Normalization (Hata, Destek, Öneri)
        for op_col in ["op_request_type", "op_task_type", "op_basket"]:
            if op_col in work_df.columns:
                work_df[op_col] = work_df[op_col].fillna("").astype(str).str.strip().replace({"nan": "", "None": ""})
            else:
                work_df[op_col] = ""

        has_op_task_id = (
            work_df["openproject_task_id"].astype(str).str.strip().replace({"nan": "", "None": ""}) != ""
            if "openproject_task_id" in work_df.columns
            else pd.Series(False, index=work_df.index)
        )
        work_df["is_op_forwarded"] = (
            (work_df["op_request_type"] != "") |
            (work_df["op_task_type"] != "") |
            (work_df["op_basket"] != "") |
            has_op_task_id
        )

        def clean_root_cause(row: pd.Series) -> str:
            rc = str(row.get("root_cause", "")).lower().strip()
            op_req = str(row.get("op_request_type", "")).lower().strip()
            op_task = str(row.get("op_task_type", "")).lower().strip()
            combined = f"{rc} {op_req} {op_task}".strip()

            if any(w in combined for w in ("ek hizmet", "ek gelistirme", "ek geliştirme", "oneri", "öneri", "feature")):
                if any(w in op_req for w in ("ek hizmet", "ek gelistirme", "ek geliştirme")) or "oneri" in op_task or "öneri" in op_task:
                    return "Öneri"
                if not any(w in rc for w in ("hata", "bug", "ariza", "arıza")):
                    return "Öneri"
            if any(w in combined for w in ("hata", "bug", "ariza", "arıza", "kesinti", "bozukluk", "problem")):
                return "Hata"
            if any(w in combined for w in ("oneri", "öneri", "iyilestirme", "iyileştirme")):
                return "Öneri"
            return "Destek"

        work_df["root_cause"] = work_df.apply(clean_root_cause, axis=1)

        # 8. Status Classification (Resolved vs In Progress)
        work_df["status_clean"] = work_df["status"].astype(str).str.lower().str.strip()
        work_df["is_resolved"] = work_df["status_clean"].apply(
            lambda s: any(res_kw in s for res_kw in self.RESOLVED_STATUS_KEYWORDS)
        )

        # 9. SLA Evaluations
        # İlk Ele Alınma SLA (MTTA): Yüksek/Çok Yüksek <= 30 dk, Diğerleri <= 60 dk
        def check_mtta_sla(row: pd.Series) -> bool:
            p = str(row.get("priority", "")).lower()
            mins = float(row.get("first_response_minutes", 0.0))
            if any(w in p for w in ("yüksek", "yuksek", "critical", "acil", "5", "4")):
                return mins <= 30.0
            return mins <= 60.0

        # Net Çözüm SLA (MTTR): Yüksek <= 24h, Orta <= 48h, Düşük <= 72h
        def check_mttr_sla(row: pd.Series) -> bool:
            p = str(row.get("priority", "")).lower()
            net_h = float(row.get("net_resolution_hours", 0.0))
            if "çok yüksek" in p or "cok yuksek" in p or "5" in p:
                return net_h <= 12.0
            if "yüksek" in p or "yuksek" in p or "critical" in p or "4" in p:
                return net_h <= 24.0
            if "orta" in p or "3" in p:
                return net_h <= 48.0
            return net_h <= 72.0

        work_df["mtta_sla_compliant"] = work_df.apply(check_mtta_sla, axis=1)
        work_df["mttr_sla_compliant"] = work_df.apply(check_mttr_sla, axis=1)

        # 10. FCR (İlk Temasta Çözüm)
        # Resolved at service desk without escalation to OpenProject
        has_explicit_fcr = "is_fcr" in diagnostics.get("mapped_columns", {})

        def check_fcr(row: pd.Series) -> bool:
            if not row["is_resolved"]:
                return False
            # Check explicit column if present in the raw data
            if has_explicit_fcr:
                val = str(row.get("is_fcr", "")).lower().strip()
                if val in ("false", "0", "hayır", "hayir", "no"):
                    return False
                if val in ("true", "1", "evet", "yes"):
                    return True

            # Fallback to OpenProject escalation check
            op_val = str(row.get("op_task_type", "")).strip() or str(row.get("openproject_task_id", "")).strip()
            if op_val and op_val.lower() not in ("nan", "none", "null", "", "-"):
                return False
            return True

        work_df["is_fcr"] = work_df.apply(check_fcr, axis=1)

        # 11. Reopened Quality Metric
        def check_reopened(val: Any) -> bool:
            s = str(val).lower().strip()
            if s in ("true", "1", "evet", "yes", "yeniden açıldı", "yeniden acildi", "reopened"):
                return True
            return "yeniden" in s

        work_df["is_reopened"] = work_df["is_reopened"].apply(check_reopened)

        return work_df, diagnostics

    def calculate_metrics(self, df: pd.DataFrame, segment: str = "all") -> Dict[str, Any]:
        """
        Calculates operational metrics across all tickets and for specific segments
        ('all', 'service_desk', 'system_ops').
        """
        if df.empty:
            return self._empty_metrics()

        df, diagnostics = self.standardize_dataframe(df)

        # Compute metrics for each segment
        seg_all = self._compute_subset_metrics(df)

        # 1. L1 Servis Masası (All incoming tickets arrive at L1 first - 104 tickets)
        df_sd = df
        seg_sd = self._compute_subset_metrics(df_sd)

        # 2. L2 Sistem Ekibi (Escalated from L1 to Sistem & VT / Deploy - 32 tickets)
        is_l2_mask = df["team_segment"] == "Sistem"
        df_sys = df[is_l2_mask]
        seg_sys = self._compute_subset_metrics(df_sys)

        # Detect actual OpenProject task / basket escalation
        has_task_cols = (
            ("op_task_type" in df.columns and (df["op_task_type"] != "").any()) or
            ("op_basket" in df.columns and (df["op_basket"] != "").any()) or
            ("openproject_task_id" in df.columns and (df["openproject_task_id"].astype(str).str.strip().replace({"nan": "", "None": ""}) != "").any())
        )
        if has_task_cols:
            has_op_task = (
                (df.get("op_task_type", pd.Series("", index=df.index)) != "") |
                (df.get("op_basket", pd.Series("", index=df.index)) != "") |
                (df.get("openproject_task_id", pd.Series("", index=df.index)).astype(str).str.strip().replace({"nan": "", "None": ""}) != "")
            )
        else:
            has_op_task = df.get("is_op_forwarded", pd.Series(False, index=df.index))

        # 3. L3 Ekipleri & İş Geliştirme (Escalated from L1 to OpenProject non-L2)
        is_op_non_l2 = has_op_task & (~is_l2_mask)
        # Öneri (İş Geliştirme) ayrımı
        is_biz_dev_mask = is_op_non_l2 & (
            (df["root_cause"] == "Öneri") |
            (df.get("op_task_type", pd.Series("", index=df.index)).astype(str).str.contains("Öneri|Oneri|oneri|Geliştirme|Gelistirme", case=False, na=False)) |
            (df.get("op_basket", pd.Series("", index=df.index)).astype(str).str.contains("İyileştirme|İyilestirme|Iyilestirme|Geliştirme", case=False, na=False))
        )
        is_l3_mask = is_op_non_l2 & (~is_biz_dev_mask)
        df_l3 = df[is_l3_mask]
        df_biz_dev = df[is_biz_dev_mask]

        # 4. L1 Doğrudan Çözülen / Kapanan (OpenProject görevi açılmadan L1'de kalanlar)
        is_l1_direct_mask = ~has_op_task
        df_l1_direct = df[is_l1_direct_mask]
        l1_direct_resolved = int((is_l1_direct_mask & df["is_resolved"]).sum())
        l1_direct_total = int(is_l1_direct_mask.sum())
        l1_direct_open = l1_direct_total - l1_direct_resolved

        # Select primary view based on segment argument
        if segment == "service_desk":
            primary = seg_sd
        elif segment == "system_ops":
            primary = seg_sys
        else:
            primary = seg_all

        return {
            "active_segment": segment,
            "summary": primary["summary"],
            "priorities": primary["priorities"],
            "technicians": primary["technicians"],
            "top_institutions": primary["top_institutions"],
            "all_institutions": primary.get("all_institutions", primary["top_institutions"]),
            "openproject_summary": primary.get("openproject_summary", {}),
            "daily_trends": primary["daily_trends"],
            "column_diagnostics": diagnostics,
            "segments": {
                "all": seg_all["summary"],
                "service_desk": seg_sd["summary"],
                "system_ops": seg_sys["summary"],
            },
            "team_breakdown": {
                "total_tickets": len(df),
                "service_desk_count": len(df_sd),
                "service_desk_resolved": int(df_sd["is_resolved"].sum()),
                "system_ops_count": len(df_sys),
                "system_ops_resolved": int(df_sys["is_resolved"].sum()),
                "l3_forwarded_count": len(df_l3),
                "l3_forwarded_resolved": int(df_l3["is_resolved"].sum()),
                "business_dev_count": len(df_biz_dev),
                "business_dev_resolved": int(df_biz_dev["is_resolved"].sum()),
                "l1_direct_count": l1_direct_resolved,
                "l1_direct_resolved": l1_direct_resolved,
                "l1_unforwarded_total": l1_direct_total,
            },
            "escalation_summary": {
                "total_incoming": len(df),
                "l1_direct": {
                    "count": l1_direct_resolved,
                    "resolved": l1_direct_resolved,
                    "total_unforwarded": l1_direct_total,
                    "open": l1_direct_open,
                    "rate": round((l1_direct_resolved / len(df)) * 100, 1) if len(df) > 0 else 0.0,
                    "resolution_rate": round((l1_direct_resolved / l1_direct_total) * 100, 1) if l1_direct_total > 0 else 0.0,
                },
                "l2_transfers": {
                    "count": len(df_sys),
                    "resolved": int(df_sys["is_resolved"].sum()),
                    "rate": round((len(df_sys) / len(df)) * 100, 1) if len(df) > 0 else 0.0,
                    "task_types": df_sys["op_task_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_sys.empty else {},
                    "baskets": df_sys["op_basket"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_sys.empty else {},
                },
                "l3_transfers": {
                    "count": len(df_l3),
                    "resolved": int(df_l3["is_resolved"].sum()),
                    "rate": round((len(df_l3) / len(df)) * 100, 1) if len(df) > 0 else 0.0,
                    "task_types": df_l3["op_task_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_l3.empty else {},
                    "baskets": df_l3["op_basket"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_l3.empty else {},
                },
                "business_dev_transfers": {
                    "count": len(df_biz_dev),
                    "resolved": int(df_biz_dev["is_resolved"].sum()),
                    "rate": round((len(df_biz_dev) / len(df)) * 100, 1) if len(df) > 0 else 0.0,
                    "task_types": df_biz_dev["op_task_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_biz_dev.empty else {},
                    "baskets": df_biz_dev["op_basket"].replace("", "Belirtilmemiş").value_counts().to_dict() if not df_biz_dev.empty else {},
                }
            }
        }

    def _compute_subset_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Helper that calculates KPIs for any subset of the DataFrame.
        """
        if df.empty:
            return self._empty_metrics()

        total_tickets = len(df)
        resolved_mask = df["is_resolved"]
        resolved_tickets = int(resolved_mask.sum())
        open_tickets = total_tickets - resolved_tickets

        # MTTA metrics
        avg_mtta_mins = round(float(df["first_response_minutes"].mean()), 1)
        mtta_sla_compliant_count = int(df["mtta_sla_compliant"].sum())
        mtta_sla_rate = round((mtta_sla_compliant_count / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

        # MTTR metrics (calculated on resolved tickets)
        eval_df = df[resolved_mask] if resolved_tickets > 0 else df
        avg_total_mttr_hours = round(float(eval_df["total_resolution_hours"].mean()), 1)
        avg_external_wait_hours = round(float(eval_df["external_wait_hours"].mean()), 1)
        avg_net_mttr_hours = round(float(eval_df["net_resolution_hours"].mean()), 1)
        mttr_sla_compliant_count = int(eval_df["mttr_sla_compliant"].sum())
        mttr_sla_rate = round((mttr_sla_compliant_count / len(eval_df)) * 100, 1) if len(eval_df) > 0 else 0.0

        # Overall SLA (40% MTTA, 60% MTTR)
        overall_sla_rate = round((mtta_sla_rate * 0.4) + (mttr_sla_rate * 0.6), 1)

        # FCR
        fcr_count = int(df["is_fcr"].sum())
        fcr_rate = round((fcr_count / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

        # Reopen
        reopen_count = int(df["is_reopened"].sum())
        reopen_rate = round((reopen_count / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

        # Root Cause (Hata, Destek, Öneri)
        root_cause_counts = df["root_cause"].value_counts().to_dict()
        bug_count = int(root_cause_counts.get("Hata", 0))
        support_count = int(root_cause_counts.get("Destek", 0))
        suggestion_count = int(root_cause_counts.get("Öneri", 0))

        # OpenProject Forwarding Global Breakdown
        has_op_mask = df["is_op_forwarded"] if "is_op_forwarded" in df.columns else pd.Series(False, index=df.index)
        op_df = df[has_op_mask]
        op_forwarded_total = int(len(op_df))
        op_baskets = op_df["op_basket"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_df.empty else {}
        op_tasks = op_df["op_task_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_df.empty else {}
        op_demands = op_df["op_request_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_df.empty else {}

        # Priorities
        priority_data: List[Dict[str, Any]] = []
        for p in ["Çok Yüksek", "Yüksek", "Orta", "Düşük"]:
            sub = df[df["priority"].astype(str).str.contains(p, case=False, na=False)]
            if not sub.empty:
                priority_data.append(
                    {
                        "priority": p,
                        "count": len(sub),
                        "resolved_count": int(sub["is_resolved"].sum()),
                        "resolution_rate": round((sub["is_resolved"].sum() / len(sub)) * 100, 1),
                        "avg_mtta_minutes": round(float(sub["first_response_minutes"].mean()), 1),
                        "avg_net_hours": round(float(sub["net_resolution_hours"].mean()), 1),
                        "avg_external_wait_hours": round(float(sub["external_wait_hours"].mean()), 1),
                        "mtta_sla_rate": round(float(sub["mtta_sla_compliant"].mean() * 100), 1),
                        "mttr_sla_rate": round(float(sub["mttr_sla_compliant"].mean() * 100), 1),
                        "reopen_count": int(sub["is_reopened"].sum()) if "is_reopened" in sub.columns else 0,
                    }
                )

        # Technicians (Individual evaluation by exploding multi-assignees)
        if "technician_list" in df.columns:
            exploded_tech = df.explode("technician_list").copy()
            exploded_tech["technician_indiv"] = exploded_tech["technician_list"].fillna("Atanmamış").astype(str).str.strip()
            exploded_tech = exploded_tech[exploded_tech["technician_indiv"] != ""]
        else:
            exploded_tech = df.copy()
            exploded_tech["technician_indiv"] = exploded_tech["technician"]

        tech_grouped = exploded_tech.groupby("technician_indiv")
        tech_matrix: List[Dict[str, Any]] = []
        for tech_name, group in tech_grouped:
            dominant_team = group["team_segment"].mode().iloc[0] if "team_segment" in group.columns and not group["team_segment"].empty else "Servis Masası"
            t_total = len(group)
            t_resolved = int(group["is_resolved"].sum())
            t_mtta_sla = round(float(group["mtta_sla_compliant"].mean() * 100), 1)
            t_mttr_sla = round(float(group["mttr_sla_compliant"].mean() * 100), 1)
            t_avg_mtta = round(float(group["first_response_minutes"].mean()), 1)
            res_group = group[group["is_resolved"]]
            t_avg_net_h = round(float(res_group["net_resolution_hours"].mean()), 1) if not res_group.empty else 0.0
            t_avg_ext_wait = round(float(res_group["external_wait_hours"].mean()), 1) if not res_group.empty else 0.0
            t_reopen = int(group["is_reopened"].sum())
            t_reopen_rate = round((t_reopen / t_total) * 100, 1) if t_total > 0 else 0.0
            tech_matrix.append(
                {
                    "technician": tech_name,
                    "team": dominant_team,
                    "assigned_count": t_total,
                    "resolved_count": t_resolved,
                    "resolution_rate": round((t_resolved / t_total) * 100, 1) if t_total > 0 else 0.0,
                    "avg_first_response_minutes": t_avg_mtta,
                    "avg_net_resolution_hours": t_avg_net_h,
                    "avg_external_wait_hours": t_avg_ext_wait,
                    "mtta_sla_rate": t_mtta_sla,
                    "mttr_sla_rate": t_mttr_sla,
                    "reopen_count": t_reopen,
                    "reopen_rate": t_reopen_rate,
                }
            )
        tech_matrix.sort(key=lambda x: x["assigned_count"], reverse=True)

        # All & Top Institutions (with Deep OpenProject & 3-way Type Breakdown)
        all_inst_names = df["institution"].value_counts().index.tolist()
        institution_stats: List[Dict[str, Any]] = []
        for inst in all_inst_names:
            sub_inst = df[df["institution"] == inst]
            inst_total = len(sub_inst)
            inst_bugs = int((sub_inst["root_cause"] == "Hata").sum())
            inst_suggestions = int((sub_inst["root_cause"] == "Öneri").sum())
            inst_support = inst_total - inst_bugs - inst_suggestions

            # OpenProject subset for this institution
            op_sub = sub_inst[sub_inst["is_op_forwarded"]] if "is_op_forwarded" in sub_inst.columns else pd.DataFrame()
            inst_op_forwarded = len(op_sub)

            raw_demands = op_sub["op_request_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_sub.empty else {}
            canonical_demands = op_sub["root_cause"].value_counts().to_dict() if not op_sub.empty else {}
            task_types = op_sub["op_task_type"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_sub.empty else {}
            baskets = op_sub["op_basket"].replace("", "Belirtilmemiş").value_counts().to_dict() if not op_sub.empty else {}

            # Cross matrix: demand_type -> task_type -> basket
            cross_matrix: List[Dict[str, Any]] = []
            if not op_sub.empty:
                cross_grouped = op_sub.groupby(["op_request_type", "root_cause", "op_task_type", "op_basket"]).size().reset_index(name="count")
                for _, crow in cross_grouped.iterrows():
                    cross_matrix.append(
                        {
                            "demand_type": crow["op_request_type"] or "Belirtilmemiş",
                            "canonical_type": crow["root_cause"],
                            "task_type": crow["op_task_type"] or "Belirtilmemiş",
                            "basket": crow["op_basket"] or "Belirtilmemiş",
                            "count": int(crow["count"]),
                        }
                    )
                cross_matrix.sort(key=lambda x: x["count"], reverse=True)

            # Ticket preview for drill-down modal (first 100 tickets of this institution)
            tickets_preview: List[Dict[str, Any]] = []
            for _, trow in sub_inst.head(100).iterrows():
                tickets_preview.append(
                    {
                        "ticket_id": str(trow.get("ticket_id", "")),
                        "title": str(trow.get("title", "")),
                        "status": str(trow.get("status", "")),
                        "technician": str(trow.get("technician", "")),
                        "root_cause": str(trow.get("root_cause", "")),
                        "op_request_type": str(trow.get("op_request_type", "")),
                        "op_task_type": str(trow.get("op_task_type", "")),
                        "op_basket": str(trow.get("op_basket", "")),
                        "is_op_forwarded": bool(trow.get("is_op_forwarded", False)),
                    }
                )

            institution_stats.append(
                {
                    "institution": inst,
                    "total_count": inst_total,
                    "bug_count": inst_bugs,
                    "support_count": inst_support,
                    "suggestion_count": inst_suggestions,
                    "bug_percentage": round((inst_bugs / inst_total) * 100, 1) if inst_total > 0 else 0.0,
                    "op_forwarded_count": inst_op_forwarded,
                    "openproject_summary": {
                        "forwarded_count": inst_op_forwarded,
                        "local_count": inst_total - inst_op_forwarded,
                        "demand_types": canonical_demands,
                        "raw_demand_types": raw_demands,
                        "task_types": task_types,
                        "baskets": baskets,
                        "cross_matrix": cross_matrix,
                    },
                    "tickets_preview": tickets_preview,
                }
            )

        # Trends
        daily_trends: List[Dict[str, Any]] = []
        try:
            work_sub = df.copy()
            work_sub["date_parsed"] = pd.to_datetime(work_sub["created_at"], errors="coerce", format="mixed")
            valid_dates = work_sub.dropna(subset=["date_parsed"]).copy()
            if not valid_dates.empty:
                valid_dates["date_only"] = valid_dates["date_parsed"].dt.strftime("%Y-%m-%d")
                grouped_days = valid_dates.groupby("date_only")
                for day, g in sorted(grouped_days):
                    dmy_str = g["date_parsed"].iloc[0].strftime("%d-%m-%Y")
                    daily_trends.append(
                        {
                            "date": dmy_str,
                            "raw_date": day,
                            "created": len(g),
                            "resolved": int(g["is_resolved"].sum()),
                        }
                    )
        except Exception:
            pass

        return {
            "summary": {
                "total_tickets": total_tickets,
                "resolved_tickets": resolved_tickets,
                "open_tickets": open_tickets,
                "resolution_rate": round((resolved_tickets / total_tickets) * 100, 1) if total_tickets > 0 else 0.0,
                "avg_mtta_minutes": avg_mtta_mins,
                "mtta_sla_rate": mtta_sla_rate,
                "avg_total_mttr_hours": avg_total_mttr_hours,
                "avg_external_wait_hours": avg_external_wait_hours,
                "avg_net_mttr_hours": avg_net_mttr_hours,
                "mttr_sla_rate": mttr_sla_rate,
                "overall_sla_rate": overall_sla_rate,
                "fcr_count": fcr_count,
                "fcr_rate": fcr_rate,
                "reopen_count": reopen_count,
                "reopen_rate": reopen_rate,
                "bug_count": bug_count,
                "support_count": support_count,
                "suggestion_count": suggestion_count,
                "op_forwarded_total": op_forwarded_total,
            },
            "priorities": priority_data,
            "technicians": tech_matrix,
            "top_institutions": institution_stats[:10],
            "all_institutions": institution_stats,
            "openproject_summary": {
                "total_forwarded": op_forwarded_total,
                "baskets": op_baskets,
                "task_types": op_tasks,
                "demand_types": op_demands,
            },
            "daily_trends": daily_trends,
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        empty_sub = {
            "total_tickets": 0, "resolved_tickets": 0, "open_tickets": 0, "resolution_rate": 0.0,
            "avg_mtta_minutes": 0.0, "mtta_sla_rate": 0.0, "avg_total_mttr_hours": 0.0,
            "avg_external_wait_hours": 0.0, "avg_net_mttr_hours": 0.0, "mttr_sla_rate": 0.0,
            "overall_sla_rate": 0.0, "fcr_count": 0, "fcr_rate": 0.0, "reopen_count": 0,
            "reopen_rate": 0.0, "bug_count": 0, "support_count": 0,
        }
        return {
            "active_segment": "all",
            "summary": empty_sub,
            "priorities": [],
            "technicians": [],
            "top_institutions": [],
            "daily_trends": [],
            "column_diagnostics": {},
            "segments": {"all": empty_sub, "service_desk": empty_sub, "system_ops": empty_sub},
            "team_breakdown": {"service_desk_count": 0, "service_desk_resolved": 0, "system_ops_count": 0, "system_ops_resolved": 0},
        }

    def render_excel(self, metrics: Dict[str, Any], df: pd.DataFrame) -> io.BytesIO:
        """
        Renders an executive corporate 5-sheet Excel workbook with OpenPyXL:
        1. Konsolide Yönetici Özeti (Tepe operasyonel görünüm)
        2. Servis Masası (L1) (L1 personeli, MTTA, FCR, Reopen)
        3. Sistem Ekibi (L2) (Sistem/VT çağrıları, MTTR, Net efor)
        4. Kurum & Kök Neden Analizi (Kurumların hata/destek dağılımı)
        5. Detaylı Çağrı Listesi (Tüm çağrılar + Operasyonel Ekip kolonu)
        """
        clean_df, _ = self.standardize_dataframe(df) if not df.empty else (df, {})
        wb = openpyxl.Workbook()

        # Sheet 1: Konsolide Yönetici Paneli
        ws_summary = wb.active
        ws_summary.title = "1. Konsolide Yönetici Özeti"
        ws_summary.views.sheetView[0].showGridLines = True
        self._build_consolidated_summary_sheet(ws_summary, metrics, clean_df)

        # Sheet 2: Servis Masası (L1)
        ws_sd = wb.create_sheet(title="2. Servis Masası (L1)")
        ws_sd.views.sheetView[0].showGridLines = True
        df_sd = clean_df
        metrics_sd = self._compute_subset_metrics(df_sd)
        self._build_team_sheet(ws_sd, "SERVİS MASASI (L1 / BNSM - TÜM GELEN ÇAĞRILAR) PERFORMANS VE PERSONEL KARNESİ", metrics_sd, is_service_desk=True)

        # Sheet 3: Sistem Ekibi (L2)
        ws_sys = wb.create_sheet(title="3. Sistem Ekibi (L2)")
        ws_sys.views.sheetView[0].showGridLines = True
        df_sys = clean_df[clean_df["team_segment"] == "Sistem"]
        metrics_sys = self._compute_subset_metrics(df_sys)
        self._build_team_sheet(ws_sys, "SİSTEM, VERİTABANI VE DEPLOY (L2 / BN - L1'DEN AKTARILAN) PERFORMANS KARNESİ", metrics_sys, is_service_desk=False)

        # Sheet 4: Kurum & Kök Neden Analizi
        ws_inst = wb.create_sheet(title="4. Kurum & Talep Analizi")
        ws_inst.views.sheetView[0].showGridLines = True
        self._build_institution_sheet(ws_inst, metrics.get("all_institutions", metrics.get("top_institutions", [])))

        # Sheet 5: Detaylı Çağrı Listesi
        ws_raw = wb.create_sheet(title="5. Detaylı Çağrı Listesi")
        ws_raw.views.sheetView[0].showGridLines = True
        self._build_raw_data_sheet(ws_raw, clean_df)

        # Sheet 6: OpenProject & Kurum Analizi
        ws_op = wb.create_sheet(title="6. OpenProject & Kurum Analizi")
        ws_op.views.sheetView[0].showGridLines = True
        self._build_openproject_sheet(ws_op, metrics, clean_df)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def _build_consolidated_summary_sheet(self, ws: openpyxl.worksheet.worksheet.Worksheet, metrics: Dict[str, Any], df: pd.DataFrame) -> None:
        summary = metrics.get("summary", {})
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        tb = metrics.get("team_breakdown", {})
        segs = metrics.get("segments", {})

        col_widths = {"A": 4, "B": 26, "C": 20, "D": 22, "E": 22, "F": 22, "G": 20, "H": 4}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # 1. Main Banner Header
        ws.merge_cells("B2:G2")
        title_cell = ws["B2"]
        title_cell.value = "METRİKA | BELGENET OPERASYONEL PERFORMANS VE SLA RAPORU (KONSOLİDE)"
        title_cell.font = Font(name="Calibri", size=15, bold=True, color=self.COLOR_WHITE)
        title_cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, end_color=self.COLOR_NAVY_DARK, fill_type="solid")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 40

        ws.merge_cells("B3:G3")
        subtitle_cell = ws["B3"]
        subtitle_cell.value = f"Rapor Oluşturulma: {now_str}  |  Kapsam: Servis Masası (L1 / BNSM) ve Sistem Ekibi (L2 / BN) Bütüncül Özeti"
        subtitle_cell.font = Font(name="Calibri", size=10, italic=True, color="94A3B8")
        subtitle_cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, end_color=self.COLOR_NAVY_DARK, fill_type="solid")
        subtitle_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 22

        thin_border = Border(
            left=Side(style="thin", color=self.COLOR_BORDER),
            right=Side(style="thin", color=self.COLOR_BORDER),
            top=Side(style="thin", color=self.COLOR_BORDER),
            bottom=Side(style="thin", color=self.COLOR_BORDER),
        )

        # 2. Executive KPI Cards (Row 5 - 7)
        kpi_cards = [
            ("TOPLAM ÇAĞRI HACMİ", f"{summary.get('total_tickets', 0):,}", f"{summary.get('open_tickets', 0)} Açık / Devam Eden", "B", "B"),
            ("ÇÖZÜM BAŞARI ORANI", f"%{summary.get('resolution_rate', 0.0)}", f"{summary.get('resolved_tickets', 0)} Çözülen / Kapatılan", "C", "C"),
            ("İLK ELE ALINMA (MTTA)", f"{summary.get('avg_mtta_minutes', 0.0)} dk", "Ortalama İlk Yanıt", "D", "D"),
            ("NET ÇÖZÜM SÜRESİ (MTTR)", f"{summary.get('avg_net_mttr_hours', 0.0)} saat", f"Dış bekleme: {summary.get('avg_external_wait_hours', 0.0)} sa", "E", "E"),
            ("İLK TEMASTA ÇÖZÜM (FCR)", f"%{summary.get('fcr_rate', 0.0)}", f"{summary.get('fcr_count', 0)} çağrı devredilmeden", "F", "F"),
            ("YENİDEN AÇILMA ORANI", f"%{summary.get('reopen_rate', 0.0)}", f"{summary.get('reopen_count', 0)} çağrı tekrar açıldı", "G", "G"),
        ]

        ws.row_dimensions[5].height = 24
        ws.row_dimensions[6].height = 36
        ws.row_dimensions[7].height = 20

        for title, val, subtext, col_start, col_end in kpi_cards:
            if col_start != col_end:
                ws.merge_cells(f"{col_start}5:{col_end}5")
                ws.merge_cells(f"{col_start}6:{col_end}6")
                ws.merge_cells(f"{col_start}7:{col_end}7")

            c_top = ws[f"{col_start}5"]
            c_top.value = title
            c_top.font = Font(name="Calibri", size=9, bold=True, color="64748B")
            c_top.fill = PatternFill(start_color=self.COLOR_KPI_BG, fill_type="solid")
            c_top.alignment = Alignment(horizontal="center", vertical="center")

            c_mid = ws[f"{col_start}6"]
            c_mid.value = val
            c_mid.font = Font(name="Calibri", size=16, bold=True, color=self.COLOR_NAVY_DARK)
            c_mid.fill = PatternFill(start_color=self.COLOR_KPI_BG, fill_type="solid")
            c_mid.alignment = Alignment(horizontal="center", vertical="center")

            c_bot = ws[f"{col_start}7"]
            c_bot.value = subtext
            c_bot.font = Font(name="Calibri", size=8, italic=True, color="64748B")
            c_bot.fill = PatternFill(start_color=self.COLOR_KPI_BG, fill_type="solid")
            c_bot.alignment = Alignment(horizontal="center", vertical="center")

            for r in range(5, 8):
                ws[f"{col_start}{r}"].border = thin_border

        # 3. Section 1: Ekip Bazlı Dağılım Matrisi (Row 10+)
        ws.merge_cells("B10:G10")
        sec1 = ws["B10"]
        sec1.value = "1. OPERASYONEL EKİP PERFORMANS VE ÇÖZÜM KARŞILAŞTIRMASI"
        sec1.font = Font(name="Calibri", size=11, bold=True, color=self.COLOR_WHITE)
        sec1.fill = PatternFill(start_color=self.COLOR_SLATE_HEADER, fill_type="solid")
        sec1.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[10].height = 28

        headers_sec1 = ["Operasyonel Ekip", "Toplam Çağrı", "Çözülen Çağrı", "Çözüm Oranı (%)", "Ort. Net Efor (Saat)", "Ort. İlk Yanıt (dk)"]
        cols_sec1 = ["B", "C", "D", "E", "F", "G"]
        ws.row_dimensions[11].height = 24

        for c_letter, h_text in zip(cols_sec1, headers_sec1):
            cell = ws[f"{c_letter}11"]
            cell.value = h_text
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_NAVY_DARK)
            cell.fill = PatternFill(start_color="E2E8F0", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        sd_s = segs.get("service_desk", {})
        sys_s = segs.get("system_ops", {})
        all_s = segs.get("all", {})

        team_rows = [
            ("Servis Masası (L1 / BNSM - Tüm Gelen Çağrılar)", sd_s.get("total_tickets", 0), sd_s.get("resolved_tickets", 0), sd_s.get("resolution_rate", 0.0), sd_s.get("avg_net_mttr_hours", 0.0), sd_s.get("avg_mtta_minutes", 0.0)),
            ("Sistem & Veritabanı / Deploy (L2 / BN - L1'den Aktarılan)", sys_s.get("total_tickets", 0), sys_s.get("resolved_tickets", 0), sys_s.get("resolution_rate", 0.0), sys_s.get("avg_net_mttr_hours", 0.0), sys_s.get("avg_mtta_minutes", 0.0)),
            ("GENEL OPERASYONEL TOPLAM", all_s.get("total_tickets", 0), all_s.get("resolved_tickets", 0), all_s.get("resolution_rate", 0.0), all_s.get("avg_net_mttr_hours", 0.0), all_s.get("avg_mtta_minutes", 0.0)),
        ]

        curr_r = 12
        for t_name, t_tot, t_res, t_rate, t_efor, t_mtta in team_rows:
            ws.row_dimensions[curr_r].height = 22
            is_total_row = "TOPLAM" in t_name
            bg_c = "F1F5F9" if is_total_row else (self.COLOR_SLATE_BG if curr_r % 2 == 0 else self.COLOR_WHITE)
            fill_c = PatternFill(start_color=bg_c, fill_type="solid")

            ws[f"B{curr_r}"].value = t_name
            ws[f"B{curr_r}"].font = Font(name="Calibri", size=10, bold=is_total_row)
            ws[f"B{curr_r}"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

            ws[f"C{curr_r}"].value = t_tot
            ws[f"C{curr_r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"C{curr_r}"].number_format = "#,##0"

            ws[f"D{curr_r}"].value = t_res
            ws[f"D{curr_r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"D{curr_r}"].number_format = "#,##0"

            ws[f"E{curr_r}"].value = t_rate / 100.0
            ws[f"E{curr_r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"E{curr_r}"].number_format = "0.0%"

            ws[f"F{curr_r}"].value = t_efor
            ws[f"F{curr_r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"F{curr_r}"].number_format = "0.0"

            ws[f"G{curr_r}"].value = t_mtta
            ws[f"G{curr_r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"G{curr_r}"].number_format = "#,##0.0"

            for c_letter in cols_sec1:
                ws[f"{c_letter}{curr_r}"].fill = fill_c
                ws[f"{c_letter}{curr_r}"].border = thin_border
            curr_r += 1

        # 4. Section 2: Terimler ve Hesaplama Metodolojisi Notu (Row curr_r + 2)
        curr_r += 2
        ws.merge_cells(f"B{curr_r}:G{curr_r}")
        sec2 = ws[f"B{curr_r}"]
        sec2.value = "2. RAPORDA KULLANILAN METRİK VE TERİM AÇIKLAMALARI"
        sec2.font = Font(name="Calibri", size=11, bold=True, color=self.COLOR_WHITE)
        sec2.fill = PatternFill(start_color=self.COLOR_SLATE_HEADER, fill_type="solid")
        sec2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[curr_r].height = 28

        terms = [
            ("İlk Ele Alınma Süresi (MTTA)", "Çağrının açıldığı andan personele atanıp ilk aksiyon/yanıt verilmesine kadar geçen fiili süredir."),
            ("Net Çözüm Süresi (MTTR)", "Açılıştan çözüme kadar geçen toplam süreden kurumun bilgi/onay bekleme süresinin düşülmesiyle bulunan net çalışma eforudur."),
            ("Kurum / Dış Bekleme Süresi", "Kurumdan ek log, imza test veya yetkili onayı beklenirken dondurulan süredir. Personelin net eforunu etkilemez."),
            ("İlk Temasta Çözüm (FCR)", "L1 Servis Masası tarafından başka birime, yazılım ekibine veya OpenProject'e devredilmeden doğrudan kapatılan çağrılardır."),
            ("Yeniden Açılma Oranı (Reopen)", "Çözümlendiği bildirilmesine rağmen kullanıcının teyit vermeyip tekrar açtığı çağrıların oranıdır (Hizmet kalitesi göstergesi)."),
            ("Operasyonel Ekip Segmentasyonu", "GLPI çağrıları; Görev Tipi ve Teknisyen listesi baz alınarak 'Servis Masası (L1)' ve 'Sistem Ekibi (L2 - Veritabanı / Deploy)' olarak ayrıştırılmıştır."),
        ]

        for t_label, t_desc in terms:
            curr_r += 1
            ws.row_dimensions[curr_r].height = 24
            ws[f"B{curr_r}"].value = t_label
            ws[f"B{curr_r}"].font = Font(name="Calibri", size=10, bold=True, color=self.COLOR_NAVY_DARK)
            ws[f"B{curr_r}"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
            ws[f"B{curr_r}"].border = thin_border

            ws.merge_cells(f"C{curr_r}:G{curr_r}")
            for c_letter in ["C", "D", "E", "F", "G"]:
                ws[f"{c_letter}{curr_r}"].border = thin_border
            c_desc = ws[f"C{curr_r}"]
            c_desc.value = t_desc
            c_desc.font = Font(name="Calibri", size=9, italic=True, color="475569")
            c_desc.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    def _build_team_sheet(self, ws: openpyxl.worksheet.worksheet.Worksheet, title_text: str, metrics: Dict[str, Any], is_service_desk: bool = True) -> None:
        summary = metrics.get("summary", {})
        technicians = metrics.get("technicians", [])

        # Column Widths
        col_widths = {"A": 28, "B": 14, "C": 14, "D": 16, "E": 18, "F": 16, "G": 18, "H": 18}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # Title
        ws.merge_cells("A2:H2")
        title = ws["A2"]
        title.value = title_text
        title.font = Font(name="Calibri", size=13, bold=True, color=self.COLOR_WHITE)
        title.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, fill_type="solid")
        title.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 35

        # Subtitle KPI banner
        ws.merge_cells("A3:H3")
        subtitle = ws["A3"]
        sub_info = (
            f"Toplam Çağrı: {summary.get('total_tickets', 0)}  |  "
            f"Çözülen: {summary.get('resolved_tickets', 0)} (%{summary.get('resolution_rate', 0.0)})  |  "
            f"Ort. İlk Yanıt: {summary.get('avg_mtta_minutes', 0.0)} dk  |  "
            f"Ort. Net Efor: {summary.get('avg_net_mttr_hours', 0.0)} sa"
        )
        if is_service_desk:
            sub_info += f"  |  FCR: %{summary.get('fcr_rate', 0.0)}  |  Reopen: %{summary.get('reopen_rate', 0.0)}"
        subtitle.value = sub_info
        subtitle.font = Font(name="Calibri", size=10, italic=True, color=self.COLOR_WHITE)
        subtitle.fill = PatternFill(start_color=self.COLOR_NAVY_LIGHT, fill_type="solid")
        subtitle.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 22

        headers = [
            ("Teknisyen Adı (Normalleştirilmiş)", 28),
            ("Atanan Çağrı", 14),
            ("Çözülen Çağrı", 14),
            ("Çözüm Oranı (%)", 16),
            ("Ort. Net Efor (Saat)", 18),
            ("Ort. İlk Yanıt (dk)", 18),
            ("Ort. Dış Bekleme (Saat)", 18),
            ("Yeniden Açılma (%)", 18),
        ]

        thin_border = Border(
            left=Side(style="thin", color=self.COLOR_BORDER),
            right=Side(style="thin", color=self.COLOR_BORDER),
            top=Side(style="thin", color=self.COLOR_BORDER),
            bottom=Side(style="thin", color=self.COLOR_BORDER),
        )

        ws.row_dimensions[5].height = 26
        for col_idx, (h_text, width) in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            cell = ws.cell(row=5, column=col_idx, value=h_text)
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_WHITE)
            cell.fill = PatternFill(start_color=self.COLOR_SLATE_HEADER, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        for r_idx, tech in enumerate(technicians, start=6):
            ws.row_dimensions[r_idx].height = 22
            bg_color = self.COLOR_SLATE_BG if r_idx % 2 == 0 else self.COLOR_WHITE
            fill = PatternFill(start_color=bg_color, fill_type="solid")

            row_values = [
                tech["technician"],
                tech["assigned_count"],
                tech["resolved_count"],
                tech["resolution_rate"] / 100.0,
                tech["avg_net_resolution_hours"],
                tech.get("avg_first_response_minutes", 0.0),
                tech.get("avg_external_wait_hours", 0.0),
                tech["reopen_rate"] / 100.0,
            ]

            for c_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.fill = fill
                cell.border = thin_border

                if c_idx == 1:
                    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                    cell.font = Font(name="Calibri", size=10, bold=True)
                elif c_idx in (2, 3):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "#,##0"
                elif c_idx in (4, 8):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "0.0%"
                elif c_idx in (5, 6, 7):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "0.0"

        # Summary Row (Excel Formula)
        tot_row = len(technicians) + 6
        ws.row_dimensions[tot_row].height = 25
        sum_fill = PatternFill(start_color="E2E8F0", fill_type="solid")
        ws.cell(row=tot_row, column=1, value="GENEL TOPLAM / ORTALAMA").font = Font(name="Calibri", size=10, bold=True)
        ws.cell(row=tot_row, column=1).alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.cell(row=tot_row, column=1).fill = sum_fill
        ws.cell(row=tot_row, column=1).border = thin_border

        if technicians:
            last_r = tot_row - 1
            c2 = ws.cell(row=tot_row, column=2, value=f"=SUM(B6:B{last_r})")
            c2.number_format = "#,##0"
            c3 = ws.cell(row=tot_row, column=3, value=f"=SUM(C6:C{last_r})")
            c3.number_format = "#,##0"
            c4 = ws.cell(row=tot_row, column=4, value=f"=AVERAGE(D6:D{last_r})")
            c4.number_format = "0.0%"
            c5 = ws.cell(row=tot_row, column=5, value=f"=AVERAGE(E6:E{last_r})")
            c5.number_format = "0.0"
            c6 = ws.cell(row=tot_row, column=6, value=f"=AVERAGE(F6:F{last_r})")
            c6.number_format = "0.0"
            c7 = ws.cell(row=tot_row, column=7, value=f"=AVERAGE(G6:G{last_r})")
            c7.number_format = "0.0"
            c8 = ws.cell(row=tot_row, column=8, value=f"=AVERAGE(H6:H{last_r})")
            c8.number_format = "0.0%"

            for c_idx in range(2, 9):
                cell = ws.cell(row=tot_row, column=c_idx)
                cell.font = Font(name="Calibri", size=10, bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill = sum_fill
                cell.border = thin_border

    def _build_institution_sheet(self, ws: openpyxl.worksheet.worksheet.Worksheet, top_institutions: List[Dict[str, Any]]) -> None:
        ws.merge_cells("A2:F2")
        title = ws["A2"]
        title.value = "EN ÇOK ÇAĞRI AÇAN İLK 10 KURUM VE KÖK NEDEN KIRILIMI"
        title.font = Font(name="Calibri", size=13, bold=True, color=self.COLOR_WHITE)
        title.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, fill_type="solid")
        title.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 35

        headers = [
            ("Kurum Adı", 34),
            ("Toplam Çağrı", 15),
            ("Hata", 14),
            ("Destek", 15),
            ("Öneri (Ek Geliştirme)", 22),
            ("Hata Oranı (%)", 15),
            ("OP İletilen", 14),
            ("Yoğunluk Durumu", 18),
        ]

        thin_border = Border(
            left=Side(style="thin", color=self.COLOR_BORDER),
            right=Side(style="thin", color=self.COLOR_BORDER),
            top=Side(style="thin", color=self.COLOR_BORDER),
            bottom=Side(style="thin", color=self.COLOR_BORDER),
        )

        ws.row_dimensions[4].height = 26
        for col_idx, (h_text, width) in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width
            cell = ws.cell(row=4, column=col_idx, value=h_text)
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_WHITE)
            cell.fill = PatternFill(start_color=self.COLOR_NAVY_LIGHT, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        for r_idx, inst in enumerate(top_institutions, start=5):
            ws.row_dimensions[r_idx].height = 22
            bg_color = self.COLOR_SLATE_BG if r_idx % 2 == 0 else self.COLOR_WHITE
            fill = PatternFill(start_color=bg_color, fill_type="solid")

            row_values = [
                inst["institution"],
                inst["total_count"],
                inst["bug_count"],
                inst["support_count"],
                inst.get("suggestion_count", 0),
                inst["bug_percentage"] / 100.0,
                inst.get("op_forwarded_count", 0),
            ]

            for c_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.fill = fill
                cell.border = thin_border

                if c_idx == 1:
                    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                    cell.font = Font(name="Calibri", size=10, bold=True)
                elif c_idx in (2, 3, 4, 5, 7):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "#,##0"
                elif c_idx == 6:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "0.0%"

            pill = ws.cell(row=r_idx, column=8)
            pill.border = thin_border
            pill.alignment = Alignment(horizontal="center", vertical="center")
            if inst["bug_percentage"] > 40.0:
                pill.value = "Yüksek Hata Payı"
                pill.fill = PatternFill(start_color=self.COLOR_DANGER_BG, fill_type="solid")
                pill.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_DANGER_TEXT)
            else:
                pill.value = "Normal Destek Dağılımı"
                pill.fill = PatternFill(start_color=self.COLOR_SUCCESS_BG, fill_type="solid")
                pill.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_SUCCESS_TEXT)

    def _build_raw_data_sheet(self, ws: openpyxl.worksheet.worksheet.Worksheet, df: pd.DataFrame) -> None:
        if df.empty:
            ws.cell(row=1, column=1, value="Kayıt bulunamadı.")
            return

        headers = [
            ("Çağrı No", "ticket_id", 14),
            ("Operasyonel Ekip", "team_segment", 18),
            ("Başlık", "title", 35),
            ("Kurum", "institution", 28),
            ("Kategori", "category", 24),
            ("Kök Neden", "root_cause", 14),
            ("Öncelik", "priority", 14),
            ("Durum", "status", 16),
            ("Teknisyen", "technician", 22),
            ("Açılış Tarihi", "created_at", 18),
            ("İlk Yanıt (Dk)", "first_response_minutes", 14),
            ("Net Efor (Saat)", "net_resolution_hours", 14),
            ("Dış Bekleme (Saat)", "external_wait_hours", 16),
            ("İlk Yanıt SLA", "mtta_sla_compliant", 14),
            ("Çözüm SLA", "mttr_sla_compliant", 14),
            ("FCR", "is_fcr", 10),
            ("Yeniden Açıldı", "is_reopened", 14),
            ("OP Talep Tipi", "op_request_type", 26),
            ("OP Görev Tipi", "op_task_type", 24),
            ("OP Hedef Sepet", "op_basket", 24),
        ]

        thin_border = Border(
            left=Side(style="thin", color=self.COLOR_BORDER),
            right=Side(style="thin", color=self.COLOR_BORDER),
            top=Side(style="thin", color=self.COLOR_BORDER),
            bottom=Side(style="thin", color=self.COLOR_BORDER),
        )

        ws.row_dimensions[1].height = 28
        for col_idx, (h_title, key, width) in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width
            cell = ws.cell(row=1, column=col_idx, value=h_title)
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_WHITE)
            cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r_idx, (_, row) in enumerate(df.iterrows(), start=2):
            ws.row_dimensions[r_idx].height = 20
            bg_color = self.COLOR_SLATE_BG if r_idx % 2 == 0 else self.COLOR_WHITE
            fill = PatternFill(start_color=bg_color, fill_type="solid")

            for c_idx, (_, key, _) in enumerate(headers, start=1):
                val = row.get(key, "")
                if isinstance(val, (bool,)):
                    val = "Evet" if val else "Hayır"

                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.fill = fill
                cell.border = thin_border

                if c_idx in (1, 2, 6, 7, 8, 10, 14, 15, 16, 17):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx in (11, 12, 13):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "0.0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

                # Highlight team segment
                if c_idx == 2:
                    if str(val) == "Sistem":
                        cell.font = Font(name="Calibri", size=9, bold=True, color="1E3A8A")
                        cell.fill = PatternFill(start_color="DBEAFE", fill_type="solid")
                    else:
                        cell.font = Font(name="Calibri", size=9, bold=True, color="065F46")
                        cell.fill = PatternFill(start_color="D1FAE5", fill_type="solid")

        last_col = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A1:{last_col}{len(df) + 1}"
        ws.freeze_panes = "A2"

    def _build_openproject_sheet(self, ws: openpyxl.worksheet.worksheet.Worksheet, metrics: Dict[str, Any], df: pd.DataFrame) -> None:
        summary = metrics.get("summary", {})
        all_institutions = metrics.get("all_institutions", metrics.get("top_institutions", []))
        total_tickets = summary.get("total_tickets", len(df))
        op_forwarded_total = summary.get("op_forwarded_total", 0)
        op_rate = round((op_forwarded_total / total_tickets) * 100, 1) if total_tickets > 0 else 0.0

        col_widths = {"A": 4, "B": 32, "C": 15, "D": 16, "E": 14, "F": 14, "G": 22, "H": 26, "I": 26, "J": 4}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # 1. Main Banner Header
        ws.merge_cells("B2:I2")
        title_cell = ws["B2"]
        title_cell.value = "METRİKA | OPENPROJECT ENTEGRASYON VE KURUM DETAY ANALİZİ"
        title_cell.font = Font(name="Calibri", size=15, bold=True, color=self.COLOR_WHITE)
        title_cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, end_color=self.COLOR_NAVY_DARK, fill_type="solid")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 40

        ws.merge_cells("B3:I3")
        subtitle_cell = ws["B3"]
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        subtitle_cell.value = f"Rapor Tarihi: {now_str}  |  GLPI Servis Masasından OpenProject'e İletilen Çağrılar, Görev Tipleri ve Sepet Dağılımı"
        subtitle_cell.font = Font(name="Calibri", size=10, italic=True, color="94A3B8")
        subtitle_cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, end_color=self.COLOR_NAVY_DARK, fill_type="solid")
        subtitle_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 22

        thin_border = Border(
            left=Side(style="thin", color=self.COLOR_BORDER),
            right=Side(style="thin", color=self.COLOR_BORDER),
            top=Side(style="thin", color=self.COLOR_BORDER),
            bottom=Side(style="thin", color=self.COLOR_BORDER),
        )

        # 2. KPI Summary Cards (Row 5 - 7)
        op_df = df[df["is_op_forwarded"]] if "is_op_forwarded" in df.columns else pd.DataFrame()
        hata_sepeti = int((op_df["op_basket"].str.contains("hata", case=False, na=False)).sum()) if not op_df.empty else 0
        sistem_sepeti = int((op_df["op_basket"].str.contains("sistem", case=False, na=False)).sum()) if not op_df.empty else 0
        iyilestirme_sepeti = int((op_df["op_basket"].str.contains("iyileştirme|iyilestirme|oneri|öneri", case=False, na=False)).sum()) if not op_df.empty else 0

        kpis = [
            ("TOPLAM ÇAĞRI", f"{total_tickets:,}", "Tüm Operasyon", "B", "C"),
            ("OPENPROJECT'E İLETİLEN", f"{op_forwarded_total:,}", f"%{op_rate} İletim Oranı", "D", "E"),
            ("HATA SEPETİ", f"{hata_sepeti:,}", "Yazılım / Hata Havuzu", "F", "F"),
            ("SİSTEM SEPETİ", f"{sistem_sepeti:,}", "Altyapı / VT Havuzu", "G", "G"),
            ("İYİLEŞTİRME / ÖNERİ", f"{iyilestirme_sepeti:,}", "Ek Geliştirme Havuzu", "H", "I"),
        ]

        ws.row_dimensions[5].height = 18
        ws.row_dimensions[6].height = 28
        ws.row_dimensions[7].height = 18

        for title, val, note, start_col, end_col in kpis:
            range_header = f"{start_col}5:{end_col}5"
            range_val = f"{start_col}6:{end_col}6"
            range_note = f"{start_col}7:{end_col}7"

            if start_col != end_col:
                ws.merge_cells(range_header)
                ws.merge_cells(range_val)
                ws.merge_cells(range_note)

            c_h = ws[f"{start_col}5"]
            c_h.value = title
            c_h.font = Font(name="Calibri", size=9, bold=True, color="64748B")
            c_h.alignment = Alignment(horizontal="center", vertical="center")
            c_h.fill = PatternFill(start_color=self.COLOR_SLATE_BG, fill_type="solid")

            c_v = ws[f"{start_col}6"]
            c_v.value = val
            c_v.font = Font(name="Calibri", size=15, bold=True, color=self.COLOR_NAVY_DARK)
            c_v.alignment = Alignment(horizontal="center", vertical="center")
            c_v.fill = PatternFill(start_color=self.COLOR_SLATE_BG, fill_type="solid")

            c_n = ws[f"{start_col}7"]
            c_n.value = note
            c_n.font = Font(name="Calibri", size=8, italic=True, color="64748B")
            c_n.alignment = Alignment(horizontal="center", vertical="center")
            c_n.fill = PatternFill(start_color=self.COLOR_SLATE_BG, fill_type="solid")

            start_idx = column_index_from_string(start_col)
            end_idx = column_index_from_string(end_col)
            for r in range(5, 8):
                for c in range(start_idx, end_idx + 1):
                    ws.cell(row=r, column=c).border = thin_border

        # 3. Table 1: Kurum Bazlı OpenProject Özeti
        ws.merge_cells("B9:I9")
        t1_title = ws["B9"]
        t1_title.value = "KURUM BAZLI OPENPROJECT İLETİM, TALEP VE SEPET DAĞILIMI"
        t1_title.font = Font(name="Calibri", size=11, bold=True, color=self.COLOR_NAVY_DARK)
        t1_title.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[9].height = 24

        table_headers = [
            ("Kurum Adı", 32),
            ("Toplam Çağrı", 15),
            ("OP'ye İletilen", 16),
            ("Hata Talebi", 14),
            ("Destek Talebi", 14),
            ("Öneri (Ek Geliştirme)", 22),
            ("Baskın Görev Tipi", 26),
            ("Baskın Hedef Sepet", 26),
        ]

        ws.row_dimensions[10].height = 26
        for c_idx, (h_name, width) in enumerate(table_headers, start=2):
            cell = ws.cell(row=10, column=c_idx, value=h_name)
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_WHITE)
            cell.fill = PatternFill(start_color=self.COLOR_NAVY_LIGHT, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        curr_row = 11
        for inst in all_institutions:
            op_summary = inst.get("openproject_summary", {})
            demands = op_summary.get("demand_types", {})
            raw_tasks = op_summary.get("task_types", {})
            raw_baskets = op_summary.get("baskets", {})

            dominant_task = max(raw_tasks.items(), key=lambda x: x[1])[0] if raw_tasks else "-"
            dominant_basket = max(raw_baskets.items(), key=lambda x: x[1])[0] if raw_baskets else "-"

            ws.row_dimensions[curr_row].height = 20
            bg = self.COLOR_SLATE_BG if curr_row % 2 == 0 else self.COLOR_WHITE
            fill = PatternFill(start_color=bg, fill_type="solid")

            row_data = [
                inst["institution"],
                inst["total_count"],
                inst.get("op_forwarded_count", 0),
                demands.get("Hata", 0),
                demands.get("Destek", 0),
                demands.get("Öneri", inst.get("suggestion_count", 0)),
                dominant_task,
                dominant_basket,
            ]

            for c_idx, val in enumerate(row_data, start=2):
                cell = ws.cell(row=curr_row, column=c_idx, value=val)
                cell.fill = fill
                cell.border = thin_border

                if c_idx == 2:
                    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                    cell.font = Font(name="Calibri", size=10, bold=True)
                elif c_idx in (3, 4, 5, 6, 7):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.number_format = "#,##0"
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
                    cell.font = Font(name="Calibri", size=9)

            curr_row += 1

        # 4. Table 2: OpenProject'e İletilen Çağrılar Detayı
        curr_row += 2
        ws.merge_cells(f"B{curr_row}:I{curr_row}")
        t2_title = ws[f"B{curr_row}"]
        t2_title.value = "OPENPROJECT'E İLETİLEN ÇAĞRILARIN DETAYLI LİSTESİ"
        t2_title.font = Font(name="Calibri", size=11, bold=True, color=self.COLOR_NAVY_DARK)
        t2_title.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[curr_row].height = 24

        curr_row += 1
        t2_headers = [
            ("Çağrı No", 14),
            ("Kurum", 28),
            ("Kategori / Tip", 16),
            ("OP Talep Tipi", 24),
            ("OP Görev Tipi", 24),
            ("OP Hedef Sepet", 24),
            ("Teknisyen", 20),
            ("Durum", 16),
        ]
        ws.row_dimensions[curr_row].height = 24
        for c_idx, (h_name, width) in enumerate(t2_headers, start=2):
            cell = ws.cell(row=curr_row, column=c_idx, value=h_name)
            cell.font = Font(name="Calibri", size=9, bold=True, color=self.COLOR_WHITE)
            cell.fill = PatternFill(start_color=self.COLOR_NAVY_DARK, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        curr_row += 1
        if not op_df.empty:
            for _, op_row in op_df.iterrows():
                ws.row_dimensions[curr_row].height = 19
                bg = self.COLOR_SLATE_BG if curr_row % 2 == 0 else self.COLOR_WHITE
                fill = PatternFill(start_color=bg, fill_type="solid")

                t2_values = [
                    str(op_row.get("ticket_id", "")),
                    str(op_row.get("institution", "")),
                    str(op_row.get("root_cause", "")),
                    str(op_row.get("op_request_type", "")),
                    str(op_row.get("op_task_type", "")),
                    str(op_row.get("op_basket", "")),
                    str(op_row.get("technician", "")),
                    str(op_row.get("status", "")),
                ]

                for c_idx, val in enumerate(t2_values, start=2):
                    cell = ws.cell(row=curr_row, column=c_idx, value=val)
                    cell.fill = fill
                    cell.border = thin_border
                    if c_idx in (2, 4, 9):
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")
                curr_row += 1
        else:
            ws.cell(row=curr_row, column=2, value="OpenProject'e iletilen kayıt bulunmuyor.")

