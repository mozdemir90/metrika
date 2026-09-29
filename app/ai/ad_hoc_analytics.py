import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from app.ai.qwen_client import QwenClient
from app.reports.service_desk_report import ServiceDeskReport

logger = logging.getLogger("metrika.ai.adhoc")


class AdHocAnalyticsEngine:
    """
    Qwen-Powered Natural Language Analytics & Dynamic Chart Generation Engine.
    Processes user prompts regarding Belgenet GLPI service desk data, enforces
    strict operational guardrails, computes zero-hallucination exact aggregates
    using Pandas, and generates interactive Chart.js visualizations.
    """

    # Operational keywords for guardrail verification
    OPERATIONAL_KEYWORDS = [
        "çağrı", "cagri", "talep", "hata", "arıza", "ariza", "destek", "oneri", "öneri",
        "ek geliştirme", "ek hizmet", "kurum", "sepet", "görev", "gorev", "teknisyen",
        "personel", "sistem", "servis masası", "bnsm", "sla", "mtta", "mttr", "fcr",
        "reopen", "yeniden", "açılış", "kapanış", "çözüm", "çözülen", "gün", "hafta",
        "grafik", "sayı", "oran", "dağılım", "toplam", "openproject", "deploy", "veritabanı"
    ]

    def __init__(self, qwen_client: Optional[QwenClient] = None):
        self.qwen = qwen_client or QwenClient()
        self.report_engine = ServiceDeskReport()

    def is_operational_query(self, prompt: str) -> bool:
        """
        Guardrail check: Ensures the prompt is within the domain of service desk,
        call metrics, institutions, baskets, technicians, or SLAs.
        """
        p_lower = prompt.lower().strip()
        if len(p_lower) < 3:
            return False

        # Explicit non-operational markers
        irrelevant_patterns = [
            r"\bhava\s*durumu\b", r"\byemek\s*tarifi\b", r"\bşiir\b", r"\bfıkra\b",
            r"\bpolitika\b", r"\bfutbol\b", r"\bfilm\b", r"\bşarkı\b", r"\bhikaye\b"
        ]
        if any(re.search(pat, p_lower) for pat in irrelevant_patterns):
            return False

        return any(kw in p_lower for kw in self.OPERATIONAL_KEYWORDS)

    async def execute_query(
        self,
        prompt: str,
        df: pd.DataFrame,
        days: int = 0,
        segment: str = "all",
    ) -> Dict[str, Any]:
        """
        Main query executor: Guardrails -> Semantic Extraction -> Exact Pandas Aggregations -> Chart & Narrative.
        """
        # 1. Guardrail Validation
        if not self.is_operational_query(prompt):
            return {
                "is_applicable": False,
                "refusal_reason": (
                    "Bu asistan yalnızca METRİKA operasyonel çağrı kayıtları, kurum/sepet analizleri, "
                    "kök neden dağılımları, teknisyen ve SLA istatistikleri için yetkilendirilmiştir. "
                    "Lütfen servis masası veya kurum operasyonlarına yönelik bir soru iletiniz."
                ),
                "answer_text": (
                    "⚠️ **Kapsam Dışı Soru:** Sorgunuz operasyonel GLPI çağrı ve metrik verilerinin kapsamı dışındadır. "
                    "Lütfen kurum, sepet, görev tipi, teknisyen veya SLA istatistiklerine yönelik bir analiz sorusu sorunuz."
                ),
                "summary_cards": [],
                "chart": {"has_chart": False},
                "table": {"has_table": False},
                "matched_count": 0,
            }

        # 2. Standardize DataFrame
        work_df, _ = self.report_engine.standardize_dataframe(df)
        if work_df.empty:
            return {
                "is_applicable": True,
                "answer_text": "İncelenen veri kümesinde çağrı kaydı bulunamadı.",
                "summary_cards": [{"label": "Toplam Kayıt", "value": "0", "color": "slate"}],
                "chart": {"has_chart": False},
                "table": {"has_table": False},
                "matched_count": 0,
            }

        p_lower = prompt.lower()

        # 3. Entity & Filter Extraction
        filtered_df = work_df.copy()
        applied_filters: List[str] = []

        if days > 0 and days < 999:
            applied_filters.append(f"Son {days} Gün")

        # 3.1 Institution Detection
        matched_institution = None
        common_inst_stopwords = {
            "türkiye", "cumhuriyeti", "bakanlığı", "bakanlık", "bakanlığ", "bakan", "genel", "müdürlüğü",
            "müdürlük", "müdürlüğ", "başkanlığı", "başkanlık", "başkanlığ", "başkan", "daire", "kurumu", "kurum",
            "kurulu", "kurul", "valiliği", "valilik", "sistem", "sistemleri", "destek", "destekleme", "hizmet",
            "hizmetleri", "bilgi", "işlem", "yönetimi", "yönetim", "şirketi", "anonim", "ticaret", "mühendislik",
            "a.ş", "aş", "ve", "ile"
        }
        unique_insts = sorted(work_df["institution"].dropna().unique(), key=len, reverse=True)
        # Check full string first
        for inst in unique_insts:
            inst_clean = str(inst).lower()
            if inst_clean in p_lower:
                matched_institution = inst
                break

        # If not full match, check distinctive keywords
        if not matched_institution:
            for inst in unique_insts:
                inst_clean = str(inst).lower()
                words = [w for w in re.split(r"[\s,.-]+", inst_clean) if len(w) >= 4 and w not in common_inst_stopwords]
                for w in words:
                    if w in p_lower:
                        matched_institution = inst
                        break
                if matched_institution:
                    break

        if matched_institution:
            filtered_df = filtered_df[filtered_df["institution"] == matched_institution]
            applied_filters.append(f"Kurum: {matched_institution}")

        # 3.2 Root Cause Detection (Hata, Destek, Öneri)
        if any(w in p_lower for w in ("öneri", "oneri", "ek geliştirme", "ek gelistirme", "ek hizmet")):
            filtered_df = filtered_df[filtered_df["root_cause"] == "Öneri"]
            applied_filters.append("Tip: Öneri (Ek Geliştirme)")
        elif any(w in p_lower for w in ("hata", "bug", "arıza", "ariza", "kesinti", "problem")):
            filtered_df = filtered_df[filtered_df["root_cause"] == "Hata"]
            applied_filters.append("Tip: Hata")
        elif "destek" in p_lower:
            filtered_df = filtered_df[filtered_df["root_cause"] == "Destek"]
            applied_filters.append("Tip: Destek")

        # 3.3 Basket Detection
        basket_keywords = {
            "sistem": "BN-Sistem Sepetine İlet",
            "hata sepeti": "BN-Hata Sepetine İlet",
            "iyileştirme": "BN-İyileştirme Sepetine İlet",
            "analiz": "BN-Analiz Sepetine İlet",
            "test": "BN-Test Sepetine İlet",
        }
        for b_kw, b_name in basket_keywords.items():
            if b_kw in p_lower:
                filtered_df = filtered_df[filtered_df["op_basket"].str.contains(b_name, case=False, na=False)]
                applied_filters.append(f"Sepet: {b_name}")
                break

        # Check if user is asking for a breakdown between teams/L2 forwarding
        is_breakdown_query = any(w in p_lower for w in (
            "kaçı l2", "kaç tanesi l2", "kaçı aktarılmış", "kaçı iletilmiş",
            "l2'ye aktarılan", "l2 ye aktarılan", "l1 vs l2", "ekip dağılımı", "l1 l2"
        ))

        # 3.4 OpenProject forwarded check
        if not is_breakdown_query and any(w in p_lower for w in ("openproject", "op'ye", "iletilen", "yönlendirilen", "aktarılan")):
            if "is_op_forwarded" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["is_op_forwarded"]]
                applied_filters.append("OpenProject'e İletilenler")

        # 3.5 Team Segment check
        if not is_breakdown_query:
            if any(w in p_lower for w in ("sistem ekibine", "sistem ekibi", "sistem & vt", "sadece l2", "l2 çağrı")) or segment in ("system", "sistem"):
                filtered_df = filtered_df[filtered_df["team_segment"] == "Sistem"]
                applied_filters.append("Ekip: Sistem (L2)")
            elif any(w in p_lower for w in ("servis masası", "servis masasi", "sadece l1", "l1 çağrı")) or segment in ("service_desk", "servis_masasi"):
                filtered_df = filtered_df[filtered_df["team_segment"] == "Servis Masası"]
                applied_filters.append("Ekip: Servis Masası (L1)")

        # 3.6 Technician Detection
        matched_tech = None
        unique_techs = work_df["technician"].dropna().unique()
        for tech in unique_techs:
            tech_clean = str(tech).lower().strip()
            if len(tech_clean) >= 4 and tech_clean in p_lower:
                matched_tech = tech
                break
        if matched_tech:
            filtered_df = filtered_df[filtered_df["technician"] == matched_tech]
            applied_filters.append(f"Teknisyen: {matched_tech}")

        # 4. Determine Grouping / Target Dimension for Chart
        matched_count = len(filtered_df)
        group_col = "op_basket"
        group_label = "Hedef Sepet"
        chart_type = "doughnut"

        if is_breakdown_query:
            group_col = "team_segment"
            group_label = "Operasyonel Ekip"
            chart_type = "doughnut"
        elif matched_institution:
            # If a specific institution is filtered, breakdown by basket or task type or root cause
            if any(w in p_lower for w in ("sepet", "nereye")):
                group_col = "op_basket"
                group_label = "Hedef Sepet"
                chart_type = "doughnut"
            elif any(w in p_lower for w in ("görev", "task", "konu")):
                group_col = "op_task_type"
                group_label = "Görev Tipi"
                chart_type = "bar"
            else:
                group_col = "root_cause"
                group_label = "Kök Neden"
                chart_type = "doughnut"
        elif matched_tech:
            if any(w in p_lower for w in ("sepet", "nereye")):
                group_col = "op_basket"
                group_label = "Hedef Sepet"
                chart_type = "doughnut"
            elif any(w in p_lower for w in ("kurum", "hangi kurum")):
                group_col = "institution"
                group_label = "Kurum"
                chart_type = "bar"
            else:
                group_col = "root_cause"
                group_label = "Talep Türü"
                chart_type = "doughnut"
        else:
            # Across multiple entities
            if any(w in p_lower for w in ("kurum", "bakanlık", "en çok")):
                group_col = "institution"
                group_label = "Kurum"
                chart_type = "bar"
            elif any(w in p_lower for w in ("teknisyen", "personel", "uzman", "atanan")):
                group_col = "technician"
                group_label = "Teknisyen"
                chart_type = "bar"
            elif any(w in p_lower for w in ("sepet", "dağılım")):
                group_col = "op_basket"
                group_label = "Hedef Sepet"
                chart_type = "doughnut"
            elif any(w in p_lower for w in ("tip", "kök neden", "arıza")):
                group_col = "root_cause"
                group_label = "Talep Türü"
                chart_type = "doughnut"

        # 5. Exact Pandas Aggregation
        series_clean = filtered_df[group_col].replace({"": "Belirtilmemiş", "nan": "Belirtilmemiş"}).fillna("Belirtilmemiş")
        counts_series = series_clean.value_counts().head(8)
        counts = counts_series.to_dict()

        labels = list(counts.keys())
        data_values = [int(v) for v in counts.values()]

        # Compute percentages
        pcts = {k: round((v / matched_count) * 100, 1) if matched_count > 0 else 0.0 for k, v in counts.items()}

        # 6. Build KPI Summary Cards
        resolved_count = int(filtered_df["is_resolved"].sum()) if not filtered_df.empty else 0
        res_rate = round((resolved_count / matched_count) * 100, 1) if matched_count > 0 else 0.0

        summary_cards = [
            {"label": "Eşleşen Çağrı", "value": f"{matched_count} adet", "color": "blue"},
            {"label": "Çözülen Çağrı", "value": f"{resolved_count} adet (%{res_rate})", "color": "emerald"},
        ]

        if counts:
            top_key, top_val = next(iter(counts.items()))
            top_label = top_key if len(top_key) <= 22 else top_key[:20] + "..."
            summary_cards.append({
                "label": f"Baskın {group_label}",
                "value": f"{top_label} ({top_val})",
                "color": "purple"
            })

        # 7. Build Dynamic Table
        table_rows = []
        for k, v in counts.items():
            table_rows.append([k, int(v), f"%{pcts[k]}"])

        table_data = {
            "has_table": bool(table_rows),
            "headers": [group_label, "Çağrı Sayısı", "Oran"],
            "rows": table_rows
        }

        # 8. Chart Palette & Configuration
        palette = [
            "#2563eb", "#3b82f6", "#059669", "#10b981", "#d97706",
            "#f59e0b", "#7c3aed", "#8b5cf6", "#e11d48", "#64748b"
        ]

        chart_config = {
            "has_chart": bool(labels),
            "type": chart_type,
            "title": f"{', '.join(applied_filters) if applied_filters else 'Operasyon'} - {group_label} Dağılımı",
            "labels": labels,
            "data": data_values,
            "colors": palette[:len(labels)],
            "group_label": group_label,
        }

        # 9. Formulate Narrative Explanation
        explanation = self._build_narrative(prompt, matched_count, applied_filters, group_label, counts, pcts, resolved_count, res_rate)

        # 10. Optional Qwen Synthesis (if enabled and reachable)
        if self.qwen.enabled:
            try:
                llm_narrative = await self._synthesize_with_qwen(prompt, matched_count, applied_filters, group_label, counts)
                if llm_narrative:
                    explanation = llm_narrative
            except Exception as e:
                logger.warning(f"Qwen ad-hoc narrative synthesis skipped: {e}")

        return {
            "is_applicable": True,
            "query_interpretation": ", ".join(applied_filters) if applied_filters else "Tüm operasyonel çağrı verisi",
            "answer_text": explanation,
            "summary_cards": summary_cards,
            "chart": chart_config,
            "table": table_data,
            "matched_count": matched_count,
        }

    def _build_narrative(
        self,
        prompt: str,
        total: int,
        filters: List[str],
        group_label: str,
        counts: Dict[str, int],
        pcts: Dict[str, float],
        resolved_count: int = 0,
        res_rate: float = 0.0
    ) -> str:
        """
        Fast, zero-latency deterministic natural language narrative generator.
        """
        if total == 0:
            filter_str = f" ({', '.join(filters)})" if filters else ""
            return f"Belirtilen kriterlere uygun{filter_str} herhangi bir çağrı kaydı bulunamamıştır."

        filter_desc = f"**{', '.join(filters)}** kapsamında " if filters else ""
        top_items = list(counts.items())[:3]
        top_str_list = [f"**{k}** ({v} adet, %{pcts.get(k, 0)})" for k, v in top_items]
        top_str = ", ".join(top_str_list)

        res_info = f"Bu çağrıların **{resolved_count} adedi (%{res_rate})** başarıyla çözümlenmiştir. " if resolved_count > 0 else ""

        narrative = (
            f"Sorgunuz doğrultusunda {filter_desc}toplam **{total} adet** çağrı kaydı tespit edilmiştir. "
            f"{res_info}"
            f"**{group_label}** bazında yapılan incelemede dağılım: {top_str} şeklindedir. "
            f"Aşağıdaki grafik ve tabloda detaylı kırılımlar gösterilmektedir."
        )
        return narrative

    async def _synthesize_with_qwen(
        self,
        prompt: str,
        total: int,
        filters: List[str],
        group_label: str,
        counts: Dict[str, int]
    ) -> Optional[str]:
        """
        Leverages Qwen 3.5 to formulate an eloquent, corporate Turkish summary of the exact computed data.
        """
        sys_prompt = (
            "Sen TÜRKSAT Bilişim Hizmetleri METRİKA Operasyonel Raporlama Platformu'nun Yapay Zeka Analistisin. "
            "Kullanıcının sorusuna verilen gerçek Pandas istatistiklerini özetleyen, 2-3 cümlelik, profesyonel, "
            "net ve Türkçe bir analitik özet yaz. Kesinlikle uydurma sayı verme, sadece verilen gerçek rakamları yorumla."
        )
        user_prompt = (
            f"Kullanıcı Sorusu: {prompt}\n"
            f"Filtreler: {', '.join(filters)}\n"
            f"Toplam Eşleşen Çağrı: {total}\n"
            f"{group_label} Dağılımı: {counts}\n\n"
            f"Lütfen kullanıcıya doğrudan, kibar ve veri odaklı bir yönetici yanıtı ver."
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        resp = await self.qwen.chat_completion(messages, temperature=0.1, max_tokens=250)
        return resp.strip() if resp else None
