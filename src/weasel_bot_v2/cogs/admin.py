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
from weasel_bot_v2.services.arcadia_quarantine import (
    ArcadiaQuarantinePreview,
    ArcadiaQuarantineResult,
    ArcadiaQuarantineService,
)

_DEFAULT_MANIFEST_PATH = Path("/library_admin/manifests/music_quarantine_manifest.json")
_DEFAULT_VALIDATION_PATH = Path("/library_admin/manifests/music_project_validation.json")


class AdminCog(commands.Cog):
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check whether Weasel Bot V2 is responding.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong. Latency: {latency_ms} ms",
            ephemeral=True,
        )

    @app_commands.command(
        name="quarantine_manifest",
        description="Preview or apply an approved Arcadia quarantine manifest.",
    )
    @app_commands.describe(
        execute="Leave false for a safe preview; set true to move approved files.",
    )
    @app_commands.default_permissions(administrator=True)
    async def quarantine_manifest(
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
                "Only an administrator or bot owner can manage quarantine manifests.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        service = ArcadiaQuarantineService(
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
                preview = service.preview(current_track_id=current_track_id)
                await interaction.followup.send(
                    format_manifest_preview(preview),
                    ephemeral=True,
                )
                return

            UserRepository(self.bot.database).upsert(
                UserRecord(
                    user_id=interaction.user.id,
                    display_name=getattr(interaction.user, "display_name", None),
                )
            )
            result = service.apply(
                guild_id=guild.id,
                requested_by_user_id=interaction.user.id,
                current_track_id=current_track_id,
            )
        except (ArcadiaManifestError, ValueError) as exc:
            await interaction.followup.send(
                f"Manifest rejected safely: {exc}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            format_manifest_result(result),
            ephemeral=True,
        )

    async def _is_admin_or_owner(self, interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if bool(getattr(permissions, "administrator", False)):
            return True
        try:
            app_info = await self.bot.application_info()
        except Exception:  # noqa: BLE001 - fall back to guild administrator.
            return False
        owner = getattr(app_info, "owner", None)
        return getattr(owner, "id", None) == interaction.user.id


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))


def format_manifest_preview(preview: ArcadiaQuarantinePreview) -> str:
    lines = [
        "Arcadia quarantine manifest preview",
        f"Manifest: {preview.digest[:12]}",
        f"Operations: {preview.operation_count}",
        f"Eligible: {preview.eligible}",
        f"Already quarantined: {preview.already_quarantined}",
        f"Blocked: {len(preview.blocked)}",
        "Reasons: "
        + ", ".join(f"{reason}={count}" for reason, count in sorted(preview.reason_counts.items())),
    ]
    if preview.blocked:
        lines.append("Blocked items:")
        lines.extend(f"- {_shorten(item)}" for item in preview.blocked[:8])
        if len(preview.blocked) > 8:
            lines.append(f"- ... and {len(preview.blocked) - 8} more")
        lines.append("No file was moved.")
    else:
        lines.append("All preflight checks passed.")
        lines.append("Re-run with execute:true to apply this exact report family.")
    return "\n".join(lines)


def format_manifest_result(result: ArcadiaQuarantineResult) -> str:
    lines = [
        "Arcadia quarantine manifest result",
        f"Manifest: {result.digest[:12]}",
        f"Moved: {result.moved}",
        f"Already quarantined: {result.already_quarantined}",
        f"Failed: {result.failed}",
        f"Removed from future queues: {result.removed_from_queue}",
    ]
    if result.failures:
        lines.append("Failures:")
        lines.extend(f"- {_shorten(item)}" for item in result.failures[:8])
        if len(result.failures) > 8:
            lines.append(f"- ... and {len(result.failures) - 8} more")
    elif result.moved:
        lines.append("Every moved file remains available to /restore_quarantined.")
    else:
        lines.append("No file needed to be moved.")
    return "\n".join(lines)


def _configured_path(environment_name: str, default: Path) -> Path:
    value = os.getenv(environment_name)
    return Path(value).expanduser() if value else default


def _current_track_id(bot: Any, guild_id: int) -> int | None:
    state = bot.player_states.get(guild_id)
    current = state.current_track if state is not None else None
    track_id = getattr(current, "id", None)
    return int(track_id) if track_id is not None else None


def _shorten(value: str, limit: int = 180) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."
