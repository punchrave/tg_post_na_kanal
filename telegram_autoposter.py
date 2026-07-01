from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv
from telethon import TelegramClient, functions, types, utils
from telethon.errors import FloodWaitError, RPCError


for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_STATIC_ID = 1806
DEFAULT_REACTION_FALLBACK_ID = 343
DEFAULT_PREMIUM_EMOJI_SEEDS = (
    "\U0001f525",
    "\U0001f4b8",
    "\u26a1",
    "\U0001f3c6",
    "\U0001f48e",
    "\U0001f3b0",
    "\U0001f680",
    "\u2728",
)
MEDIA_DIRECTIVE_RE = re.compile(
    r"^\s*(?:КАРТИНКА|ФОТО|IMAGE|PHOTO|MEDIA)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
CHANNEL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?P<domain>kick\.com|twitch\.tv)/"
    r"(?P<slug>[A-Za-z0-9_][A-Za-z0-9_.-]*)(?:/)?"
    r"(?=$|[\s)\]}>.,!?;:])",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# ASCII-safe emotion table. When the same emoji is listed more than once,
# the first ID from the supplied list is used.
EMOTION_MAP = {
    "\U0001f5ff": 349,  # moai
    "\U0001f4a9": 350,  # pile_of_poo
    "\U0001f44e": 351,  # thumbs_down
    "\U0001f494": 351,  # broken_heart
    "\U0001f389": 353,  # party_popper
    "\U0001f62d": 354,  # loudly_crying_face
    "\U0001f4af": 355,  # hundred_points
    "\U0001f974": 355,  # woozy_face
    "\U0001f601": 356,  # beaming_face_with_smiling_eyes
    "\U0001f923": 358,  # rolling_on_the_floor_laughing
    "\U0001f44f": 358,  # clapping_hands
    "\U0001f353": 360,  # strawberry
    "\U0001f631": 361,  # face_screaming_in_fear
    "\U0001f192": 9552,  # cool_button
    "\U0001f3c6": 9554,  # trophy
    "\u270d\ufe0f": 9555,  # writing_hand
    "\u270d": 9555,  # writing_hand without variation selector
    "\U0001f525": 340,  # fire
    "\U0001f44d": 341,  # thumbs_up
    "\U0001f64f": 341,  # folded_hands
    "\U0001f48b": 342,  # kiss_mark
    "\U0001f498": 342,  # heart_with_arrow
    "\u2764\ufe0f": 343,  # red_heart
    "\u2764": 343,  # red_heart without variation selector
    "\U0001f929": 345,  # star_struck
    "\U0001f44c": 346,  # ok_hand
    "\u26a1": 327,  # high_voltage
    "\U0001f4b8": 328,  # money_with_wings
    "\U0001f47b": 329,  # ghost
    "\U0001f91d": 332,  # handshake
    "\U0001f92e": 333,  # face_vomiting
    "\U0001f921": 333,  # clown_face
    "\U0001f92f": 333,  # exploding_head
    "\U0001f648": 9550,  # see_no_evil_monkey
    "\U0001f649": 9551,  # hear_no_evil_monkey
}

CHANNEL_REACTION_ID_OVERRIDES = {
    "timeslid": 328,
    "feerino": 365,
    "folsis1337": 328,
    "kryqen": 365,
    "jazzouthill": 365,
}

CHANNEL_REACTION_ID_SKIPS = {
    "filosovads",
    "saylowzol",
    "ufitou",
    "tilup1337",
}

CHANNEL_POST_SKIPS: set[str] = set()


@dataclass(frozen=True)
class Target:
    title: str
    entity: types.TypePeer


@dataclass
class PostResult:
    channel: str
    message_id: int | None
    link: str
    views: int | None
    static_id: int | None
    reaction_id: int | None
    random_views: int | None
    random_reactions: int | None
    status: str
    error: str = ""


@dataclass(frozen=True)
class PremiumEmoji:
    document_id: int
    alt: str


@dataclass(frozen=True)
class MessagePayload:
    body: str
    media_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PreparedPost:
    target: Target
    body: str
    original_body: str
    media_paths: tuple[Path, ...]
    auto_media_path: Path | None
    rotation_key: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post one Telegram message to every channel in a Telegram folder/filter."
    )
    parser.add_argument(
        "-m",
        "--message-file",
        help="Path to a UTF-8 text file containing the post body.",
    )
    parser.add_argument(
        "--messages-file",
        help=(
            "Path to a UTF-8 file with per-channel blocks like 'КАНАЛ 1', "
            "'КАНАЛ 2'. Blocks are matched to targets by folder order."
        ),
    )
    parser.add_argument(
        "--channel-links",
        default=os.getenv("TG_CHANNEL_LINKS_FILE", "channel_links.json"),
        help=(
            "JSON file with per-Telegram-channel Kick/Twitch links. "
            "Default: channel_links.json."
        ),
    )
    parser.add_argument(
        "--media-dir",
        default=os.getenv("TG_MEDIA_DIR", "media"),
        help="Base folder for images referenced in post blocks. Default: media.",
    )
    parser.add_argument(
        "--media-pool-dir",
        default=os.getenv("TG_MEDIA_POOL_DIR", "media_pool"),
        help=(
            "Folder with images that are rotated across channels automatically. "
            "Default: media_pool."
        ),
    )
    parser.add_argument(
        "--media-rotation-state",
        default=os.getenv("TG_MEDIA_ROTATION_STATE", "media_rotation_state.json"),
        help="JSON state file for automatic image rotation.",
    )
    parser.add_argument(
        "--used-media-dir",
        default=os.getenv("TG_USED_MEDIA_DIR", "media_used"),
        help="Folder where successfully posted pool images are archived.",
    )
    parser.add_argument(
        "--keep-used-media",
        action="store_true",
        help="Keep automatically used pool images in --media-pool-dir.",
    )
    parser.add_argument(
        "--no-auto-media",
        action="store_true",
        help="Do not automatically attach images from --media-pool-dir.",
    )
    parser.add_argument(
        "-f",
        "--folder",
        help="Telegram folder/filter title or numeric filter id. Can also be set via TG_FOLDER.",
    )
    parser.add_argument(
        "--channels-file",
        help=(
            "Optional fallback: UTF-8 file with one channel username/link/id per line. "
            "Blank lines and lines starting with # are ignored."
        ),
    )
    parser.add_argument(
        "--session",
        default=os.getenv("TG_SESSION", "telegram_autoposter"),
        help="Telethon session file name. Default: TG_SESSION or telegram_autoposter.",
    )
    parser.add_argument(
        "--parse-mode",
        choices=("md", "html", "none"),
        default=os.getenv("TG_PARSE_MODE", "md"),
        help="Message parse mode. Default: md.",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=float(os.getenv("TG_DELAY_MIN", "2")),
        help="Minimum delay between posts in seconds. Default: 2.",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=float(os.getenv("TG_DELAY_MAX", "6")),
        help="Maximum delay between posts in seconds. Default: 6.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Post only to the first N matched channels. Useful for testing.",
    )
    parser.add_argument(
        "--include-groups",
        action="store_true",
        help="Also post to megagroups/chats if they are present in the folder.",
    )
    parser.add_argument(
        "--no-link-preview",
        action="store_true",
        help="Disable Telegram link preview for the post.",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Send messages silently.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matched channels without posting.",
    )
    parser.add_argument(
        "--report",
        help="Output CSV report path. Default: reports/posted_YYYYMMDD_HHMMSS.csv.",
    )
    parser.add_argument(
        "--static-id",
        type=int,
        default=int(
            os.getenv(
                "TG_OUTPUT_STATIC_ID",
                os.getenv("TG_MONITOR_STATIC_ID", str(DEFAULT_STATIC_ID)),
            )
        ),
        help=(
            "Fixed ID for the first copy-friendly output line. "
            "Default: TG_OUTPUT_STATIC_ID, TG_MONITOR_STATIC_ID, or 1806."
        ),
    )
    parser.add_argument(
        "--reaction-fallback-id",
        type=int,
        default=int(
            os.getenv(
                "TG_REACTION_FALLBACK_ID",
                str(DEFAULT_REACTION_FALLBACK_ID),
            )
        ),
        help=(
            "Reaction ID when Telegram has no known reaction for the post/channel. "
            "Default: TG_REACTION_FALLBACK_ID or 343."
        ),
    )
    parser.add_argument(
        "--no-premium-emoji",
        action="store_true",
        help="Do not add random Telegram custom/premium emoji to posts.",
    )
    parser.add_argument(
        "--premium-emoji-min",
        type=int,
        default=int(os.getenv("TG_PREMIUM_EMOJI_MIN", "1")),
        help="Minimum random premium emoji placed before each post. Default: 1.",
    )
    parser.add_argument(
        "--premium-emoji-max",
        type=int,
        default=int(os.getenv("TG_PREMIUM_EMOJI_MAX", "3")),
        help="Maximum random premium emoji placed before each post. Default: 3.",
    )
    return parser.parse_args()


def env_int(name: str) -> int:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc


def resolve_media_path(raw_path: str, media_dir: Path) -> Path:
    value = raw_path.strip().strip('"').strip("'")
    path = Path(value)
    if not path.is_absolute():
        path = media_dir / path
    return path


def payload_from_lines(lines: list[str], media_dir: Path, source_name: str) -> MessagePayload:
    body_lines: list[str] = []
    media_paths: list[Path] = []

    for raw_line in lines:
        match = MEDIA_DIRECTIVE_RE.fullmatch(raw_line)
        if match:
            media_path = resolve_media_path(match.group(1), media_dir)
            if not media_path.exists():
                raise SystemExit(f"{source_name}: media file not found: {media_path}")
            media_paths.append(media_path)
            continue
        body_lines.append(raw_line)

    body = "\n".join(body_lines).strip()
    if not body:
        raise SystemExit(f"{source_name}: message body is empty.")
    return MessagePayload(body=body, media_paths=tuple(media_paths))


def read_message(path: str, media_dir: Path) -> MessagePayload:
    body = Path(path).read_text(encoding="utf-8").splitlines()
    return payload_from_lines(body, media_dir, path)


def read_channel_messages(path: str, media_dir: Path) -> list[MessagePayload]:
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks: dict[int, list[str]] = {}
    current_index: int | None = None

    for raw_line in text.splitlines():
        match = re.fullmatch(r"\s*(?:КАНАЛ|KANAL|CHANNEL)\s+(\d+)\s*", raw_line, re.IGNORECASE)
        if match:
            current_index = int(match.group(1))
            blocks.setdefault(current_index, [])
            continue
        if current_index is not None:
            blocks[current_index].append(raw_line)

    if not blocks:
        raise SystemExit("Messages file must contain blocks like 'КАНАЛ 1'.")

    messages: list[MessagePayload] = []
    for index in sorted(blocks):
        messages.append(
            payload_from_lines(
                blocks[index],
                media_dir,
                f"{path}: КАНАЛ {index}",
            )
        )

    return messages


def clean_int_list(value: str) -> list[int]:
    result: list[int] = []
    for item in re.split(r"[\s,;]+", value.strip()):
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def target_link_keys(target: Target) -> list[str]:
    keys: list[str] = []
    username = getattr(target.entity, "username", None)
    if username:
        keys.append(username.casefold())
    keys.append(target.title.casefold())
    return list(dict.fromkeys(keys))


def target_should_skip_post(target: Target) -> bool:
    return any(key in CHANNEL_POST_SKIPS for key in target_link_keys(target))


def target_rotation_key(target: Target) -> str:
    return target_link_keys(target)[0]


def list_media_pool_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix.casefold() in IMAGE_EXTENSIONS
    )


def load_media_rotation_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"cycle": 1, "used_channels": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"cycle": 1, "used_channels": []}

    cycle = raw.get("cycle", 1)
    used_channels = raw.get("used_channels", [])
    if not isinstance(cycle, int) or cycle < 1:
        cycle = 1
    if not isinstance(used_channels, list):
        used_channels = []

    return {
        "cycle": cycle,
        "used_channels": [
            item for item in used_channels if isinstance(item, str) and item
        ],
    }


def save_media_rotation_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def auto_media_assignments(
    targets: list[Target],
    media_files: Sequence[Path],
    state: dict[str, object],
) -> dict[str, Path]:
    if not targets or not media_files:
        return {}

    target_keys = [target_rotation_key(target) for target in targets]
    all_target_keys = set(target_keys)
    used_channels = {
        item
        for item in state.get("used_channels", [])
        if isinstance(item, str) and item in all_target_keys
    }
    if used_channels >= all_target_keys:
        state["cycle"] = int(state.get("cycle", 1)) + 1
        used_channels = set()
        state["used_channels"] = []

    available_targets = [
        target
        for target in targets
        if target_rotation_key(target) not in used_channels
    ]
    random.shuffle(available_targets)

    shuffled_media = list(media_files)
    random.shuffle(shuffled_media)

    assignment_count = min(len(available_targets), len(shuffled_media))
    return {
        target_rotation_key(target): media
        for target, media in zip(
            available_targets[:assignment_count],
            shuffled_media[:assignment_count],
        )
    }


def mark_auto_media_used(
    path: Path,
    state: dict[str, object],
    channel_keys: Iterable[str],
) -> None:
    used_channels = [
        item for item in state.get("used_channels", []) if isinstance(item, str)
    ]
    used_set = set(used_channels)
    for key in channel_keys:
        if key not in used_set:
            used_channels.append(key)
            used_set.add(key)
    state["used_channels"] = used_channels
    save_media_rotation_state(path, state)


def archive_used_media(media_paths: Iterable[Path], used_media_dir: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = used_media_dir / stamp
    moved_any = False

    for media_path in dict.fromkeys(media_paths):
        if not media_path.exists():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / media_path.name
        counter = 2
        while destination.exists():
            destination = target_dir / f"{media_path.stem}_{counter}{media_path.suffix}"
            counter += 1
        media_path.replace(destination)
        moved_any = True

    if moved_any:
        print(f"Archived used media to: {target_dir.resolve()}")


def normalize_channel_links(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for raw_key, raw_value in raw.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.casefold()
        if isinstance(raw_value, str):
            result[key] = {
                "kick": raw_value,
                "twitch": raw_value,
            }
            continue
        if not isinstance(raw_value, dict):
            continue

        links: dict[str, str] = {}
        for service in ("kick", "twitch"):
            value = raw_value.get(service)
            if isinstance(value, str) and value.strip():
                links[service] = value.strip()
        if links:
            result[key] = links

    return result


def create_channel_links_template(path: Path, targets: list[Target]) -> None:
    template: dict[str, dict[str, str]] = {}
    for target in targets:
        username = getattr(target.entity, "username", None)
        key = username or target.title
        template[key] = {
            "kick": "",
            "twitch": "",
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Created channel links template: {path.resolve()}")


def load_channel_links(path: Path, targets: list[Target]) -> dict[str, dict[str, str]]:
    if not path.exists():
        create_channel_links_template(path, targets)
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid channel links JSON {path}: {exc}") from exc

    return normalize_channel_links(raw)


def target_links(target: Target, channel_links: dict[str, dict[str, str]]) -> dict[str, str]:
    for key in target_link_keys(target):
        found = channel_links.get(key)
        if found:
            return found
    return {}


def replace_stream_links(body: str, target: Target, channel_links: dict[str, dict[str, str]]) -> str:
    links = target_links(target, channel_links)

    def replacement(match: re.Match[str]) -> str:
        domain = match.group("domain").casefold()
        service = "kick" if domain == "kick.com" else "twitch"
        if links.get(service):
            return links[service]
        if match.group("slug").casefold() == "yourlink":
            username = getattr(target.entity, "username", None)
            if username:
                return f"https://{domain}/{username}"
        return match.group(0)

    return CHANNEL_URL_RE.sub(replacement, body)


def has_stream_link(body: str) -> bool:
    return CHANNEL_URL_RE.search(body) is not None


def preview_target(
    index: int,
    total: int,
    target: Target,
    original_body: str,
    final_body: str,
    media_paths: Sequence[Path],
) -> None:
    link_note = "stream link replaced" if original_body != final_body else "no stream link change"
    if has_stream_link(original_body) and original_body == final_body:
        link_note = "stream link present, no channel mapping"

    media_note = ", ".join(path.name for path in media_paths) if media_paths else "no image"
    preview = final_body.replace("\n", " ")[:90]
    suffix = "..." if len(final_body) > 90 else ""
    print(f"[{index}/{total}] {target.title}")
    print(f"  media: {media_note}")
    print(f"  links: {link_note}")
    print(f"  text: {preview}{suffix}")


def prepare_posts(
    targets: list[Target],
    body: MessagePayload | None,
    channel_messages: list[MessagePayload],
    channel_links: dict[str, dict[str, str]],
    auto_media_by_channel: dict[str, Path],
) -> list[PreparedPost]:
    prepared: list[PreparedPost] = []
    for index, target in enumerate(targets, start=1):
        current_payload = channel_messages[index - 1] if channel_messages else body
        if current_payload is None:
            raise SystemExit("No message body was loaded.")

        rotation_key = target_rotation_key(target)
        auto_media_path = auto_media_by_channel.get(rotation_key)
        media_paths = current_payload.media_paths
        if not media_paths and auto_media_path is not None:
            media_paths = (auto_media_path,)

        final_body = replace_stream_links(
            current_payload.body,
            target,
            channel_links,
        )
        prepared.append(
            PreparedPost(
                target=target,
                body=final_body,
                original_body=current_payload.body,
                media_paths=tuple(media_paths),
                auto_media_path=auto_media_path,
                rotation_key=rotation_key,
            )
        )

    return prepared


def clean_lines(path: str) -> list[str]:
    lines: list[str] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def filter_title(dialog_filter: object) -> str:
    title = getattr(dialog_filter, "title", "")
    if hasattr(title, "text"):
        return str(title.text)
    return str(title)


def peer_id(value: object) -> int | None:
    try:
        return utils.get_peer_id(value)
    except Exception:
        return None


def unique_targets(targets: Iterable[Target]) -> list[Target]:
    seen: set[int] = set()
    result: list[Target] = []
    for target in targets:
        pid = peer_id(target.entity)
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        result.append(target)
    return result


def is_channel_target(entity: object, include_groups: bool) -> bool:
    if isinstance(entity, types.Channel):
        if getattr(entity, "broadcast", False):
            return True
        if include_groups and getattr(entity, "megagroup", False):
            return True
    if include_groups and isinstance(entity, types.Chat):
        return True
    return False


def automatic_filter_match(dialog_filter: object, entity: object) -> bool:
    if isinstance(entity, types.Channel):
        if getattr(dialog_filter, "broadcasts", False) and getattr(entity, "broadcast", False):
            return True
        if getattr(dialog_filter, "groups", False) and getattr(entity, "megagroup", False):
            return True

    if isinstance(entity, types.Chat):
        return bool(getattr(dialog_filter, "groups", False))

    if isinstance(entity, types.User):
        if getattr(dialog_filter, "bots", False) and getattr(entity, "bot", False):
            return True
        if getattr(dialog_filter, "contacts", False) and getattr(entity, "contact", False):
            return True
        if getattr(dialog_filter, "non_contacts", False) and not getattr(entity, "contact", False):
            return True

    return False


async def resolve_filter(client: TelegramClient, selector: str) -> object:
    response = await client(functions.messages.GetDialogFiltersRequest())
    filters = getattr(response, "filters", response)
    for dialog_filter in filters:
        if selector.isdigit() and str(getattr(dialog_filter, "id", "")) == selector:
            return dialog_filter
        if filter_title(dialog_filter).casefold() == selector.casefold():
            return dialog_filter

    available = [
        f"{getattr(item, 'id', '?')}: {filter_title(item) or '<untitled>'}"
        for item in filters
        if not isinstance(item, types.DialogFilterDefault)
    ]
    raise SystemExit(
        "Telegram folder/filter was not found. Available filters:\n"
        + ("\n".join(available) if available else "<none>")
    )


async def folder_targets(
    client: TelegramClient,
    selector: str,
    include_groups: bool,
) -> list[Target]:
    dialog_filter = await resolve_filter(client, selector)
    exclude_ids = {
        pid
        for pid in (peer_id(peer) for peer in getattr(dialog_filter, "exclude_peers", []))
        if pid is not None
    }

    manual_peers = list(getattr(dialog_filter, "pinned_peers", [])) + list(
        getattr(dialog_filter, "include_peers", [])
    )
    targets: list[Target] = []

    for input_peer in manual_peers:
        try:
            entity = await client.get_entity(input_peer)
        except RPCError as exc:
            print(f"Skipping unresolved peer from folder: {exc}")
            continue
        if peer_id(entity) not in exclude_ids and is_channel_target(entity, include_groups):
            targets.append(Target(title=utils.get_display_name(entity), entity=entity))

    if any(
        getattr(dialog_filter, flag, False)
        for flag in ("broadcasts", "groups", "bots", "contacts", "non_contacts")
    ):
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if peer_id(entity) in exclude_ids:
                continue
            if getattr(dialog_filter, "exclude_archived", False) and getattr(dialog, "folder_id", None):
                continue
            if getattr(dialog_filter, "exclude_read", False) and getattr(dialog, "unread_count", 0) == 0:
                continue
            if automatic_filter_match(dialog_filter, entity) and is_channel_target(entity, include_groups):
                targets.append(Target(title=dialog.name, entity=entity))

    return unique_targets(targets)


async def file_targets(
    client: TelegramClient,
    channels_file: str,
    include_groups: bool,
) -> list[Target]:
    targets: list[Target] = []
    for item in clean_lines(channels_file):
        try:
            entity = await client.get_entity(item)
        except RPCError as exc:
            print(f"Skipping {item}: {exc}")
            continue
        if is_channel_target(entity, include_groups):
            targets.append(Target(title=utils.get_display_name(entity), entity=entity))
        else:
            print(f"Skipping {item}: not a channel target")
    return unique_targets(targets)


def post_link(entity: object, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"

    pid = peer_id(entity)
    if pid is None:
        return ""
    raw = str(pid)
    if raw.startswith("-100"):
        raw = raw[4:]
    elif raw.startswith("-"):
        raw = raw[1:]
    return f"https://t.me/c/{raw}/{message_id}"


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def python_index_to_utf16_offset(value: str, index: int) -> int:
    return utf16_len(value[:index])


def shift_entities(
    entities: list[object],
    *,
    start_offset: int,
    delta: int,
) -> None:
    for entity in entities:
        offset = getattr(entity, "offset", None)
        if isinstance(offset, int) and offset >= start_offset:
            entity.offset = offset + delta


def insert_premium_emoji(
    message: str,
    entities: list[object],
    custom_entities: list[types.MessageEntityCustomEmoji],
    index: int,
    emoji: PremiumEmoji,
    *,
    before: str = "",
    after: str = " ",
) -> str:
    insert_text = f"{before}{emoji.alt}{after}"
    insert_offset = python_index_to_utf16_offset(message, index)
    emoji_offset = insert_offset + utf16_len(before)
    delta = utf16_len(insert_text)

    message = f"{message[:index]}{insert_text}{message[index:]}"
    shift_entities(entities, start_offset=insert_offset, delta=delta)
    shift_entities(custom_entities, start_offset=insert_offset, delta=delta)
    custom_entities.append(
        types.MessageEntityCustomEmoji(
            offset=emoji_offset,
            length=utf16_len(emoji.alt),
            document_id=emoji.document_id,
        )
    )
    return message


def custom_emoji_alt(document: types.Document) -> str:
    for attr in getattr(document, "attributes", []):
        if isinstance(attr, types.DocumentAttributeCustomEmoji):
            return getattr(attr, "alt", None) or "\u2728"
    return "\u2728"


def is_custom_emoji_document(document: object) -> bool:
    if not isinstance(document, types.Document):
        return False
    return any(
        isinstance(attr, types.DocumentAttributeCustomEmoji)
        for attr in getattr(document, "attributes", [])
    )


def unique_premium_emojis(emojis: Iterable[PremiumEmoji]) -> list[PremiumEmoji]:
    unique: list[PremiumEmoji] = []
    seen: set[int] = set()
    for emoji in emojis:
        if emoji.document_id in seen:
            continue
        seen.add(emoji.document_id)
        unique.append(emoji)
    return unique


async def premium_emoji_from_document_ids(
    client: TelegramClient,
    document_ids: Sequence[int],
) -> list[PremiumEmoji]:
    if not document_ids:
        return []

    try:
        documents = await client(
            functions.messages.GetCustomEmojiDocumentsRequest(
                document_id=list(document_ids)
            )
        )
    except RPCError as exc:
        print(f"Premium emoji lookup failed: {exc}")
        return []

    return [
        PremiumEmoji(document_id=document.id, alt=custom_emoji_alt(document))
        for document in documents
        if is_custom_emoji_document(document)
    ]


async def premium_emojis_from_pack(
    client: TelegramClient,
    short_name: str,
) -> list[PremiumEmoji]:
    try:
        response = await client(
            functions.messages.GetStickerSetRequest(
                stickerset=types.InputStickerSetShortName(short_name=short_name),
                hash=0,
            )
        )
    except RPCError as exc:
        print(f"Premium emoji pack lookup failed for {short_name}: {exc}")
        return []

    return [
        PremiumEmoji(document_id=document.id, alt=custom_emoji_alt(document))
        for document in getattr(response, "documents", [])
        if is_custom_emoji_document(document)
    ]


def input_sticker_set_from_set(sticker_set: object) -> types.TypeInputStickerSet | None:
    set_id = getattr(sticker_set, "id", None)
    access_hash = getattr(sticker_set, "access_hash", None)
    if isinstance(set_id, int) and isinstance(access_hash, int):
        return types.InputStickerSetID(id=set_id, access_hash=access_hash)

    short_name = getattr(sticker_set, "short_name", None)
    if isinstance(short_name, str) and short_name:
        return types.InputStickerSetShortName(short_name=short_name)

    return None


async def premium_emojis_from_account_packs(client: TelegramClient) -> list[PremiumEmoji]:
    try:
        response = await client(functions.messages.GetEmojiStickersRequest(hash=0))
    except RPCError as exc:
        print(f"Premium emoji account pack lookup failed: {exc}")
        return []

    sticker_sets = list(getattr(response, "sets", []) or [])
    random.shuffle(sticker_sets)

    emojis: list[PremiumEmoji] = []
    for sticker_set in sticker_sets:
        input_set = input_sticker_set_from_set(sticker_set)
        if input_set is None:
            continue
        try:
            full_set = await client(
                functions.messages.GetStickerSetRequest(
                    stickerset=input_set,
                    hash=0,
                )
            )
        except RPCError as exc:
            short_name = getattr(sticker_set, "short_name", "unknown")
            print(f"Premium emoji pack lookup failed for {short_name}: {exc}")
            continue

        emojis.extend(
            PremiumEmoji(document_id=document.id, alt=custom_emoji_alt(document))
            for document in getattr(full_set, "documents", [])
            if is_custom_emoji_document(document)
        )

    return unique_premium_emojis(emojis)


async def load_premium_emojis(client: TelegramClient) -> list[PremiumEmoji]:
    env_ids = clean_int_list(os.getenv("TG_PREMIUM_EMOJI_IDS", ""))
    if env_ids:
        return await premium_emoji_from_document_ids(client, env_ids)

    pack_names = [
        item.strip()
        for item in os.getenv("TG_PREMIUM_EMOJI_PACKS", "").split(",")
        if item.strip()
    ]
    pack_emojis = await premium_emojis_from_account_packs(client)
    for pack_name in pack_names:
        for emoji in await premium_emojis_from_pack(client, pack_name):
            pack_emojis.append(emoji)
    pack_emojis = unique_premium_emojis(pack_emojis)
    if pack_emojis:
        return pack_emojis

    seen: set[int] = set()
    document_ids: list[int] = []
    search_limit = int(os.getenv("TG_PREMIUM_EMOJI_SEARCH_LIMIT", "400"))
    seeds = [
        item.strip()
        for item in os.getenv("TG_PREMIUM_EMOJI_SEEDS", "").split(",")
        if item.strip()
    ] or list(DEFAULT_PREMIUM_EMOJI_SEEDS)

    for seed in seeds:
        try:
            result = await client(
                functions.messages.SearchCustomEmojiRequest(
                    emoticon=seed,
                    hash=0,
                )
            )
        except RPCError:
            continue
        for document_id in getattr(result, "document_id", []):
            if document_id in seen:
                continue
            seen.add(document_id)
            document_ids.append(document_id)
            if len(document_ids) >= search_limit:
                break
        if len(document_ids) >= search_limit:
            break

    return await premium_emoji_from_document_ids(client, document_ids)


def first_non_empty_line_start(message: str) -> int | None:
    cursor = 0
    for line in message.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped:
            return cursor + (len(line) - len(stripped))
        cursor += len(line)
    return None


def line_end_accent_candidates(message: str) -> list[int]:
    candidates: list[int] = []
    cursor = 0
    for line in message.splitlines(keepends=True):
        line_without_newline = line.rstrip("\r\n")
        stripped = line_without_newline.strip()
        if (
            len(stripped) >= 28
            and CHANNEL_URL_RE.search(line_without_newline) is None
            and re.search(r"[.!?…)\]]$", stripped)
        ):
            candidates.append(cursor + len(line_without_newline.rstrip()))
        cursor += len(line)
    return candidates


def premium_accent_plans(
    message: str,
    premium_emojis: Sequence[PremiumEmoji],
    min_count: int,
    max_count: int,
) -> list[tuple[int, PremiumEmoji, str, str]]:
    if not premium_emojis or max_count <= 0:
        return []

    min_count = max(0, min_count)
    max_count = max(min_count, max_count)
    candidates: list[tuple[int, str, str]] = []
    used_indexes: set[int] = set()

    def add_candidate(index: int, before: str, after: str) -> None:
        if index in used_indexes:
            return
        candidates.append((index, before, after))
        used_indexes.add(index)

    for match in CHANNEL_URL_RE.finditer(message):
        add_candidate(match.start(), "", " ")

    first_start = first_non_empty_line_start(message)
    if first_start is not None and CHANNEL_URL_RE.match(message, first_start) is None:
        add_candidate(first_start, "", " ")

    for index in line_end_accent_candidates(message):
        add_candidate(index, " ", "")

    if not candidates:
        return []

    count = random.randint(min_count, max_count)
    count = min(count, len(candidates))
    if count <= 0:
        return []

    random.shuffle(candidates)
    return [
        (index, random.choice(premium_emojis), before, after)
        for index, before, after in candidates[:count]
    ]


async def decorate_with_premium_emojis(
    client: TelegramClient,
    body: str,
    parse_mode: str | None,
    premium_emojis: Sequence[PremiumEmoji],
    min_count: int,
    max_count: int,
) -> tuple[str, list[object] | None, str | None]:
    if not premium_emojis:
        return body, None, parse_mode

    if parse_mode is None:
        message = body
        entities: list[object] = []
    else:
        message, parsed_entities = await client._parse_message_text(body, parse_mode)
        entities = list(parsed_entities or [])

    message = message.rstrip()
    custom_entities: list[types.MessageEntityCustomEmoji] = []

    plans = premium_accent_plans(
        message,
        premium_emojis,
        min_count,
        max_count,
    )

    for index, emoji, before, after in sorted(plans, key=lambda item: item[0], reverse=True):
        message = insert_premium_emoji(
            message,
            entities,
            custom_entities,
            index,
            emoji,
            before=before,
            after=after,
        )

    all_entities = entities + custom_entities
    all_entities.sort(key=lambda entity: getattr(entity, "offset", 0))
    return message, all_entities, None


def reaction_to_id(reaction: object) -> int | None:
    emoticon = getattr(reaction, "emoticon", None)
    if not emoticon:
        return None
    return EMOTION_MAP.get(emoticon)


def message_reaction_id(message: types.Message | None) -> int | None:
    if message is None:
        return None
    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None)
    if not results:
        return None

    top = max(results, key=lambda result: getattr(result, "count", 0))
    return reaction_to_id(getattr(top, "reaction", None))


def channel_reaction_override_id(target: Target) -> int | None:
    username = getattr(target.entity, "username", None)
    if username:
        found = CHANNEL_REACTION_ID_OVERRIDES.get(username.casefold())
        if found is not None:
            return found

    return CHANNEL_REACTION_ID_OVERRIDES.get(target.title.casefold())


def channel_reaction_should_skip(target: Target) -> bool:
    return any(key in CHANNEL_REACTION_ID_SKIPS for key in target_link_keys(target))


def random_reaction_count(reaction_id: int | None) -> int:
    if reaction_id == 365:
        return random.randint(70, 100)
    return random.randint(30, 50)


async def channel_reaction_id(
    client: TelegramClient,
    target: Target,
) -> int | None:
    try:
        if isinstance(target.entity, types.Channel):
            full = await client(functions.channels.GetFullChannelRequest(target.entity))
        elif isinstance(target.entity, types.Chat):
            full = await client(functions.messages.GetFullChatRequest(target.entity.id))
        else:
            return None
    except RPCError:
        return None

    available_reactions = getattr(getattr(full, "full_chat", None), "available_reactions", None)
    reaction_ids: list[int] = []
    for reaction in getattr(available_reactions, "reactions", []) or []:
        found = reaction_to_id(reaction)
        if found is not None and found not in reaction_ids:
            reaction_ids.append(found)

    if reaction_ids:
        return reaction_ids[0]
    return None


async def post_one(
    client: TelegramClient,
    target: Target,
    body: str,
    media_paths: Sequence[Path],
    parse_mode: str | None,
    no_link_preview: bool,
    silent: bool,
    static_id: int,
    reaction_fallback_id: int,
    premium_emojis: Sequence[PremiumEmoji],
    premium_emoji_min: int,
    premium_emoji_max: int,
) -> PostResult:
    message_body, formatting_entities, effective_parse_mode = (
        await decorate_with_premium_emojis(
            client,
            body,
            parse_mode,
            premium_emojis,
            premium_emoji_min,
            premium_emoji_max,
        )
    )
    if media_paths:
        sent_result = await client.send_file(
            target.entity,
            [str(path) for path in media_paths],
            caption=message_body,
            parse_mode=effective_parse_mode,
            formatting_entities=formatting_entities,
            silent=silent,
        )
        sent = sent_result[0] if isinstance(sent_result, list) else sent_result
    else:
        sent = await client.send_message(
            target.entity,
            message_body,
            parse_mode=effective_parse_mode,
            formatting_entities=formatting_entities,
            link_preview=not no_link_preview,
            silent=silent,
        )
    message = await client.get_messages(target.entity, ids=sent.id)
    views = getattr(message, "views", None)
    if channel_reaction_should_skip(target):
        reaction_id = None
    else:
        reaction_id = (
            channel_reaction_override_id(target)
            or message_reaction_id(message)
            or await channel_reaction_id(client, target)
            or reaction_fallback_id
        )
    return PostResult(
        channel=target.title,
        message_id=sent.id,
        link=post_link(target.entity, sent.id),
        views=views,
        static_id=static_id,
        reaction_id=reaction_id,
        random_views=random.randint(2200, 2800),
        random_reactions=random_reaction_count(reaction_id),
        status="posted",
    )


def report_path(value: str | None) -> Path:
    if value:
        return Path(value)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("reports") / f"posted_{stamp}.csv"


def copy_lines_path(report_csv_path: Path) -> Path:
    name = report_csv_path.stem
    if name.startswith("posted_"):
        name = "copy_" + name.removeprefix("posted_")
    else:
        name = name + "_copy"
    return report_csv_path.with_name(f"{name}.txt")


def write_report(path: Path, results: list[PostResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=(
                "channel",
                "message_id",
                "link",
                "views",
                "static_id",
                "reaction_id",
                "random_views",
                "random_reactions",
                "status",
                "error",
            ),
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "channel": result.channel,
                    "message_id": result.message_id or "",
                    "link": result.link,
                    "views": "" if result.views is None else result.views,
                    "static_id": "" if result.static_id is None else result.static_id,
                    "reaction_id": "" if result.reaction_id is None else result.reaction_id,
                    "random_views": "" if result.random_views is None else result.random_views,
                    "random_reactions": (
                        "" if result.random_reactions is None else result.random_reactions
                    ),
                    "status": result.status,
                    "error": result.error,
                }
            )


def write_copy_lines(path: Path, results: list[PostResult]) -> None:
    lines: list[str] = []
    for result in results:
        lines.extend(copy_friendly_lines(result))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def copy_friendly_lines(result: PostResult) -> list[str]:
    if (
        result.status != "posted"
        or not result.link
        or result.static_id is None
        or result.random_views is None
    ):
        return []

    lines = [f"{result.static_id} | {result.link} | {result.random_views}"]
    if result.reaction_id is not None and result.random_reactions is not None:
        lines.append(f"{result.reaction_id} | {result.link} | {result.random_reactions}")
    return lines


async def amain() -> None:
    load_dotenv()
    args = parse_args()

    api_id = env_int("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_hash:
        raise SystemExit("Missing required environment variable: TG_API_HASH")

    folder = args.folder
    if folder is None and not args.channels_file:
        folder = os.getenv("TG_FOLDER")
    if not folder and not args.channels_file:
        raise SystemExit("Set --folder/TG_FOLDER or provide --channels-file.")

    if args.delay_min < 0 or args.delay_max < 0:
        raise SystemExit("Delay values must be non-negative.")
    if args.delay_max < args.delay_min:
        raise SystemExit("--delay-max must be greater than or equal to --delay-min.")
    if args.premium_emoji_min < 0 or args.premium_emoji_max < 0:
        raise SystemExit("Premium emoji counts must be non-negative.")
    if args.premium_emoji_max < args.premium_emoji_min:
        raise SystemExit("--premium-emoji-max must be greater than or equal to --premium-emoji-min.")

    if not args.message_file and not args.messages_file:
        raise SystemExit("Set --message-file or --messages-file.")

    media_dir = Path(args.media_dir)
    body = read_message(args.message_file, media_dir) if args.message_file else None
    channel_messages = (
        read_channel_messages(args.messages_file, media_dir) if args.messages_file else []
    )
    parse_mode = None if args.parse_mode == "none" else args.parse_mode

    client = TelegramClient(args.session, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            phone = os.getenv("TG_PHONE")
            if phone:
                await client.start(phone=phone)
            else:
                await client.start(
                    phone=lambda: input(
                        "Enter your Telegram phone number, including country code: "
                    ).strip()
                )

        targets: list[Target] = []
        if folder:
            targets.extend(await folder_targets(client, folder, args.include_groups))
        if args.channels_file:
            targets.extend(await file_targets(client, args.channels_file, args.include_groups))
        targets = unique_targets(targets)
        if args.limit:
            targets = targets[: args.limit]
        skipped_targets = [target for target in targets if target_should_skip_post(target)]
        post_targets = [target for target in targets if not target_should_skip_post(target)]

        if not post_targets:
            raise SystemExit("No matching channel targets found.")

        if channel_messages and len(channel_messages) < len(targets):
            raise SystemExit(
                f"Messages file has {len(channel_messages)} block(s), "
                f"but {len(targets)} target(s) were matched."
            )
        channel_links = load_channel_links(Path(args.channel_links), targets)
        media_pool_dir = Path(args.media_pool_dir)
        media_pool_dir.mkdir(parents=True, exist_ok=True)
        media_rotation_state_path = Path(args.media_rotation_state)
        media_rotation_state = load_media_rotation_state(media_rotation_state_path)
        media_files = [] if args.no_auto_media else list_media_pool_files(media_pool_dir)
        auto_media_by_channel = auto_media_assignments(
            post_targets,
            media_files,
            media_rotation_state,
        )
        all_prepared_posts = prepare_posts(
            targets,
            body,
            channel_messages,
            channel_links,
            auto_media_by_channel,
        )
        prepared_posts = [
            post for post in all_prepared_posts if not target_should_skip_post(post.target)
        ]

        print(f"Matched {len(prepared_posts)} target(s):")
        for post in prepared_posts:
            target = post.target
            print(f"- {target.title}")
        if skipped_targets:
            print("\nTemporarily skipped target(s):")
            for target in skipped_targets:
                print(f"- {target.title}")
        print("\nPreview:")
        for index, post in enumerate(prepared_posts, start=1):
            preview_target(
                index,
                len(prepared_posts),
                post.target,
                post.original_body,
                post.body,
                post.media_paths,
            )

        if args.dry_run:
            print("Dry run complete. No messages were posted.")
            return

        premium_emojis: list[PremiumEmoji] = []
        if not args.no_premium_emoji:
            premium_emojis = await load_premium_emojis(client)
            if premium_emojis:
                print(f"Loaded {len(premium_emojis)} premium emoji candidate(s).")
            else:
                print("No premium emoji candidates found; posting plain text.")

        results: list[PostResult] = []
        posted_auto_media_keys: list[str] = []
        posted_auto_media_paths: list[Path] = []
        for index, post in enumerate(prepared_posts, start=1):
            try:
                print(f"[{index}/{len(prepared_posts)}] Posting to {post.target.title}...")
                result = await post_one(
                    client,
                    post.target,
                    post.body,
                    post.media_paths,
                    parse_mode,
                    args.no_link_preview,
                    args.silent,
                    args.static_id,
                    args.reaction_fallback_id,
                    premium_emojis,
                    args.premium_emoji_min,
                    args.premium_emoji_max,
                )
                results.append(result)
                print(f"  posted: {result.link}")
                if result.status == "posted" and post.auto_media_path is not None:
                    posted_auto_media_keys.append(post.rotation_key)
                    posted_auto_media_paths.append(post.auto_media_path)
            except FloodWaitError as exc:
                wait_seconds = int(exc.seconds) + 2
                print(f"  Telegram flood wait: sleeping {wait_seconds}s")
                await asyncio.sleep(wait_seconds)
                try:
                    result = await post_one(
                        client,
                        post.target,
                        post.body,
                        post.media_paths,
                        parse_mode,
                        args.no_link_preview,
                        args.silent,
                        args.static_id,
                        args.reaction_fallback_id,
                        premium_emojis,
                        args.premium_emoji_min,
                        args.premium_emoji_max,
                    )
                    results.append(result)
                    print(f"  posted after wait: {result.link}")
                    if result.status == "posted" and post.auto_media_path is not None:
                        posted_auto_media_keys.append(post.rotation_key)
                        posted_auto_media_paths.append(post.auto_media_path)
                except Exception as retry_exc:
                    results.append(
                        PostResult(
                            channel=post.target.title,
                            message_id=None,
                            link="",
                            views=None,
                            static_id=None,
                            reaction_id=None,
                            random_views=None,
                            random_reactions=None,
                            status="failed",
                            error=str(retry_exc),
                        )
                    )
                    print(f"  failed after wait: {retry_exc}")
            except Exception as exc:
                results.append(
                    PostResult(
                        channel=post.target.title,
                        message_id=None,
                        link="",
                        views=None,
                        static_id=None,
                        reaction_id=None,
                        random_views=None,
                        random_reactions=None,
                        status="failed",
                        error=str(exc),
                    )
                )
                print(f"  failed: {exc}")

            if index < len(prepared_posts):
                delay = random.uniform(args.delay_min, args.delay_max)
                await asyncio.sleep(delay)

        output_path = report_path(args.report)
        write_report(output_path, results)
        copy_output_path = copy_lines_path(output_path)
        write_copy_lines(copy_output_path, results)
        if posted_auto_media_keys:
            mark_auto_media_used(
                media_rotation_state_path,
                media_rotation_state,
                posted_auto_media_keys,
            )
            if not args.keep_used_media:
                archive_used_media(posted_auto_media_paths, Path(args.used_media_dir))
        print(f"\nCSV report: {output_path.resolve()}")
        print(f"Copy lines file: {copy_output_path.resolve()}")
        print("\nCopy-friendly lines:")
        for result in results:
            for line in copy_friendly_lines(result):
                print(line)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(amain())
