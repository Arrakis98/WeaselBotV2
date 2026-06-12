from __future__ import annotations

from discord import app_commands

from weasel_bot_v2.cogs.debug import DebugCog


def test_bot_status_command_uses_safe_callback_name() -> None:
    command = next(
        command for command in DebugCog.__cog_app_commands__ if command.name == "bot_status"
    )

    assert isinstance(command, app_commands.Command)
    assert command.name == "bot_status"
    assert command.callback.__name__ == "show_bot_status"
