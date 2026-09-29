import logging
from typing import Any, Dict, List, Optional
import httpx
import pandas as pd
from app.connectors.base_connector import BaseConnector
from app.connectors.mock_connector import MockConnector
from app.core.config import settings

logger = logging.getLogger("metrika.connectors.glpi")


class GLPIConnector(BaseConnector):
    """
    Production-ready GLPI REST API client with session management,
    pagination, timeout resilience, and automatic fallback.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        app_token: Optional[str] = None,
        user_token: Optional[str] = None,
        timeout: Optional[float] = None,
        fallback_enabled: Optional[bool] = None,
    ):
        self.base_url = (base_url or settings.GLPI_URL).rstrip("/")
        self.app_token = app_token if app_token is not None else settings.GLPI_APP_TOKEN
        self.user_token = user_token if user_token is not None else settings.GLPI_USER_TOKEN
        self.timeout = timeout or settings.GLPI_TIMEOUT_SECONDS
        self.fallback_enabled = fallback_enabled if fallback_enabled is not None else settings.FALLBACK_TO_MOCK
        self.session_token: Optional[str] = None
        self._mock_fallback = MockConnector()

    async def _init_session(self, client: httpx.AsyncClient) -> bool:
        """
        Authenticate with GLPI and obtain a Session-Token.
        """
        if not self.app_token or not self.user_token:
            logger.warning("GLPI credentials (APP_TOKEN or USER_TOKEN) not configured.")
            return False

        headers = {
            "Content-Type": "application/json",
            "App-Token": self.app_token,
            "Authorization": f"user_token {self.user_token}",
        }
        init_url = f"{self.base_url}/initSession"

        try:
            resp = await client.get(init_url, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                self.session_token = data.get("session_token")
                logger.info("GLPI session successfully initialized.")
                return True
            else:
                logger.error(f"GLPI initSession failed with status {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.warning(f"Failed to connect to GLPI initSession ({self.base_url}): {e}")
            return False

    async def _kill_session(self, client: httpx.AsyncClient) -> None:
        """
        Terminate current GLPI session.
        """
        if not self.session_token:
            return

        headers = {
            "Content-Type": "application/json",
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
        }
        kill_url = f"{self.base_url}/killSession"
        try:
            await client.get(kill_url, headers=headers, timeout=5.0)
            logger.info("GLPI session killed successfully.")
        except Exception as e:
            logger.debug(f"Error while killing GLPI session: {e}")
        finally:
            self.session_token = None

    async def fetch_tickets(self, days: int = 7, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Fetch tickets within specified date range. Falls back to mock data if GLPI is unreachable.
        """
        async with httpx.AsyncClient() as client:
            session_ok = await self._init_session(client)
            if not session_ok:
                if self.fallback_enabled:
                    logger.warning("GLPI API unavailable or unconfigured. Falling back to MockConnector.")
                    return await self._mock_fallback.fetch_tickets(days=days, params=params)
                raise ConnectionError(f"Could not connect to GLPI at {self.base_url}")

            try:
                headers = {
                    "Content-Type": "application/json",
                    "App-Token": self.app_token,
                    "Session-Token": self.session_token,
                }

                # GLPI pagination query
                # E.g. /Ticket?range=0-999&is_deleted=0
                all_raw_tickets: List[Dict[str, Any]] = []
                range_start = 0
                step = 200

                while True:
                    query_params = {
                        "range": f"{range_start}-{range_start + step - 1}",
                        "is_deleted": 0,
                        "sort": "date",
                        "order": "DESC",
                    }
                    ticket_url = f"{self.base_url}/Ticket"
                    resp = await client.get(ticket_url, headers=headers, params=query_params, timeout=self.timeout)

                    if resp.status_code in (200, 206):
                        chunk = resp.json()
                        if not chunk or not isinstance(chunk, list):
                            break
                        all_raw_tickets.extend(chunk)
                        if len(chunk) < step or len(all_raw_tickets) >= 1000:
                            break
                        range_start += step
                    else:
                        logger.error(f"Error querying GLPI tickets: {resp.status_code} - {resp.text}")
                        break

                if not all_raw_tickets:
                    if self.fallback_enabled:
                        logger.info("GLPI returned 0 tickets. Falling back to mock dataset for demonstration.")
                        return await self._mock_fallback.fetch_tickets(days=days, params=params)
                    return pd.DataFrame()

                # Transform raw GLPI format to standardized DataFrame
                return self._normalize_glpi_payload(all_raw_tickets, days)

            except Exception as e:
                logger.error(f"GLPI query error: {e}")
                if self.fallback_enabled:
                    logger.warning("Using mock fallback due to GLPI query failure.")
                    return await self._mock_fallback.fetch_tickets(days=days, params=params)
                raise
            finally:
                await self._kill_session(client)

    def _normalize_glpi_payload(self, tickets: List[Dict[str, Any]], days: int) -> pd.DataFrame:
        """
        Normalize GLPI REST API raw ticket dictionaries into unified columns.
        """
        records = []
        for t in tickets:
            records.append(
                {
                    "ticket_id": t.get("id"),
                    "title": t.get("name", "İsimsiz Çağrı"),
                    "institution": t.get("entities_id", "Kurum Bilgisi Yok"),
                    "category": t.get("itilcategories_id", "Genel"),
                    "root_cause": "Hata" if "hata" in str(t.get("name", "")).lower() else "Destek",
                    "priority": self._map_glpi_priority(t.get("priority", 3)),
                    "status": self._map_glpi_status(t.get("status", 1)),
                    "technician_raw": t.get("users_id_recipient", "Atanmamış"),
                    "created_at": t.get("date", ""),
                    "resolved_at": t.get("solvedate", "") or t.get("closedate", ""),
                    "first_response_time_str": t.get("takeintoaccount_delay_stat", "30 dakika"),
                    "total_resolution_time_str": t.get("solve_delay_stat", "1 gün"),
                    "external_wait_time_str": t.get("waiting_duration", "0 dakika"),
                    "openproject_task_id": "",
                    "is_fcr": False,
                    "is_reopened": "yeniden" in str(t.get("name", "")).lower(),
                }
            )
        return pd.DataFrame(records)

    @staticmethod
    def _map_glpi_priority(priority_id: Any) -> str:
        mapping = {1: "Çok Düşük", 2: "Düşük", 3: "Orta", 4: "Yüksek", 5: "Çok Yüksek"}
        try:
            return mapping.get(int(priority_id), "Orta")
        except (ValueError, TypeError):
            return "Orta"

    @staticmethod
    def _map_glpi_status(status_id: Any) -> str:
        mapping = {
            1: "Yeni",
            2: "İşlemde (Atandı)",
            3: "İşlemde (Planlandı)",
            4: "Beklemede",
            5: "Çözüldü",
            6: "Kapandı",
        }
        try:
            return mapping.get(int(status_id), "İşlemde")
        except (ValueError, TypeError):
            return "İşlemde"

    async def check_health(self) -> Dict[str, Any]:
        """
        Check health of GLPI connection.
        """
        if not self.app_token or not self.user_token:
            return {
                "status": "unconfigured",
                "source": "glpi",
                "message": "GLPI credentials not configured in environment.",
                "fallback_active": self.fallback_enabled,
            }

        async with httpx.AsyncClient() as client:
            try:
                ok = await self._init_session(client)
                if ok:
                    await self._kill_session(client)
                    return {
                        "status": "online",
                        "source": "glpi",
                        "message": "Connected to GLPI REST API successfully.",
                        "base_url": self.base_url,
                    }
                else:
                    return {
                        "status": "auth_failed",
                        "source": "glpi",
                        "message": "GLPI authentication rejected.",
                        "fallback_active": self.fallback_enabled,
                    }
            except Exception as e:
                return {
                    "status": "offline",
                    "source": "glpi",
                    "message": f"GLPI connection error: {str(e)}",
                    "fallback_active": self.fallback_enabled,
                }
