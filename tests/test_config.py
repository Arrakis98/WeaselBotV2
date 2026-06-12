from __future__ import annotations

from pathlib import Path

import pytest

from weasel_bot_v2.config import ConfigurationError, Settings


def test_missing_discord_token_fails_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    with pytest.raises(ConfigurationError, match="DISCORD_TOKEN is required"):
        Settings.load(tmp_path, require_token=True)


def test_missing_discord_token_allowed_for_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)

    settings = Settings.load(tmp_path, require_token=False)

    assert settings.discord_token is None


def test_env_values_override_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_TEST_GUILD_ID", "123456789")
    monkeypatch.setenv("LAVALINK_HOST", "audio")
    monkeypatch.setenv("LAVALINK_PORT", "2444")
    monkeypatch.setenv("LAVALINK_PASSWORD", "local-password")

    settings = Settings.load(tmp_path)

    assert settings.discord_token == "test-token"
    assert settings.discord_test_guild_id == 123456789
    assert settings.lavalink.host == "audio"
    assert settings.lavalink.port == 2444
    assert settings.lavalink.password == "local-password"
    assert settings.lavalink.configured is True


def test_config_yaml_can_provide_non_secret_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.delenv("LAVALINK_HOST", raising=False)
    monkeypatch.delenv("LAVALINK_PORT", raising=False)
    monkeypatch.delenv("LAVALINK_PASSWORD", raising=False)
    (tmp_path / "config.yaml").write_text(
        """
bot:
  name: Test Bot
paths:
  data_dir: /tmp/weasel-data
lavalink:
  host: localhost
  port: 2333
  secure: false
""",
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.bot.name == "Test Bot"
    assert settings.bot.data_dir == Path("/tmp/weasel-data")
    assert settings.lavalink.host == "localhost"
    assert settings.lavalink.port == 2333
    assert settings.lavalink.password is None

