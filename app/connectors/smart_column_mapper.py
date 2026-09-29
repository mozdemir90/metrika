import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


class SmartColumnMapper:
    """
    Intelligent Semantic Column Mapping Engine.
    Resolves variations in Excel / CSV column headers across GLPI exports,
    custom Belgenet plugins, Jira, ServiceNow, and manual Excel templates.
    """

    # Canonical columns and their semantic synonym / substring keywords
    CANONICAL_KEYWORDS: Dict[str, List[str]] = {
        "ticket_id": [
            "kimlik", "id", "ticketid", "ticket", "cagrino", "cagri",
            "talepno", "talep", "kayitno", "semanticid", "kayit"
        ],
        "title": [
            "baslik", "konu", "title", "subject", "summary", "tanim", "ozet"
        ],
        "institution": [
            "istektebulunan", "kurum", "kurumadi", "entity", "entitiesid",
            "institution", "organizasyon", "organization", "talepeden", "musteri", "birim"
        ],
        "category": [
            "kategori", "category", "itilcategoriesid", "itilkategori", "hizmet", "servisturu", "sinif"
        ],
        "root_cause": [
            "taleptipi", "kokneden", "gorevtipi", "soruntipi", "issuetype",
            "tur", "tip", "type", "rootcause"
        ],
        "priority": [
            "oncelik", "priority", "aciliyet", "oncelikderecesi", "severity", "onem"
        ],
        "status": [
            "durum", "status", "statu", "state", "asama", "durumadi"
        ],
        "technician_group": [
            "atananlarteknisyengrubu", "teknisyengrubu", "teknisyengrup", "gruputeknisyen"
        ],
        "technician_raw": [
            "atananlarteknisyen", "teknisyen", "technician", "usersidrecipient",
            "atanan", "sorumlu", "assignee", "personel", "uzman", "operator"
        ],
        "created_at": [
            "acilistarihi", "createdat", "date", "olusturulmatarihi", "tarih", "kayittarihi", "creationdate"
        ],
        "resolved_at": [
            "cozumtarihi", "kapanistarihi", "kapaniszamani", "resolvedat",
            "solvedate", "closedate", "bitistarihi", "closedat", "songuncelleme"
        ],
        "first_response_time_str": [
            "elealinmasuresi", "elealinma", "ilkyanitsuresi", "ilkyanit",
            "firstresponsetimestr", "takeintoaccountdelaystat", "mtta", "ilktepki"
        ],
        "total_resolution_time_str": [
            "cozumlenmesuresi", "cozumlenmesure", "cozumlenmezamani",
            "cozulmezamani", "cozulsuresi", "cozumsuresi", "toplamcozumsuresi",
            "toplamcozum", "totalresolutiontimestr", "solvedelaystat", "resolutiontime", "solvetime"
        ],
        "external_wait_time_str": [
            "beklemezamani", "beklemesuresi", "disbekleme", "externalwaittimestr",
            "waitingduration", "kurumbeklemesuresi", "kurumbekleme", "haricibekleme"
        ],
        "op_request_type": [
            "openprojectegondermetaleptipi", "openprojecttaleptipi", "optaleptipi",
            "eklentileropenprojectegondermetaleptipi"
        ],
        "op_task_type": [
            "openprojectegondermegorevtipi", "openprojectgorevtipi", "opgorevtipi",
            "eklentileropenprojectegondermegorevtipi"
        ],
        "op_basket": [
            "budestekkaydiniopenprojecteilet", "openprojecteilet", "openprojectsepet", "opsepet",
            "eklentileropenprojectegondermebudestekkaydiniopenprojecteilet"
        ],
        "openproject_task_id": [
            "openprojecttaskid", "openprojectid", "optask", "opid"
        ],
        "is_fcr": [
            "fcr", "ilktemastacozum", "dogrudancozum", "firstcontactresolution"
        ],
        "is_reopened": [
            "eklentileretiket", "etiket", "tag", "yenidenacildi", "reopened", "reopen", "tekraracildi"
        ],
    }

    @classmethod
    def clean_header(cls, text: Any) -> str:
        """
        Cleans header string by replacing Turkish characters and stripping non-alphanumerics.
        E.g. 'Atananlar - Teknisyen' -> 'atananlarteknisyen'
             'İstekte bulunan - İstekte bulunan' -> 'istektebulunanistektebulunan'
        """
        if text is None:
            return ""
        s = str(text).strip()
        # Explicit Turkish char replacement
        tr_map = {
            "İ": "i", "I": "i", "ı": "i",
            "Ş": "s", "ş": "s",
            "Ğ": "g", "ğ": "g",
            "Ü": "u", "ü": "u",
            "Ö": "o", "ö": "o",
            "Ç": "c", "ç": "c",
        }
        for k, v in tr_map.items():
            s = s.replace(k, v)
        s = s.lower()
        s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("utf-8")
        s = re.sub(r"[^a-z0-9]", "", s)
        return s

    @classmethod
    def map_dataframe(cls, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Analyzes columns and maps them to canonical names.
        Returns mapped DataFrame and detailed mapping diagnostics report.
        """
        work_df = df.copy()
        raw_cols = work_df.columns.tolist()
        cleaned_raw_cols = {col: cls.clean_header(col) for col in raw_cols}

        matched_mapping: Dict[str, str] = {}  # canonical -> raw_column_name
        used_raw_cols = set()

        # Step 1: Semantic Keyword and Substring Matching
        for canonical, keywords in cls.CANONICAL_KEYWORDS.items():
            if canonical in raw_cols:
                matched_mapping[canonical] = canonical
                used_raw_cols.add(canonical)
                continue

            best_match = None
            best_match_score = 0  # preference for longer keyword matches

            for raw_col, clean_raw in cleaned_raw_cols.items():
                if raw_col in used_raw_cols and canonical not in ("root_cause", "openproject_task_id"):
                    # Allow sharing only between root_cause / openproject if necessary
                    continue

                # Ensure technician_raw doesn't accidentally pick technician_group
                if canonical == "technician_raw" and "grub" in clean_raw:
                    continue

                for kw in keywords:
                    if kw in clean_raw:
                        score = len(kw)
                        if score > best_match_score:
                            best_match_score = score
                            best_match = raw_col

            if best_match:
                matched_mapping[canonical] = best_match
                # Avoid reusing technician / institution / op columns
                if canonical in (
                    "technician_raw", "technician_group", "institution",
                    "first_response_time_str", "total_resolution_time_str", "external_wait_time_str",
                    "op_request_type", "op_task_type", "op_basket"
                ):
                    used_raw_cols.add(best_match)

        # Step 2: Content-based fallback inspection
        duration_regex = re.compile(r"\b(dakika|dk|saat|sa|gun|gün|saniye|sn|hour|minute|day)\b", re.IGNORECASE)
        for canonical in ["first_response_time_str", "total_resolution_time_str", "external_wait_time_str", "technician_raw", "status"]:
            if canonical not in matched_mapping:
                for raw_col in raw_cols:
                    if raw_col in used_raw_cols:
                        continue
                    # Inspect sample values
                    sample_vals = work_df[raw_col].dropna().astype(str).head(10).tolist()
                    if not sample_vals:
                        continue

                    # Check for duration string pattern with word boundary to avoid 'güncelleme'
                    if canonical in ("first_response_time_str", "total_resolution_time_str", "external_wait_time_str"):
                        duration_hits = sum(1 for v in sample_vals if duration_regex.search(v))
                        if duration_hits >= 3:
                            matched_mapping[canonical] = raw_col
                            used_raw_cols.add(raw_col)
                            break

                    # Check for status pattern
                    elif canonical == "status":
                        status_hits = sum(1 for v in sample_vals if any(st in v.lower() for st in ("çözül", "kapan", "bekle", "işlen", "yeni", "closed", "open")))
                        if status_hits >= 3:
                            matched_mapping[canonical] = raw_col
                            used_raw_cols.add(raw_col)
                            break

        # Step 3: Populate canonical columns in work_df
        for canonical, raw_col in matched_mapping.items():
            if raw_col in work_df.columns:
                work_df[canonical] = work_df[raw_col]

        # Step 4: Ensure all canonical columns exist with defaults
        defaults = {
            "ticket_id": lambda: range(1, len(work_df) + 1),
            "title": "Servis Masası Çağrısı",
            "institution": "Genel Kurum",
            "category": "Genel Destek",
            "root_cause": "Destek",
            "priority": "Orta",
            "status": "Çözülmüş",
            "technician_raw": "Atanmamış",
            "created_at": "",
            "resolved_at": "",
            "first_response_time_str": "30 dakika",
            "total_resolution_time_str": "1 gün",
            "external_wait_time_str": "0 dakika",
            "is_fcr": False,
            "is_reopened": False,
            "technician_group": "Servis Masası Ekibi",
            "op_request_type": "",
            "op_task_type": "",
            "op_basket": "",
        }

        for canonical, def_val in defaults.items():
            if canonical not in work_df.columns:
                work_df[canonical] = def_val() if callable(def_val) else def_val

        # Diagnostics summary
        diagnostics = {
            "mapped_columns": {k: str(v) for k, v in matched_mapping.items()},
            "unmapped_raw_columns": [c for c in raw_cols if c not in matched_mapping.values()],
            "confidence_score": round((len(matched_mapping) / len(defaults)) * 100, 1),
            "total_raw_columns": len(raw_cols),
        }

        return work_df, diagnostics
