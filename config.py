"""Environment settings and validated bridge configuration."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


class BridgeConfigError(ValueError):
    """Raised when bridges.json is malformed or unsafe to load."""


@dataclass(frozen=True)
class Settings:
    token: str
    prefix: str
    bridge_config_path: Path
    log_level: str
    owner_ids: frozenset[int]


@dataclass(frozen=True)
class BridgeGroup:
    name: str
    channels: tuple[int, ...]
    enabled: bool = True
    show_source: bool = True


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read settings from environment variables (normally populated by .env)."""
    env = os.environ if environ is None else environ
    token = env.get("BOT_TOKEN", "").strip()
    if not token or token.lower() in {"bot_token", "your_token_here", "put_your_bot_token_here", "your_bot_token_here", "changeme"}:
        raise RuntimeError(
            "BOT_TOKEN is missing. Copy .env to .env and add your bot token."
        )

    prefix = env.get("BOT_PREFIX", ".")
    if not prefix.strip():
        raise ValueError("BOT_PREFIX cannot be empty or whitespace-only.")
    if len(prefix) > 10:
        raise ValueError("BOT_PREFIX must be 10 characters or fewer.")

    raw_path = Path(env.get("BRIDGE_CONFIG", "bridges.json")).expanduser()
    config_path = raw_path if raw_path.is_absolute() else ROOT_DIR / raw_path

    raw_owners = env.get("BOT_OWNER_IDS", "")
    owner_ids: set[int] = set()
    for value in raw_owners.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            owner_id = int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid user ID in BOT_OWNER_IDS: {value!r}") from exc
        if owner_id <= 0:
            raise ValueError(f"User IDs in BOT_OWNER_IDS must be positive: {value!r}")
        owner_ids.add(owner_id)

    return Settings(
        token=token,
        prefix=prefix,
        bridge_config_path=config_path,
        log_level=env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        owner_ids=frozenset(owner_ids),
    )


def parse_bridge_config(document: Any) -> list[BridgeGroup]:
    """Validate bridge groups without making any Discord API calls."""
    if not isinstance(document, dict):
        raise BridgeConfigError("The top level of bridges.json must be a JSON object.")
    entries = document.get("bridges")
    if not isinstance(entries, list):
        raise BridgeConfigError("bridges.json must contain a 'bridges' array.")

    groups: list[BridgeGroup] = []
    enabled_channel_owner: dict[int, str] = {}
    seen_names: set[str] = set()

    for index, entry in enumerate(entries):
        where = f"bridges[{index}]"
        if not isinstance(entry, dict):
            raise BridgeConfigError(f"{where} must be an object.")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BridgeConfigError(f"{where}.name must be a non-empty string.")
        name = name.strip()
        if len(name) > 80:
            raise BridgeConfigError(f"{where}.name must be 80 characters or fewer.")
        if name.casefold() in seen_names:
            raise BridgeConfigError(f"Bridge group name {name!r} is duplicated.")
        seen_names.add(name.casefold())

        raw_channels = entry.get("channels")
        if not isinstance(raw_channels, list):
            raise BridgeConfigError(f"{where}.channels must be an array of channel IDs.")
        channels: list[int] = []
        for raw_id in raw_channels:
            if isinstance(raw_id, bool):
                raise BridgeConfigError(f"{where}.channels contains an invalid channel ID.")
            try:
                channel_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise BridgeConfigError(
                    f"{where}.channels contains an invalid channel ID: {raw_id!r}."
                ) from exc
            if channel_id <= 0:
                raise BridgeConfigError(
                    f"{where}.channels contains a non-positive channel ID: {raw_id!r}."
                )
            if channel_id not in channels:
                channels.append(channel_id)

        if len(channels) < 2:
            raise BridgeConfigError(
                f"{where}.channels needs at least two different channel IDs."
            )

        enabled = entry.get("enabled", True)
        show_source = entry.get("show_source", True)
        if not isinstance(enabled, bool):
            raise BridgeConfigError(f"{where}.enabled must be true or false.")
        if not isinstance(show_source, bool):
            raise BridgeConfigError(f"{where}.show_source must be true or false.")

        if enabled:
            for channel_id in channels:
                previous = enabled_channel_owner.get(channel_id)
                if previous is not None:
                    raise BridgeConfigError(
                        f"Channel ID {channel_id} is used by both {previous!r} and {name!r}. "
                        "Each channel can belong to only one enabled bridge group."
                    )
                enabled_channel_owner[channel_id] = name

        groups.append(
            BridgeGroup(
                name=name,
                channels=tuple(channels),
                enabled=enabled,
                show_source=show_source,
            )
        )
    return groups


def load_bridge_config(path: Path) -> list[BridgeGroup]:
    """Read and validate bridge groups from a JSON file."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError as exc:
        raise BridgeConfigError(
            f"Bridge config file not found: {path}. Recreate it using the example in README.md."
        ) from exc
    except json.JSONDecodeError as exc:
        raise BridgeConfigError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise BridgeConfigError(f"Could not read {path}: {exc}") from exc
    return parse_bridge_config(document)
