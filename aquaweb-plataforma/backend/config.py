"""Configuración centralizada de AquaWeb IoT mediante Pydantic Settings v2."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent

PHYSICAL_LIMITS: dict[str, tuple[float, float]] = {
    "ph": (0.0, 14.0),
    "temperatura": (-5.0, 60.0),
    "tds": (0.0, 50000.0),
    "ec": (0.0, 80000.0),
    "salinidad": (0.0, 50000.0),
}

DEFAULT_THRESHOLDS: dict[str, dict[str, float | str]] = {
    "ph": {"min_optimo": 6.5, "max_optimo": 9.5, "min_fisico": 0.0, "max_fisico": 14.0, "unidad": "pH"},
    "temperatura": {"min_optimo": 20.0, "max_optimo": 30.0, "min_fisico": -5.0, "max_fisico": 60.0, "unidad": "°C"},
    "tds": {"min_optimo": 4000.0, "max_optimo": 15000.0, "min_fisico": 0.0, "max_fisico": 50000.0, "unidad": "ppm"},
    "ec": {"min_optimo": 10000.0, "max_optimo": 35000.0, "min_fisico": 0.0, "max_fisico": 80000.0, "unidad": "ppm"},
    "salinidad": {"min_optimo": 5000.0, "max_optimo": 23000.0, "min_fisico": 0.0, "max_fisico": 50000.0, "unidad": "ppm"},
}

# Saltos máximos físicamente plausibles entre dos lecturas consecutivas (<= 15 s)
MAX_ABRUPT_JUMP: dict[str, float] = {
    "ph": 2.5,
    "temperatura": 8.0,
    "tds": 15000.0,
    "ec": 25000.0,
    "salinidad": 15000.0,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://aquaweb:aquaweb_secret_2026@localhost:5432/aquaweb_iot"
    )
    mqtt_broker_host: str = Field(default="broker.hivemq.com")
    mqtt_broker_port: int = Field(default=1883)
    mqtt_username: str = Field(default="")
    mqtt_password: str = Field(default="")
    mqtt_keepalive_seg: int = Field(default=15)
    mqtt_grupo: str = Field(default="grupo")
    mqtt_device_id: str = Field(default="estanque-01")
    mqtt_enabled: bool = Field(default=True)

    default_pub_interval_seg: int = Field(default=5)
    silence_multiplier: int = Field(default=3)
    frozen_sensor_cycles: int = Field(default=5)
    command_timeout_seg: int = Field(default=15)
    alert_resolve_cycles: int = Field(default=2)
    buffer_file_path: str = Field(default="backend/data/buffer_pendiente.jsonl")

    api_key: str = Field(default="aquaweb-dev-key-2026")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,https://cris19111.github.io"
    )
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def buffer_path(self) -> Path:
        p = Path(self.buffer_file_path)
        return p if p.is_absolute() else (BASE_DIR / p)

    def topic_prefix(self, device_id: str | None = None) -> str:
        dev = device_id or self.mqtt_device_id
        return f"utp/ds8/{self.mqtt_grupo}/aquaweb/{dev}"

    @property
    def topic_wildcard(self) -> str:
        return f"utp/ds8/{self.mqtt_grupo}/aquaweb/+"

    @property
    def topic_all_devices(self) -> str:
        return f"utp/ds8/{self.mqtt_grupo}/aquaweb/#"


settings = Settings()
