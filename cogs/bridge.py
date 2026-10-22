from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from config import BridgeConfigError, BridgeGroup, load_bridge_config

log = logging.getLogger("chatbridge.bridge")
WEBHOOK_NAME = "Chat Bridge"
MAX_WEBHOOK_FILES = 10
MAX_MESSAGE_LENGTH = 2000
MAX_TRACKED_MESSAGES = 5000


class BridgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config_path = bot.settings.bridge_config_path
        self.groups: list[BridgeGroup] = []
        self.routes: dict[int, tuple[BridgeGroup, tuple[int, ...]]] = {}
        self.webhooks: dict[int, discord.Webhook] = {}
        self.webhook_locks: dict[int, Any] = {}
        # Source message ID -> messages posted to the other channels. In-memory by design.
        self.forwarded_messages: dict[int, list[discord.Message]] = {}
        self.reload_config()

    def reload_config(self) -> int:
        """Load the whole file first, then atomically replace the active routes."""
        groups = load_bridge_config(self.config_path)
        routes: dict[int, tuple[BridgeGroup, tuple[int, ...]]] = {}
        for group in groups:
            if not group.enabled:
                continue
            for source_id in group.channels:
                destinations = tuple(channel_id for channel_id in group.channels if channel_id != source_id)
                routes[source_id] = (group, destinations)

        self.groups = groups
        self.routes = routes
        log.info(
            "Loaded %d enabled bridge group(s), routing %d channel(s)",
            sum(group.enabled for group in groups),
            len(routes),
        )
        return len(routes)

    def _webhook_lock(self, channel_id: int):
        # Locks are created lazily so messages arriving at one destination cannot race
        # to create duplicate webhooks.
        import asyncio

        lock = self.webhook_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self.webhook_locks[channel_id] = lock
        return lock

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        cached = self.webhooks.get(channel.id)
        if cached is not None:
            return cached

        async with self._webhook_lock(channel.id):
            cached = self.webhooks.get(channel.id)
            if cached is not None:
                return cached
            webhooks = await channel.webhooks()
            bot_user = self.bot.user
            for webhook in webhooks:
                if (
                    webhook.name == WEBHOOK_NAME
                    and webhook.user is not None
                    and bot_user is not None
                    and webhook.user.id == bot_user.id
                ):
                    self.webhooks[channel.id] = webhook
                    return webhook

            webhook = await channel.create_webhook(
                name=WEBHOOK_NAME,
                reason="Create a webhook for Discord Chat Bridge message relaying",
            )
            self.webhooks[channel.id] = webhook
            log.info("Created relay webhook in #%s (%s)", channel.name, channel.id)
            return webhook

    def _source_label(self, message: discord.Message) -> str:
        guild_name = discord.utils.escape_markdown(message.guild.name if message.guild else "Discord")
        channel_name = discord.utils.escape_markdown(getattr(message.channel, "name", "channel"))
        return f"**{guild_name} · #{channel_name}**"

    def _payload_content(
        self, message: discord.Message, group: BridgeGroup
    ) -> str | None:
        content = message.clean_content or ""
        if not content and message.stickers:
            content = "\n".join(
                f"Sticker: {sticker.name} ({sticker.url})" for sticker in message.stickers[:5]
            )
        if group.show_source:
            label = self._source_label(message)
            content = f"{label}\n{content}" if content else label
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[: MAX_MESSAGE_LENGTH - 1] + "…"
        return content or None

    @staticmethod
    def _copied_embeds(message: discord.Message) -> list[discord.Embed]:
        copied: list[discord.Embed] = []
        for embed in message.embeds[:10]:
            try:
                copied.append(discord.Embed.from_dict(embed.to_dict()))
            except (TypeError, ValueError):
                log.debug("Skipped an embed that could not be copied from message %s", message.id)
        return copied

    async def _upload_files(self, message: discord.Message) -> list[discord.File]:
        files: list[discord.File] = []
        attachments = message.attachments[:MAX_WEBHOOK_FILES]
        for attachment in attachments:
            files.append(await attachment.to_file())
        if len(message.attachments) > MAX_WEBHOOK_FILES:
            log.warning(
                "Message %s has %d attachments; only the first %d can be relayed in one message",
                message.id,
                len(message.attachments),
                MAX_WEBHOOK_FILES,
            )
        return files

    async def _resolve_text_channel(self, channel_id: int) -> discord.TextChannel | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Could not access destination channel %s: %s", channel_id, exc)
                return None
        if not isinstance(channel, discord.TextChannel):
            log.warning(
                "Destination %s is not a standard text/announcement channel; skipping it",
                channel_id,
            )
            return None
        return channel

    async def _send_fallback(
        self,
        channel: discord.TextChannel,
        message: discord.Message,
        group: BridgeGroup,
        files: list[discord.File],
        embeds: list[discord.Embed],
    ) -> discord.Message:
        """Send as the bot when webhook management is not available."""
        author = discord.utils.escape_markdown(message.author.display_name)
        content = self._payload_content(message, group) or ""
        fallback_prefix = f"**{author}** · "
        available = max(0, MAX_MESSAGE_LENGTH - len(fallback_prefix))
        content = fallback_prefix + content[:available]
        kwargs: dict[str, Any] = {
            "content": content,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if files:
            kwargs["files"] = files
        if embeds:
            kwargs["embeds"] = embeds
        return await channel.send(**kwargs)

    async def _relay_to_channel(
        self, message: discord.Message, channel: discord.TextChannel, group: BridgeGroup
    ) -> discord.Message | None:
        files: list[discord.File] = []
        try:
            files = await self._upload_files(message)
            embeds = self._copied_embeds(message)
            content = self._payload_content(message, group)
            try:
                webhook = await self._get_webhook(channel)
                webhook_kwargs: dict[str, Any] = {
                    "content": content,
                    "username": message.author.display_name[:80],
                    "avatar_url": message.author.display_avatar.url,
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "wait": True,
                }
                if files:
                    webhook_kwargs["files"] = files
                if embeds:
                    webhook_kwargs["embeds"] = embeds
                sent = await webhook.send(**webhook_kwargs)
                if sent is not None:
                    return sent
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning(
                    "Webhook relay failed for channel %s; trying a bot message instead: %s",
                    channel.id,
                    exc,
                )
                if isinstance(exc, discord.NotFound):
                    self.webhooks.pop(channel.id, None)
                # A failed webhook send can consume file streams; rewind before fallback.
                for file in files:
                    try:
                        file.reset(seek=0)
                    except (AttributeError, OSError, ValueError):
                        pass
                return await self._send_fallback(channel, message, group, files, embeds)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, OSError) as exc:
            log.warning(
                "Could not relay source message %s to channel %s: %s",
                message.id,
                channel.id,
                exc,
            )
        finally:
            for file in files:
                try:
                    file.close()
                except Exception:
                    log.debug("Failed to close a relay file handle", exc_info=True)
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return
        route = self.routes.get(message.channel.id)
        if route is None:
            return

        # Don't relay valid bot commands into the other linked channels.
        try:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return
        except Exception:
            log.debug("Could not determine whether message %s is a command", message.id, exc_info=True)

        group, destination_ids = route
        if not (message.content or message.attachments or message.embeds or message.stickers):
            return

        forwarded: list[discord.Message] = []
        for channel_id in destination_ids:
            channel = await self._resolve_text_channel(channel_id)
            if channel is None:
                continue
            sent = await self._relay_to_channel(message, channel, group)
            if sent is not None:
                forwarded.append(sent)
        if forwarded:
            self.forwarded_messages[message.id] = forwarded
            # Bound memory usage on a long-running bridge. Older mappings stop
            # tracking edits/deletions but the relayed messages remain in Discord.
            while len(self.forwarded_messages) > MAX_TRACKED_MESSAGES:
                oldest_message_id = next(iter(self.forwarded_messages))
                self.forwarded_messages.pop(oldest_message_id, None)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if after.author.bot or after.webhook_id is not None:
            return
        forwarded = self.forwarded_messages.get(after.id)
        if not forwarded:
            return
        group_route = self.routes.get(after.channel.id)
        if group_route is None:
            return
        group, _ = group_route
        content = self._payload_content(after, group)
        embeds = self._copied_embeds(after)
        for sent in forwarded:
            try:
                await sent.edit(
                    content=content,
                    embeds=embeds,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.debug("Could not update relayed message %s: %s", sent.id, exc)

    async def _delete_forwarded(self, message_id: int) -> None:
        forwarded = self.forwarded_messages.pop(message_id, [])
        for sent in forwarded:
            try:
                await sent.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.debug("Could not delete relayed message %s: %s", sent.id, exc)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        await self._delete_forwarded(message.id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        # Raw delete also works when the source message is no longer in the cache.
        await self._delete_forwarded(payload.message_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        for message_id in payload.message_ids:
            await self._delete_forwarded(message_id)

    @commands.group(name="bridge", invoke_without_command=True)
    async def bridge(self, ctx: commands.Context) -> None:
        await ctx.reply(
            f"Use `{self.bot.command_prefix}bridge help` to see bridge commands.",
            mention_author=False,
        )

    @bridge.command(name="help")
    async def bridge_help(self, ctx: commands.Context) -> None:
        prefix = self.bot.command_prefix
        embed = discord.Embed(
            title="Discord Chat Bridge",
            description="Relays messages between configured Discord text channels.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name=f"`{prefix}bridge status`", value="Show configured bridge groups.", inline=False)
        embed.add_field(name=f"`{prefix}bridge ping`", value="Check whether the bot is responsive.", inline=False)
        embed.add_field(
            name=f"`{prefix}bridge reload`",
            value="Reload `bridges.json` (requires Manage Server or a configured bot owner).",
            inline=False,
        )
        embed.set_footer(text="Commands are not relayed to other bridge channels.")
        await ctx.reply(embed=embed, mention_author=False)

    @bridge.command(name="ping")
    async def bridge_ping(self, ctx: commands.Context) -> None:
        await ctx.reply("Pong — the bridge is online.", mention_author=False)

    @bridge.command(name="status")
    async def bridge_status(self, ctx: commands.Context) -> None:
        active = [group for group in self.groups if group.enabled]
        if not active:
            await ctx.reply(
                "No bridge groups are enabled. Edit `bridges.json`, then run `bridge reload`.",
                mention_author=False,
            )
            return

        lines = [f"**{group.name}** — {len(group.channels)} channel(s)" for group in active]
        description = "\n".join(lines)
        if len(description) > 3800:
            description = description[:3797] + "..."
        embed = discord.Embed(title="Bridge status", description=description, color=discord.Color.blurple())
        embed.add_field(name="Routed channels", value=str(len(self.routes)))
        embed.add_field(name="Edit/delete tracking", value="In memory until restart")
        await ctx.reply(embed=embed, mention_author=False)

    @bridge.command(name="reload")
    @commands.check(
        lambda ctx: (
            ctx.author.id in getattr(getattr(ctx.bot, "settings", None), "owner_ids", frozenset())
            or (
                ctx.guild is not None
                and isinstance(ctx.author, discord.Member)
                and ctx.author.guild_permissions.manage_guild
            )
        )
    )
    async def bridge_reload(self, ctx: commands.Context) -> None:
        try:
            routed_channels = self.reload_config()
        except BridgeConfigError as exc:
            await ctx.reply(f"Configuration was not changed: {exc}", mention_author=False)
            return
        await ctx.reply(
            f"Bridge configuration reloaded. **{len([g for g in self.groups if g.enabled])}** enabled group(s), "
            f"**{routed_channels}** routed channel(s).",
            mention_author=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BridgeCog(bot))
