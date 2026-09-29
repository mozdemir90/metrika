from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_TITLE: str = "METRİKA - Operasyonel Metrik ve Raporlama Platformu"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # GLPI API Settings
    GLPI_URL: str = "http://glpi.belgenet.local/apirest.php"
    GLPI_APP_TOKEN: str = ""
    GLPI_USER_TOKEN: str = ""
    GLPI_TIMEOUT_SECONDS: float = 15.0

    # Reporting Defaults
    DEFAULT_REPORT_DAYS: int = 7
    FALLBACK_TO_MOCK: bool = True

    # Qwen LLM API Configuration (TÜRKSAT PAAS Qwen servisi - jiraClassification_prod ile aynı)
    HAKEM_API_URL: str = "https://token.ai.turksat.com.tr/v1/chat/completions"
    HAKEM_API_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2NvbnNvbGUuYWkudHVya3NhdC5jb20udHIiLCJhdWQiOlsicngyOG9tbCIsIjd3Mmxua3AiLCI3dzJsbmtwIiwiVFVSS1NBVCIsIlRVUktTQVQiLCJzeXN0ZW0tY2F0YWxvZyIsIjd3Mmxua3AiLCJnYWFwIl0sImlhdCI6MTc4NDYxNTM5Mn0.SZlNmZ3qctfmVQixnrXRlQWl3OZsIM_PJxGn-aPJyek.b73wf4oub5sfnsc7m7nnj64e7.lelw2lfxqb2rgvuqyheqijih3"
    HAKEM_API_MODEL: str = "qwen35-122b-a10b-fp8"
    QWEN_TIMEOUT_SECONDS: float = 60.0
    ENABLE_QWEN_LLM: bool = True

    # Legacy On-Prem LLM fallback aliases
    ON_PREM_LLM_URL: Optional[str] = None
    ON_PREM_LLM_MODEL: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
