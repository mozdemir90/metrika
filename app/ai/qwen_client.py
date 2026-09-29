import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger("metrika.ai.qwen")


class QwenClient:
    """
    TÜRKSAT PAAS Qwen LLM İstemcisi.
    jiraClassification_prod projesinde kullanılan Hakem AI (qwen35-122b-a10b-fp8)
    altyapısıyla birebir aynı endpoint, yetkilendirme ve model yapısını kullanır.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_url = api_url or settings.HAKEM_API_URL
        self.api_key = api_key or settings.HAKEM_API_KEY
        self.api_model = api_model or settings.HAKEM_API_MODEL
        self.timeout = timeout or settings.QWEN_TIMEOUT_SECONDS
        self.enabled = settings.ENABLE_QWEN_LLM and bool(self.api_url and self.api_key)
        self.last_error: Optional[str] = None

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """
        Extracts valid JSON string from LLM responses that might contain
        markdown code blocks, reasoning tags, or conversational padding.
        """
        if not text:
            return None
        text = text.strip()

        # 1. Match ```json ... ``` or ``` ... ```
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # 2. Match outermost { ... }
        brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace_match:
            return brace_match.group(1).strip()

        return text

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Sends chat completion request to TÜRKSAT PAAS Qwen endpoint.
        """
        if not self.enabled:
            self.last_error = "Qwen LLM client is disabled or missing credentials."
            logger.info(self.last_error)
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.api_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        t_start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.api_url, headers=headers, json=payload)
                duration_ms = (time.perf_counter() - t_start) * 1000

                if resp.status_code == 200:
                    data = resp.json()
                    choice = data.get("choices", [{}])[0]
                    msg = choice.get("message", {})
                    content = msg.get("content")

                    # Sanitize content: strip <think>...</think> and internal Thinking Process
                    if content:
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
                        if "Thinking Process:" in content:
                            parts = re.split(r"\n\n(?=[A-ZÇĞİÖŞÜ])", content, maxsplit=1)
                            if len(parts) > 1 and not parts[1].strip().startswith("Thinking Process:"):
                                content = parts[1]
                            else:
                                content = None
                    else:
                        # Never expose raw internal reasoning CoT chain to users
                        logger.info("Qwen content was empty or truncated before completion.")
                        content = None

                    logger.info(f"Qwen API responded in {duration_ms:.1f} ms (Model: {self.api_model})")
                    self.last_error = None
                    return content.strip() if content else None
                else:
                    self.last_error = f"HTTP {resp.status_code}: {resp.text}"
                    logger.error(f"Qwen API error {self.last_error}")
                    return None
        except Exception as e:
            duration_ms = (time.perf_counter() - t_start) * 1000
            self.last_error = f"{type(e).__name__}: {e}"
            logger.warning(f"Qwen API call failed after {duration_ms:.1f} ms: {self.last_error}")
            return None

    async def check_health(self) -> Dict[str, Any]:
        """
        Performs a quick diagnostic ping to verify Qwen API connectivity and latency.
        """
        if not self.enabled:
            return {
                "status": "disabled",
                "online": False,
                "model": self.api_model,
                "url": self.api_url,
                "error": "API Key or URL not configured.",
            }

        t_start = time.perf_counter()
        try:
            res = await self.chat_completion(
                messages=[
                    {"role": "system", "content": "Sen bir test asistanısın."},
                    {"role": "user", "content": "PİNG. Sadece 'PONG' yaz."},
                ],
                max_tokens=None,
            )
            duration_ms = round((time.perf_counter() - t_start) * 1000, 1)
            if res:
                return {
                    "status": "online",
                    "online": True,
                    "model": self.api_model,
                    "url": self.api_url,
                    "latency_ms": duration_ms,
                    "response_preview": res[:50],
                }
            return {
                "status": "offline",
                "online": False,
                "model": self.api_model,
                "url": self.api_url,
                "latency_ms": duration_ms,
                "error": self.last_error or "API returned empty response.",
            }
        except Exception as e:
            return {
                "status": "error",
                "model": self.api_model,
                "url": self.api_url,
                "error": str(e),
            }

    async def generate_executive_report(self, metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generates structured executive-level insights, strategic narrative, and prioritized
        operational action plan using Qwen 3.5 (122B).
        """
        summary = metrics.get("summary", {})
        top_inst = metrics.get("top_institutions", [])[:6]
        techs = metrics.get("technicians", [])[:6]
        team_breakdown = metrics.get("team_breakdown", {})
        active_seg = metrics.get("active_segment", "all")

        seg_name = "Tüm Operasyon (Konsolide)"
        if active_seg == "service_desk":
            seg_name = "Servis Masası (L1 / BNSM)"
        elif active_seg == "system_ops":
            seg_name = "Sistem Ekibi & VT / Deploy (L2 / BN)"

        system_prompt = (
            "Sen TÜRKSAT Bilişim ve Belgenet Operasyonları için çalışan Üst Düzey Yönetim ve Süreç Danışmanısın. "
            "Görevin: Sana sunulan operasyonel verileri derinlemesine analiz edip kurum yöneticileri, genel müdürlük "
            "ve daire başkanları için stratejik, hakkaniyetli, yapıcı ve doğrudan uygulanabilir bir Türkçe yönetici özeti "
            "ve önceliklendirilmiş aksiyon planı hazırlamaktır.\n\n"
            "Önemli Prensipler:\n"
            "1. SLA hedefleri sözleşme ve kuruma göre dinamik değiştiği için sabit yapay SLA varsayımları yerine; "
            "Fiili Çözüm Oranı, İlk Yanıt Hızı, Net Çalışma Eforu ve Kurum/Dış Bekleme sürelerine odaklan.\n"
            "2. Kurum bekleme süreleri personelin kontrolü dışındaki dondurulmuş sürelerdir; değerlendirmelerini hakkaniyetli yap.\n"
            "3. Aksiyon planında genel geçer tavsiyeler yerine, verideki darboğazları (yüksek hata üreten kurumlar, "
            "düşük doğrudan çözüm oranı, uzayan bekleme süreleri veya teknisyen yük dengesizlikleri) hedef alan somut adımlar üret.\n"
            "4. Yanıtını SADECE ve SADECE geçerli bir JSON objesi olarak dön. Markdown backtick (```) veya JSON dışı metin ekleme.\n\n"
            "JSON Formatı:\n"
            "{\n"
            '  "health_status": "Operasyonel Akış Sağlıklı ve Dengeli",\n'
            '  "health_color": "green",\n'
            '  "executive_summary": "Kurum üst yönetimi için 2 paragraflık stratejik durum ve performans değerlendirmesi...",\n'
            '  "observations": [\n'
            '    "Öne çıkan kritik operasyonel bulgu 1",\n'
            '    "Öne çıkan kritik operasyonel bulgu 2",\n'
            '    "Öne çıkan kritik operasyonel bulgu 3"\n'
            '  ],\n'
            '  "alerts": [\n'
            '    "Tespit edilen darboğaz veya potansiyel risk 1",\n'
            '    "Tespit edilen darboğaz veya potansiyel risk 2"\n'
            '  ],\n'
            '  "immediate_actions": [\n'
            '    "Acil / Bu Hafta Uygulanacak Operasyonel Aksiyon 1",\n'
            '    "Acil / Bu Hafta Uygulanacak Operasyonel Aksiyon 2"\n'
            '  ],\n'
            '  "strategic_actions": [\n'
            '    "Orta / Uzun Vadeli Süreç ve Kalite İyileştirme Aksiyonu 1",\n'
            '    "Orta / Uzun Vadeli Süreç ve Kalite İyileştirme Aksiyonu 2"\n'
            '  ],\n'
            '  "recommendations": [\n'
            '    "Genel Eylem Önerisi 1",\n'
            '    "Genel Eylem Önerisi 2",\n'
            '    "Genel Eylem Önerisi 3"\n'
            '  ]\n'
            "}"
        )

        user_content = (
            f"Kapsam: {seg_name}\n"
            f"Operasyonel Özet:\n"
            f"- Toplam Çağrı: {summary.get('total_tickets', 0)}\n"
            f"- Çözülen Çağrı: {summary.get('resolved_tickets', 0)} (Çözüm Oranı: %{summary.get('resolution_rate', 0.0)})\n"
            f"- Devam Eden / Açık Çağrı: {summary.get('open_tickets', 0)}\n"
            f"- Ortalama İlk Müdahale Süresi: {summary.get('avg_mtta_minutes', 0.0)} dakika\n"
            f"- Ortalama Net Çözüm Süresi: {summary.get('avg_net_mttr_hours', 0.0)} saat\n"
            f"- Ortalama Kurum / Dış Bekleme Süresi: {summary.get('avg_external_wait_hours', 0.0)} saat\n"
            f"- Doğrudan Çözüm (İlk Temasta): {summary.get('fcr_count', 0)} adet (%{summary.get('fcr_rate', 0.0)})\n"
            f"- Yeniden Açılma Oranı: {summary.get('reopen_count', 0)} adet (%{summary.get('reopen_rate', 0.0)})\n"
            f"- Hata Çağrıları: {summary.get('bug_count', 0)}, Destek Çağrıları: {summary.get('support_count', 0)}\n\n"
            f"En Çok Çağrı Açan Kurumlar:\n"
            + "\n".join([f"  • {i.get('institution')}: {i.get('total_count')} çağrı (Hata: %{i.get('bug_percentage', 0)})" for i in top_inst])
            + "\n\nPersonel Dağılımı (İlk 6):\n"
            + "\n".join([f"  • {t.get('technician')}: {t.get('assigned_count')} atanan, {t.get('resolved_count')} çözülen (%{t.get('resolution_rate')}), Net Efor: {t.get('avg_net_resolution_hours')} sa" for t in techs])
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        raw_response = await self.chat_completion(messages, temperature=0.15, max_tokens=None)
        if not raw_response:
            return None

        json_str = self._extract_json(raw_response)
        try:
            parsed = json.loads(json_str)
            imm_actions = parsed.get("immediate_actions", [])
            strat_actions = parsed.get("strategic_actions", [])
            recs = parsed.get("recommendations", [])
            if not recs and (imm_actions or strat_actions):
                recs = imm_actions + strat_actions

            return {
                "source": f"Qwen LLM ({self.api_model})",
                "health_status": parsed.get("health_status", "Operasyonel Değerlendirme Tamamlandı"),
                "health_color": parsed.get("health_color", "blue"),
                "executive_summary": parsed.get("executive_summary", ""),
                "observations": parsed.get("observations", []),
                "alerts": parsed.get("alerts", []),
                "immediate_actions": imm_actions,
                "strategic_actions": strat_actions,
                "recommendations": recs,
            }
        except Exception as e:
            logger.warning(f"Could not parse Qwen JSON response: {e}. Raw content: {raw_response[:200]}")
            return None

    async def generate_action_plan(self, metrics: Dict[str, Any], focus_area: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Generates a focused, actionable operational roadmap for team leaders and directors.
        """
        report = await self.generate_executive_report(metrics)
        if not report:
            return None

        return {
            "source": report.get("source"),
            "health_status": report.get("health_status"),
            "health_color": report.get("health_color"),
            "executive_summary": report.get("executive_summary"),
            "immediate_actions": report.get("immediate_actions", []),
            "strategic_actions": report.get("strategic_actions", []),
            "alerts": report.get("alerts", []),
            "recommendations": report.get("recommendations", []),
        }


_default_client: Optional[QwenClient] = None


def get_qwen_client() -> QwenClient:
    """Returns a shared singleton instance of QwenClient."""
    global _default_client
    if _default_client is None:
        _default_client = QwenClient()
    return _default_client

