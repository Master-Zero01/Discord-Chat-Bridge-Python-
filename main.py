# Original code by Baghi#5121, edited by _MasterZero#5029

import discord
import asyncio
from discord.ext import commands
import os
import sys
import config

# Connecting bot commands
client = commands.Bot(command_prefix='.')

@client.command()
async def load(ctx, extension):
    client.load_extension(f'cogs.{extension}')
    await ctx.send('Cogs are loaded')

@client.command()
async def unload(ctx, extension):
    client.unload_extension(f'cogs.{extension}')
    await ctx.send('Cogs are unloaded')

@client.command()
async def reload(ctx, extension):
    client.unload_extension(f'cogs.{extension}')
    client.load_extension(f'cogs.{extension}')
    await ctx.send('Cogs are reloaded')

# Connections
for filename in os.listdir('./cogs'):
    if filename.endswith('.py'):
        cog_name = filename[:-3]  # Remove the file extension (.py)
        if cog_name in config.cogs:
            client.load_extension(f"cogs.{cog_name}")

@client.event
async def on_ready():
    await client.change_presence(status=discord.Status.online)
    print('Bot online')
    await asyncio.sleep(300)
    restart_program(0.65)

def restart_program():
    python = sys.executable
    os.execl(python, python, *sys.argv)

client.run(config.token)
