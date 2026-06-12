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
    timeout_seconds: float = 30.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.port and self.password)


@dataclass(frozen=True)
class BotConfig:
    name: str = "Weasel Bot V2"
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    music_library: Path = Path("music")


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path = Path("data/weasel.db")

    @property
    def configured(self) -> bool:
        return bool(self.path)


@dataclass(frozen=True)
class FeatureFlags:
    music: bool = False
    local_library: bool = False
    web_playback: bool = False
    playlists: bool = False
    history: bool = False
    ratings: bool = False
    legacy_json_import: bool = False
    rich_discord_ui: bool = False
    ai: bool = False
    chaos_mode: bool = False

    def safe_summary(self) -> str:
        enabled = [
            name
            for name, value in (
                ("music", self.music),
                ("local_library", self.local_library),
                ("web_playback", self.web_playback),
                ("playlists", self.playlists),
                ("history", self.history),
                ("ratings", self.ratings),
                ("legacy_json_import", self.legacy_json_import),
                ("rich_discord_ui", self.rich_discord_ui),
                ("ai", self.ai),
                ("chaos_mode", self.chaos_mode),
            )
            if value
        ]
        return ", ".join(enabled) if enabled else "none"


@dataclass(frozen=True)
class Settings:
    discord_token: str | None
    discord_test_guild_id: int | None
    bot: BotConfig
    lavalink: LavalinkConfig
    database: DatabaseConfig
    features: FeatureFlags

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
            bot=_load_bot_config(raw_config, base_dir),
            lavalink=_load_lavalink_config(raw_config),
            database=_load_database_config(raw_config, base_dir),
            features=_load_feature_flags(raw_config),
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


def _load_bot_config(raw_config: dict[str, Any], base_dir: Path) -> BotConfig:
    bot = _mapping(raw_config.get("bot"))
    paths = _mapping(raw_config.get("paths"))

    return BotConfig(
        name=str(bot.get("name") or "Weasel Bot V2"),
        data_dir=_path_value(paths.get("data_dir"), base_dir / "data", base_dir),
        logs_dir=_path_value(paths.get("logs_dir"), base_dir / "logs", base_dir),
        music_library=_path_value(paths.get("music_library"), base_dir / "music", base_dir),
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

    timeout_value = os.getenv("LAVALINK_TIMEOUT_SECONDS") or lavalink.get("timeout_seconds") or 30
    try:
        timeout_seconds = float(timeout_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("LAVALINK_TIMEOUT_SECONDS must be a number.") from exc

    return LavalinkConfig(
        host=host,
        port=port,
        password=password,
        secure=secure,
        timeout_seconds=timeout_seconds,
    )


def _load_database_config(raw_config: dict[str, Any], base_dir: Path) -> DatabaseConfig:
    database = _mapping(raw_config.get("database"))
    return DatabaseConfig(
        path=_path_value(database.get("path"), base_dir / "data" / "weasel.db", base_dir)
    )


def _load_feature_flags(raw_config: dict[str, Any]) -> FeatureFlags:
    features = _mapping(raw_config.get("features"))
    chaos_mode = _mapping(raw_config.get("chaos_mode"))
    return FeatureFlags(
        music=_bool_value(features.get("music"), False),
        local_library=_bool_value(features.get("local_library"), False),
        web_playback=_bool_value(features.get("web_playback"), False),
        playlists=_bool_value(features.get("playlists"), False),
        history=_bool_value(features.get("history"), False),
        ratings=_bool_value(features.get("ratings"), False),
        legacy_json_import=_bool_value(features.get("legacy_json_import"), False),
        rich_discord_ui=_bool_value(features.get("rich_discord_ui"), False),
        ai=_bool_value(features.get("ai"), False),
        chaos_mode=_bool_value(chaos_mode.get("enabled"), False),
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _path_value(value: object, default: Path, base_dir: Path) -> Path:
    if value is None:
        return default

    path = Path(str(value))
    if path.is_absolute():
        return path
    return base_dir / path


def _bool_value(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
