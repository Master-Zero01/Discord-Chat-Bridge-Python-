import discord
from discord.ext import commands
from discord import Embed
import asyncio
import config  # Import the config module
from aiohttp import ClientSession

webhook_url = "WEBHOOK_URL"

class Test1(commands.Cog):
    def __init__(self, client, target_channel_id):
        self.client = client
        self.target_channel_id = target_channel_id
        self.session = ClientSession()

    def cog_unload(self):
        asyncio.create_task(self.session.close())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id == CHANNEL_ID:
            webhook = discord.Webhook.from_url(webhook_url, adapter=discord.AsyncWebhookAdapter(self.session))
            
            content = message.clean_content
            
            # Check if message has attachments
            if message.attachments:
                # Send the message content and attachments
                await webhook.send(content=content, files=[await attachment.to_file() for attachment in message.attachments])
            elif message.embeds:
                # Send the message content and the first embed (if it exists)
                await webhook.send(content=content, embeds=[message.embeds[0]])
            else:
                await webhook.send(content=content, username=message.author.name, avatar_url=message.author.avatar_url)

def setup(client):
    target_channel_id = config.cog_config.get('target_channel_id')
    client.add_cog(Test1(client, target_channel_id))