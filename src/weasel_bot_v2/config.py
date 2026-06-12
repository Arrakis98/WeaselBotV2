from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class LavalinkConfig:
    host: str = "lavalink"
    port: int = 2333
    password: str | None = None
    secure: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.password)


@dataclass(frozen=True)
class BotConfig:
    name: str = "Weasel Bot V2"
    data_dir: Path = Path("/app/data")
    logs_dir: Path = Path("/app/logs")
    music_library: Path = Path("/music")


@dataclass(frozen=True)
class Settings:
    discord_token: str | None
    discord_test_guild_id: int | None
    bot: BotConfig
    lavalink: LavalinkConfig

    @classmethod
    def load(cls, cwd: Path | None = None, *, require_token: bool = True) -> Settings:
        base_dir = cwd or Path.cwd()
        load_dotenv(base_dir / ".env", override=False)

        raw_config = _load_yaml(base_dir / "config.yaml")
        if raw_config is None:
            raw_config = _load_yaml(base_dir / "config.example.yaml") or {}

        settings = cls(
            discord_token=_clean_secret(os.getenv("DISCORD_TOKEN")),
            discord_test_guild_id=_optional_int(os.getenv("DISCORD_TEST_GUILD_ID")),
            bot=_load_bot_config(raw_config),
            lavalink=_load_lavalink_config(raw_config),
        )

        if require_token and not settings.discord_token:
            raise ConfigurationError(
                "DISCORD_TOKEN is required. Copy .env.example to .env and set it locally."
            )

        return settings


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ConfigurationError(f"{path.name} must contain a YAML mapping at the top level.")

    return data


def _load_bot_config(raw_config: dict[str, Any]) -> BotConfig:
    bot = _mapping(raw_config.get("bot"))
    paths = _mapping(raw_config.get("paths"))

    return BotConfig(
        name=str(bot.get("name") or "Weasel Bot V2"),
        data_dir=Path(str(paths.get("data_dir") or "/app/data")),
        logs_dir=Path(str(paths.get("logs_dir") or "/app/logs")),
        music_library=Path(str(paths.get("music_library") or "/music")),
    )


def _load_lavalink_config(raw_config: dict[str, Any]) -> LavalinkConfig:
    lavalink = _mapping(raw_config.get("lavalink"))

    host = os.getenv("LAVALINK_HOST") or str(lavalink.get("host") or "lavalink")
    port_value = os.getenv("LAVALINK_PORT") or lavalink.get("port") or 2333
    password = _clean_secret(os.getenv("LAVALINK_PASSWORD") or lavalink.get("password"))
    secure = _optional_bool(os.getenv("LAVALINK_SECURE"))
    if secure is None:
        secure = bool(lavalink.get("secure", False))

    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("LAVALINK_PORT must be an integer.") from exc

    return LavalinkConfig(host=host, port=port, password=password, secure=secure)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: str | None) -> int | None:
    cleaned = _clean_secret(value)
    if cleaned is None:
        return None

    try:
        return int(cleaned)
    except ValueError as exc:
        raise ConfigurationError("DISCORD_TEST_GUILD_ID must be an integer.") from exc


def _optional_bool(value: str | None) -> bool | None:
    cleaned = _clean_secret(value)
    if cleaned is None:
        return None
    return cleaned.lower() in {"1", "true", "yes", "on"}


def _clean_secret(value: object) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None
