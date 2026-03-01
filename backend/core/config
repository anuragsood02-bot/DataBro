"""
core/config.py
Centralised settings — loaded once at startup from .env / environment variables.
"""
from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # App
    app_name: str = "DataBro"
    app_url: str = "http://localhost:8000"
    environment: str = "development"
    debug: bool = False

    # Server
    port: int = 8000
    allowed_origins: str = "*"

    # Auth
    secret_key: str = "change-me-in-production"
    session_ttl_hours: int = 72

    # Anthropic / Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 4096

    # Files
    upload_dir: str = "uploads"
    max_upload_mb: int = 25

    # Email
    email_provider: str = "none"   # none | resend | sendgrid | smtp
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = "hello@databro.ai"

    # Features
    demo_mode: bool = True
    require_email_verify: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def cors_origins(self) -> List[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


# Singleton — import this everywhere
settings = Settings()
