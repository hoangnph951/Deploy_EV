from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    auth_session_ttl_hours: int = Field(default=24, ge=1, le=168)
    auth_remembered_session_ttl_days: int = Field(default=30, ge=1, le=90)

    openai_api_key: str = ""
    openai_base_url: str = ""
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    ai_plan_explanation_enabled: bool = False
    ai_plan_explanation_timeout_seconds: float = Field(default=12.0, gt=0.1, le=60.0)
    openai_station_fallback_enabled: bool = True
    openai_station_search_model: str = "gpt-5.4-mini"
    openai_station_search_timeout_seconds: float = Field(default=20.0, gt=1.0, le=60.0)
    openai_station_search_max_candidates: int = Field(default=12, ge=1, le=20)
    openai_station_search_allowed_domains: str = ""
    openai_recovery_enabled: bool = True
    openai_recovery_model: str = "gpt-5.4-mini"
    openai_recovery_timeout_seconds: float = Field(default=20.0, gt=1.0, le=60.0)
    openai_replanning_model: str = "gpt-5.4-mini"
    openai_replanning_prompt_version: str = "f4-supervisor-v3"
    openai_replanning_enabled: bool = True
    openai_replanning_timeout_seconds: float = Field(default=30.0, gt=1.0, le=60.0)
    replanning_max_tool_calls: int = Field(default=6, ge=1, le=12)
    replanning_max_llm_turns: int = Field(default=12, ge=1, le=16)

    database_url: str = "sqlite:///./data/app.db"
    chroma_persist_dir: str = "./data/chroma"
    goong_maptiles_key: str = ""
    goong_api_key: str = ""
    goong_api_base_url: str = "https://rsapi.goong.io"
    geocoder_provider: Literal["fixture", "goong"] = "goong"
    geocoder_timeout_seconds: float = Field(default=4.0, gt=0.1, le=30.0)
    geocoder_result_limit: int = Field(default=5, ge=1, le=10)
    routing_provider: Literal["fixture", "goong"] = "goong"
    routing_timeout_seconds: float = Field(default=8.0, gt=0.1, le=30.0)
    routing_max_retries: int = Field(default=2, ge=0, le=5)
    goong_min_request_interval_seconds: float = Field(default=0.2, ge=0.0, le=5.0)
    goong_rate_limit_cooldown_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    monitoring_max_off_route_distance_km: float = Field(default=2.0, gt=0, le=100)
    monitoring_max_soc_drop_deviation_percent: float = Field(default=5.0, gt=0, le=100)
    monitoring_max_telemetry_silent_seconds: float = Field(default=60.0, gt=0, le=3600)
    station_provider: Literal["fixture", "vinfast"] = "vinfast"
    vinfast_locator_meta_url: str = "https://static-cms-prod.vinfastauto.com/locators/locators-meta.json"
    vinfast_locator_dataset_base_url: str = "https://static-cms-prod.vinfastauto.com/locators"
    vinfast_locator_detail_base_url: str = "https://vinfastauto.com/vn_vi/get-locator"
    vinfast_timeout_seconds: float = Field(default=15.0, gt=0.1, le=60.0)
    open_meteo_weather_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_elevation_url: str = "https://api.open-meteo.com/v1/elevation"
    open_meteo_timeout_seconds: float = Field(default=8.0, gt=0.1, le=30.0)
    environment_provider: Literal["fixture", "open_meteo"] = "open_meteo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
