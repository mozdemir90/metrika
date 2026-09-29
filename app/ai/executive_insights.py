import logging
from typing import Any, Dict, List, Optional
from app.ai.qwen_client import QwenClient
from app.core.config import settings

logger = logging.getLogger("metrika.ai")


class ExecutiveInsightsEngine:
    """
    Qwen LLM & Heuristic Executive Summary Engine.
    jiraClassification_prod projesinde kullanılan TÜRKSAT PAAS Qwen LLM servisiyle
    entegre çalışarak kurum yöneticilerine yapay zeka destekli stratejik özetler sunar.
    Bağlantı kesilmesi veya zaman aşımı durumunda yerel kural motoruna (heuristic) yumuşak geçiş yapar.
    """

    def __init__(self, qwen_client: Optional[QwenClient] = None):
        self.qwen = qwen_client or QwenClient()

    async def generate_summary(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates executive summary. Queries Qwen LLM if available;
        gracefully falls back to the heuristic engine if unavailable.
        """
        # 1. Try Qwen LLM
        if self.qwen.enabled:
            try:
                qwen_report = await self.qwen.generate_executive_report(metrics)
                if qwen_report and qwen_report.get("observations"):
                    # Enrich with local top performers for completeness
                    techs = metrics.get("technicians", [])
                    top_performers = [
                        t["technician"] for t in techs if t.get("resolved_count", 0) >= 5
                    ][:3]
                    qwen_report["top_performers"] = top_performers
                    qwen_report["is_llm_generated"] = True
                    return qwen_report
            except Exception as e:
                logger.warning(f"Qwen LLM call encountered an issue: {e}. Falling back to heuristic engine.")

        # 2. Heuristic fallback
        heuristic_res = self.generate_heuristic_summary(metrics)
        heuristic_res["is_llm_generated"] = False
        return heuristic_res

    def generate_heuristic_summary(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        summary = metrics.get("summary", {})
        top_inst = metrics.get("top_institutions", [])
        techs = metrics.get("technicians", [])

        total = summary.get("total_tickets", 0)
        resolved = summary.get("resolved_tickets", 0)
        open_count = summary.get("open_tickets", 0)
        res_rate = summary.get("resolution_rate", 0.0)
        fcr = summary.get("fcr_rate", 0.0)
        reopen = summary.get("reopen_rate", 0.0)
        avg_mtta = summary.get("avg_mtta_minutes", 0.0)
        avg_net_mttr = summary.get("avg_net_mttr_hours", 0.0)
        avg_ext_wait = summary.get("avg_external_wait_hours", 0.0)

        # 1. Operational Health Status
        if reopen <= 5.0 and avg_mtta <= 60.0:
            health_status = "Operasyonel Akış Sağlıklı ve Dengeli"
            health_color = "green"
        elif reopen <= 10.0:
            health_status = "Standart Operasyon (Normal Seyir)"
            health_color = "yellow"
        else:
            health_status = "Kalite / Reopen Uyarısı (Müdahale Gerekebilir)"
            health_color = "red"

        # 2. Key Observations
        observations: List[str] = [
            f"İncelenen dönemde toplam {total} adet çağrı işlenmiş olup {resolved} adedi (%{res_rate}) sonuçlandırılmış, {open_count} çağrı aktif durumdadır.",
            f"Ortalama ilk müdahale süresi (MTTA) {avg_mtta} dakika, personelin fiili net çalışma süresi ortalama {avg_net_mttr} saattir.",
        ]

        if avg_ext_wait > 3.0:
            observations.append(
                f"Kurumlardan bilgi/onay bekleme süresi ortalama {avg_ext_wait} saat olarak ölçülmüştür. Dış bekleme süreleri net efordan düşülerek personel performansı hakkaniyetle hesaplanmıştır."
            )

        if fcr >= 25.0:
            observations.append(
                f"İlk Temasta Çözüm (FCR) oranı %{fcr} seviyesindedir; çağrılar üst ekibe veya OpenProject'e aktarılmadan doğrudan birinci hatta sonuçlandırılmıştır."
            )
        else:
            observations.append(
                f"L1 doğrudan kapatma (FCR) oranı %{fcr} seviyesindedir; 2. seviyeye eskalasyon oranını azaltmak için L1 bilgi tabanının güçlendirilmesi değerlendirilebilir."
            )

        # 3. Risk and Alerts
        alerts: List[str] = []
        if reopen > 7.0:
            alerts.append(f"Yeniden açılma oranı (%{reopen}) dikkat çekicidir. Kapatılan çağrıların kullanıcı teyidi alınarak kapatıldığından emin olunmalıdır.")

        high_bug_inst = [i["institution"] for i in top_inst if i.get("bug_percentage", 0) > 40.0]
        if high_bug_inst:
            alerts.append(f"Şu kurumlarda hata/arıza oranı %40'ın üzerindedir: {', '.join(high_bug_inst[:3])}. Bu kurumların altyapı ve e-imza konfigürasyonları taranmalıdır.")

        # 4. Actionable Recommendations (Immediate vs Strategic)
        immediate_actions: List[str] = [
            "Dış bekleme süresi uzayan çağrılar için kurum irtibat kişilerine otomatik hatırlatma e-postaları tetiklenmesi.",
            "Kritik çağrılarda ilk müdahale süresini minimumda tutmak için mesai başlangıç saatlerinde nöbetçi teknisyen atanması.",
        ]
        if high_bug_inst:
            immediate_actions.append(f"Hata oranı yüksek çıkan kurumlara ({', '.join(high_bug_inst[:2])}) acil teknik inceleme başlatılması.")

        strategic_actions: List[str] = [
            "İlk Temasta Çözüm (FCR) oranını yükseltmek adına L1 servis masası için güncel çağrı çözüm rehberleri hazırlanması.",
            "Kurum bekleme sürelerinin dondurulmasını kurumsal SLA protokollerine resmi olarak bağlayacak süreç tanımlarının yapılması.",
        ]

        recommendations: List[str] = immediate_actions + strategic_actions

        # Top Performing Technicians
        top_performers = [
            t["technician"] for t in techs if t.get("resolved_count", 0) >= 5
        ][:3]

        return {
            "source": "heuristic_expert_rules",
            "health_status": health_status,
            "health_color": health_color,
            "executive_summary": (
                f"Sistem Masası operasyonunda işlenen {total} çağrının %{res_rate} oranı başarıyla çözüme kavuşturulmuştur. "
                f"Ortalama ilk yanıt süresi {avg_mtta} dk ve ortalama net çözüm süresi {avg_net_mttr} saattir. "
                f"Dış kurumsal bekleme sürelerinin ayrıştırılması sayesinde ekip eforu şeffaf olarak yansıtılmaktadır."
            ),
            "observations": observations,
            "alerts": alerts,
            "immediate_actions": immediate_actions,
            "strategic_actions": strategic_actions,
            "recommendations": recommendations,
            "top_performers": top_performers,
        }
