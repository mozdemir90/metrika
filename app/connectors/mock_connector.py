import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pandas as pd
from app.connectors.base_connector import BaseConnector


class MockConnector(BaseConnector):
    """
    Mock / Fallback connector providing realistic Belgenet GLPI service desk data.
    Useful for local testing, offline development, demos, and graceful degradation
    when the real GLPI API is unreachable.
    """

    TECHNICIANS = [
        "glpi \nAhmet Yılmaz",
        "glpi \n  Mehmet Kaya  ",
        "Ayşe Demir",
        "glpi \nFatma Çelik\r\n",
        "Canan Öztürk",
        "glpi\nBurak Şahin",
        "Emre Koç",
        "glpi \n  Zeynep Yıldız",
    ]

    INSTITUTIONS = [
        "Adalet Bakanlığı",
        "Milli Eğitim Bakanlığı",
        "Sağlık Bakanlığı",
        "İçişleri Bakanlığı",
        "Tarım ve Orman Bakanlığı",
        "Hazine ve Maliye Bakanlığı",
        "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı",
        "Ulaştırma ve Altyapı Bakanlığı",
        "Sanayi ve Teknoloji Bakanlığı",
        "Gençlik ve Spor Bakanlığı",
        "SGK Başkanlığı",
        "Gelir İdaresi Başkanlığı",
    ]

    CATEGORIES = [
        ("E-İmza / Mobil İmza Sorunu", "Hata"),
        ("Belge Akışı / Onay Süreci", "Destek"),
        ("Kullanıcı Yetkilendirme Talebi", "Destek"),
        ("Entegrasyon / Servis Kesintisi", "Hata"),
        ("Şablon / Form Düzenleme", "Destek"),
        ("Veritabanı Senkronizasyon Hatası", "Hata"),
        ("Kep / DYS İletişim Hatası", "Hata"),
        ("Yeni Birim / Rol Açılışı", "Destek"),
        ("EBYS İstemci Kurulum Yardımı", "Destek"),
        ("PDF / TIFF Görüntüleme Hatası", "Hata"),
    ]

    PRIORITIES = ["Düşük", "Orta", "Yüksek", "Çok Yüksek"]
    STATUSES = ["Çözüldü", "Kapandı", "İşlemde", "Beklemede"]

    def __init__(self, seed: int = 42):
        self.seed = seed

    def _generate_synthetic_data(self, total_count: int = 240) -> pd.DataFrame:
        random.seed(self.seed)
        now = datetime.now()
        records: List[Dict[str, Any]] = []

        for i in range(1, total_count + 1):
            # Ticket age within last 35 days
            created_days_ago = random.uniform(0.1, 34.5)
            created_at = now - timedelta(days=created_days_ago)

            priority = random.choices(
                self.PRIORITIES, weights=[0.20, 0.50, 0.22, 0.08], k=1
            )[0]
            status = random.choices(
                self.STATUSES, weights=[0.60, 0.28, 0.08, 0.04], k=1
            )[0]
            category_name, root_cause = random.choice(self.CATEGORIES)
            institution = random.choice(self.INSTITUTIONS)
            technician_raw = random.choice(self.TECHNICIANS)

            # First Response Time (MTTA)
            # High/Very High should mostly be <= 30 min, others <= 60 min
            if priority in ["Yüksek", "Çok Yüksek"]:
                mtta_minutes = random.choice([12, 18, 24, 28, 32, 45, 15, 20])
            else:
                mtta_minutes = random.choice([25, 35, 45, 55, 65, 80, 40, 50])

            # Duration representation string for MTTA
            if mtta_minutes < 60:
                mtta_str = f"{mtta_minutes} dakika"
            else:
                h = mtta_minutes // 60
                m = mtta_minutes % 60
                mtta_str = f"{h} saat {m} dakika"

            # Resolution Times
            # Total resolution: ranges from 1 hour to 4 days
            total_hours = round(random.uniform(2.5, 75.0), 1)
            # External waiting duration (institution wait)
            # ~40% tickets have external waiting time
            has_ext_wait = random.random() < 0.45
            if has_ext_wait:
                ext_hours = round(random.uniform(1.0, min(total_hours * 0.7, 30.0)), 1)
            else:
                ext_hours = 0.0

            # Formats like "X gün Y saat Z dakika"
            tot_d = int(total_hours // 24)
            tot_rem_h = int(total_hours % 24)
            tot_m = int((total_hours - int(total_hours)) * 60)
            parts = []
            if tot_d > 0:
                parts.append(f"{tot_d} gün")
            if tot_rem_h > 0:
                parts.append(f"{tot_rem_h} saat")
            if tot_m > 0 or not parts:
                parts.append(f"{tot_m} dakika")
            total_duration_str = " ".join(parts)

            ext_d = int(ext_hours // 24)
            ext_rem_h = int(ext_hours % 24)
            ext_m = int((ext_hours - int(ext_hours)) * 60)
            ext_parts = []
            if ext_d > 0:
                ext_parts.append(f"{ext_d} gün")
            if ext_rem_h > 0:
                ext_parts.append(f"{ext_rem_h} saat")
            if ext_m > 0 or not ext_parts:
                ext_parts.append(f"{ext_m} dakika")
            ext_wait_str = " ".join(ext_parts) if ext_hours > 0 else "0 dakika"

            # Closed date
            if status in ["Çözüldü", "Kapandı"]:
                resolved_at = created_at + timedelta(hours=total_hours)
                if resolved_at > now:
                    resolved_at = now
            else:
                resolved_at = None

            # FCR: Resolved at tier-1 service desk without OpenProject escalation
            # 75% FCR rate
            escalated_to_openproject = random.random() < 0.24
            openproject_task_id = f"OP-{1000 + i}" if escalated_to_openproject else ""
            is_fcr = not escalated_to_openproject and status in ["Çözüldü", "Kapandı"]

            # Reopened Quality Metric (~7% reopen rate)
            is_reopened = random.random() < 0.07

            records.append(
                {
                    "ticket_id": 10000 + i,
                    "title": f"{institution} - {category_name} #{i}",
                    "institution": institution,
                    "category": category_name,
                    "root_cause": root_cause,
                    "priority": priority,
                    "status": status,
                    "technician_raw": technician_raw,
                    "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "resolved_at": resolved_at.strftime("%Y-%m-%d %H:%M:%S") if resolved_at else "",
                    "first_response_time_str": mtta_str,
                    "first_response_minutes": mtta_minutes,
                    "total_resolution_time_str": total_duration_str,
                    "total_resolution_hours": total_hours,
                    "external_wait_time_str": ext_wait_str,
                    "external_wait_hours": ext_hours,
                    "openproject_task_id": openproject_task_id,
                    "is_fcr": is_fcr,
                    "is_reopened": is_reopened,
                }
            )

        df = pd.DataFrame(records)
        return df

    async def fetch_tickets(self, days: int = 7, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        df = self._generate_synthetic_data(total_count=300)
        df["created_dt"] = pd.to_datetime(df["created_at"])
        cutoff_date = datetime.now() - timedelta(days=days)
        filtered_df = df[df["created_dt"] >= cutoff_date].copy()
        filtered_df.drop(columns=["created_dt"], inplace=True)
        return filtered_df

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "online",
            "source": "mock",
            "message": "Mock GLPI data source operational.",
            "latency_ms": 1.2,
        }
