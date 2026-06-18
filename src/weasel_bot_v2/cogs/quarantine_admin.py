from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.models import UserRecord
from weasel_bot_v2.repositories import UserRepository
from weasel_bot_v2.services.arcadia_manifest import ArcadiaManifestError
from weasel_bot_v2.services.quarantine_layout import (
    QuarantineLayoutPreview,
    QuarantineLayoutResult,
    QuarantineLayoutService,
)
from weasel_bot_v2.services.quarantine_sweep import (
    QuarantineSweepPreview,
    QuarantineSweepResult,
    QuarantineSweepService,
)

_DEFAULT_MANIFEST_PATH = Path("/library_admin/manifests/music_quarantine_manifest.json")
_DEFAULT_VALIDATION_PATH = Path("/library_admin/manifests/music_project_validation.json")


class QuarantineAdminCog(commands.Cog):
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @app_commands.command(
        name="purge_quarantine",
        description="Preview or quarantine all SuperDisliked and MediaTool candidates.",
    )
    @app_commands.describe(
        execute="Leave false for a safe preview; set true to move every eligible file.",
    )
    @app_commands.default_permissions(administrator=True)
    async def purge_quarantine(
        self,
        interaction: discord.Interaction,
        execute: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return
        if not await self._is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "Only an administrator or bot owner can manage quarantine.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        service = QuarantineSweepService(
            self.bot,
            manifest_path=_configured_path(
                "WEASEL_QUARANTINE_MANIFEST_PATH",
                _DEFAULT_MANIFEST_PATH,
            ),
            validation_path=_configured_path(
                "WEASEL_PROJECT_VALIDATION_PATH",
                _DEFAULT_VALIDATION_PATH,
            ),
        )
        current_track_id = _current_track_id(self.bot, guild.id)
        try:
            if not execute:
                preview = service.preview(
                    guild_id=guild.id,
                    current_track_id=current_track_id,
                )
                await interaction.followup.send(
                    format_sweep_preview(preview),
                    ephemeral=True,
                )
                return

            _upsert_user(self.bot, interaction)
            result = service.apply(
                guild_id=guild.id,
                requested_by_user_id=interaction.user.id,
                current_track_id=current_track_id,
            )
        except (ArcadiaManifestError, ValueError) as exc:
            await interaction.followup.send(
                f"Quarantine sweep rejected safely: {exc}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            format_sweep_result(result),
            ephemeral=True,
        )

    @app_commands.command(
        name="quarantine_layout",
        description="Preview or migrate legacy quarantine files into source folders.",
    )
    @app_commands.describe(
        execute="Leave false for a safe preview; set true to migrate legacy records.",
    )
    @app_commands.default_permissions(administrator=True)
    async def quarantine_layout(
        self,
        interaction: discord.Interaction,
        execute: bool = False,
    ) -> None:
        if not await self._is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "Only an administrator or bot owner can migrate quarantine layout.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        service = QuarantineLayoutService(self.bot)
        if not execute:
            await interaction.followup.send(
                format_layout_preview(service.preview()),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            format_layout_result(service.apply()),
            ephemeral=True,
        )

    async def _is_admin_or_owner(self, interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if bool(getattr(permissions, "administrator", False)):
            return True
        try:
            app_info = await self.bot.application_info()
        except Exception:  # noqa: BLE001 - guild administrator remains the fallback.
            return False
        owner = getattr(app_info, "owner", None)
        return getattr(owner, "id", None) == interaction.user.id


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuarantineAdminCog(bot))


def format_sweep_preview(preview: QuarantineSweepPreview) -> str:
    lines = [
        "Unified quarantine preview",
        f"Eligible total: {preview.eligible}",
        f"SuperDislike eligible: {len(preview.superdisliked.eligible)}",
        f"MediaTool eligible: {preview.mediatool.eligible}",
        f"Already quarantined: {preview.already_quarantined}",
        f"Blocked: {len(preview.blocked)}",
        "Destinations: superdislike/ and mediatool/",
    ]
    if preview.blocked:
        lines.append("Blocked items:")
        lines.extend(f"- {_shorten(item)}" for item in preview.blocked[:8])
        if len(preview.blocked) > 8:
            lines.append(f"- ... and {len(preview.blocked) - 8} more")
        lines.append("No file was moved.")
    else:
        lines.append("All preflight checks passed. Re-run with execute:true.")
    return "\n".join(lines)


def format_sweep_result(result: QuarantineSweepResult) -> str:
    lines = [
        "Unified quarantine result",
        f"Moved total: {result.moved}",
        f"SuperDislike moved: {result.superdisliked.moved}",
        f"MediaTool moved: {result.mediatool.moved}",
        f"Already quarantined: {result.already_quarantined}",
        f"Failed: {result.failed}",
        f"Removed from future queues: {result.removed_from_queue}",
    ]
    if result.failures:
        lines.append("Failures:")
        lines.extend(f"- {_shorten(item)}" for item in result.failures[:8])
        if len(result.failures) > 8:
            lines.append(f"- ... and {len(result.failures) - 8} more")
    else:
        lines.append("Every moved file remains restorable.")
    return "\n".join(lines)


def format_layout_preview(preview: QuarantineLayoutPreview) -> str:
    lines = [
        "Quarantine layout migration preview",
        f"Eligible legacy records: {len(preview.eligible)}",
        f"Already current: {preview.already_current}",
        f"Blocked: {len(preview.blocked)}",
    ]
    if preview.blocked:
        lines.extend(f"- {_shorten(item)}" for item in preview.blocked[:8])
        lines.append("No file was moved.")
    else:
        lines.append("Re-run with execute:true to migrate into source folders.")
    return "\n".join(lines)


def format_layout_result(result: QuarantineLayoutResult) -> str:
    lines = [
        "Quarantine layout migration result",
        f"Migrated: {result.migrated}",
        f"Already current: {result.already_current}",
        f"Failed: {result.failed}",
    ]
    if result.failures:
        lines.extend(f"- {_shorten(item)}" for item in result.failures[:8])
    else:
        lines.append("The unified quarantine layout is ready.")
    return "\n".join(lines)


def _configured_path(environment_name: str, default: Path) -> Path:
    value = os.getenv(environment_name)
    return Path(value).expanduser() if value else default


def _current_track_id(bot: Any, guild_id: int) -> int | None:
    state = bot.player_states.get(guild_id)
    current = state.current_track if state is not None else None
    track_id = getattr(current, "id", None)
    return int(track_id) if track_id is not None else None


def _upsert_user(bot: Any, interaction: discord.Interaction) -> None:
    UserRepository(bot.database).upsert(
        UserRecord(
            user_id=interaction.user.id,
            display_name=getattr(interaction.user, "display_name", None),
        )
    )


def _shorten(value: str, limit: int = 180) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."
