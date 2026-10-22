from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from config import load_bridge_config, load_settings


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("discord.http").setLevel(logging.WARNING)


class ChatBridgeBot(commands.Bot):
    def __init__(self) -> None:
        self.settings = load_settings()
        # Fail before logging in if the bridge JSON is missing or malformed.
        load_bridge_config(self.settings.bridge_config_path)
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=self.settings.prefix,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
            case_insensitive=True,
        )

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.bridge")


bot: ChatBridgeBot | None = None


async def handle_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.reply(
            "You need the **Manage Server** permission (or to be listed in `BOT_OWNER_IDS`) to do that.",
            mention_author=False,
        )
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"Missing argument: `{error.param.name}`.", mention_author=False)
        return
    if isinstance(error, commands.BadArgument):
        await ctx.reply("I couldn't understand one of those arguments.", mention_author=False)
        return

    logging.getLogger("chatbridge.commands").error(
        "Unhandled command error",
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.reply("That command failed. Check the bot logs for details.", mention_author=False)


def main() -> int:
    global bot
    try:
        bot = ChatBridgeBot()
    except (RuntimeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(bot.settings.log_level)

    @bot.event
    async def on_ready() -> None:
        logging.getLogger("chatbridge").info(
            "Connected as %s (ID: %s) | discord.py %s",
            bot.user,
            bot.user.id if bot.user else "unknown",
            discord.__version__,
        )
        logging.getLogger("chatbridge").info(
            "Prefix: %r | Bridge config: %s",
            bot.settings.prefix,
            bot.settings.bridge_config_path,
        )

    @bot.event
    async def on_command_error(
        ctx: commands.Context, error: commands.CommandError
    ) -> None:
        await handle_command_error(ctx, error)

    try:
        bot.run(bot.settings.token, log_handler=None)
    except KeyboardInterrupt:
        return 0
    except discord.LoginFailure:
        logging.getLogger("chatbridge").error(
            "Discord rejected the token. Check BOT_TOKEN in your .env file."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
