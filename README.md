# Discord Chat Bridge (Python)

A small, self-hosted Discord bot for relaying messages between two or more text channels. It builds on the original [Discord-Chat-Bridge-Python-](https://github.com/Master-Zero01/Discord-Chat-Bridge-Python-) project and keeps its Python + `discord.py` + cog approach, while replacing hardcoded credentials and the older webhook code with a configurable relay.

## Features

- Bridge two or more Discord text/announcement channels in one group, including channels in different servers.
- Relay message text, author display name/avatar, embeds, and up to 10 file attachments per message.
- Mirror message text/embed edits and deletions while the bot is running.
- Prevent relay loops by ignoring bot and webhook messages.
- Disable user/role/`@everyone` mentions in relayed posts.
- Automatically create/reuse a `Chat Bridge` webhook where permissions allow; fall back to a normal bot message otherwise.
- Reload channel configuration without restarting the bot.
- No database, web server, or external bridge service required.

The bot keeps a bounded in-memory map of the most recent 5,000 source messages for edit/delete mirroring, so that tracking starts fresh after a bot restart and older messages may no longer be mirrored when edited/deleted. Reactions, voice, forum posts, threads as destination channels, and cross-platform bridges are not included.

## Requirements

- Python 3.10 or newer
- A Discord application/bot and permission to add it to the servers being bridged
- `View Channels`, `Send Messages`, `Embed Links`, and `Attach Files` in bridged channels
- `Manage Webhooks` in destination channels for webhook-style identity/avatar forwarding. Without it, messages use the bot's identity and include the sender's name.
- The **Message Content Intent** enabled both in the Developer Portal and in the bot code (already enabled by this project)

## Install

### Windows (PowerShell)

```powershell
cd Discord-Chat-Bridge-Python
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

### Linux

```bash
cd Discord-Chat-Bridge-Python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env .env
nano .env
```

Set `BOT_TOKEN` in `.env`. Do not commit or share `.env`; it contains your bot token. If the token has ever been published, reset it in the Discord Developer Portal before using it.

## Discord setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and select your application.
2. Under **Bot**, reset/copy the token and enable **Message Content Intent**.
3. Under **OAuth2 → URL Generator**, select the `bot` scope. Grant only the permissions needed above, plus `Manage Webhooks` if you want forwarded messages to use each sender's display name/avatar.
4. Use the generated URL to invite the bot to every server participating in a bridge.
5. Confirm the bot can view both ends of the bridge. Channel IDs are configured below.

## Configure channel bridges

Enable Developer Mode in Discord (**User Settings → Advanced → Developer Mode**), then right-click each channel and choose **Copy Channel ID**.

Edit `bridges.json`:

```json
{
  "bridges": [
    {
      "name": "Community Chat",
      "channels": [123456789012345678, 234567890123456789],
      "enabled": true,
      "show_source": true
    }
  ]
}
```

- `name`: a unique label for this bridge group.
- `channels`: two or more channel IDs. Every message in one channel is sent to every other channel in the same group.
- `enabled`: set to `false` to pause a group without deleting it.
- `show_source`: when `true`, adds the originating server and channel above the relayed content. Recommended for cross-server bridges.

Add more objects to `bridges` for independent groups. A channel may belong to only one enabled group, which avoids duplicate copies. The example `bridges.json` shipped with this project is disabled until you replace the example IDs and enable it.

If you keep the bot online while editing the file, run `.bridge reload` in a server where you have **Manage Server**. Or restart the bot.

## Run

```bash
python main.py
```

Expected startup log includes `Connected as ...` and the number of enabled groups/channels. Keep the terminal/session running; this is a self-hosted bot, not a hosted service.

## Commands

The default prefix is `.` and can be changed with `BOT_PREFIX` in `.env`.

| Command | Purpose | Access |
| --- | --- | --- |
| `.bridge help` | Show command help | Everyone |
| `.bridge ping` | Check bot responsiveness | Everyone |
| `.bridge status` | List enabled bridge groups | Everyone |
| `.bridge reload` | Reload `bridges.json` | Manage Server or configured bot owner |

Commands that are recognized by the bot are not relayed to the other channels.

## Troubleshooting

- **Bot is online but messages do not relay:** enable Message Content Intent in the Developer Portal, check the IDs in `bridges.json`, set the group to `"enabled": true`, and confirm the bot can view the source channel.
- **Forwarded messages use the bot's name instead of the sender's:** grant `Manage Webhooks` in destination channels. The bot falls back to a regular message if it cannot use a webhook.
- **A destination does not work:** check the logs for the channel ID and grant the bot `View Channel`, `Send Messages`, and (as needed) `Embed Links`/`Attach Files`.
- **Token error:** ensure `.env` contains `BOT_TOKEN=...` without placeholder text. Never paste the token into public chat or source control.
- **Invalid configuration:** `bridges.json` must be valid JSON, each enabled group needs at least two distinct positive channel IDs, names must be unique, and no channel can be in two enabled groups.

## Project layout

```text
Discord-Chat-Bridge-Python/
├── cogs/
│   ├── __init__.py
│   └── bridge.py
├── tests/
│   └── test_config.py
├── .env.example
├── .gitignore
├── bridges.json
├── config.py
├── main.py
└── requirements.txt
```

## Development checks

Run the configuration tests with:

```bash
python -m unittest discover -s tests -v
```
