from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import re
import ssl
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
WIN_MEDIA_DIRECTIVE_RE = re.compile(
    r"^\s*(?:СКРИН(?:ШОТ)?\s+ЗАНОСА|WIN(?:NER)?(?:_IMAGE|\s+IMAGE)?)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
WIN_MEDIA_PLACEHOLDER_RE = re.compile(
    r"^\s*\[\s*(?:СЮДА\s+КИДАЕМ\s+)?СКРИН(?:ШОТ)?\s+ЗАНОСА\s*\]\s*$",
    re.IGNORECASE,
)
CHANNEL_HEADER_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:КАНАЛ|KANAL|CHANNEL)\s+(\d+)\s*\*{0,2}\s*$",
    re.IGNORECASE,
)
POST_HEADER_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:\[\s*Через\s+([^\]]+)\s*\]\s*)?"
    r"Пост\s+(\d+)\s*:\s*\*{0,2}\s*(.*)$",
    re.IGNORECASE,
)
CHANNEL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?P<domain>kick\.com|twitch\.tv)/"
    r"(?P<slug>[A-Za-z0-9_][A-Za-z0-9_.-]*)(?:/)?"
    r"(?=$|[\s)\]}>.,!?;:])",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WIN_MEDIA_NAME_RE = re.compile(r"(?:^|[_\-.])(win|zanos|занос)(?:[_\-.]|$)", re.IGNORECASE)
DURATION_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)(?P<unit>s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?",
    re.IGNORECASE,
)
DELAY_PROFILES: dict[str, tuple[tuple[float, float, int], ...]] = {
    "uniform": (),
    "quick": (
        (30, 90, 6),
        (90, 3 * 60, 4),
    ),
    "mixed": (
        (2 * 60, 4 * 60, 5),
        (4 * 60, 6 * 60, 4),
        (6 * 60, 8 * 60, 1),
    ),
    "slow": (
        (5 * 60, 8 * 60, 4),
        (8 * 60, 12 * 60, 4),
        (12 * 60, 15 * 60, 2),
    ),
}

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
    "w8rkludobudka": 365,
    "propileros": 346,
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
    icheatbot_views_order: int | None = None
    icheatbot_reaction_order: int | None = None


@dataclass(frozen=True)
class PremiumEmoji:
    document_id: int
    alt: str


@dataclass(frozen=True)
class MessagePayload:
    body: str
    media_paths: tuple[Path, ...] = ()
    media_role: str | None = None


@dataclass(frozen=True)
class SequencedPayload:
    payload: MessagePayload
    sequence_index: int
    delay_after_previous: float = 0


@dataclass(frozen=True)
class PreparedPost:
    target: Target
    body: str
    original_body: str
    media_paths: tuple[Path, ...]
    auto_media_path: Path | None
    managed_media_paths: tuple[Path, ...]
    rotation_key: str
    sequence_index: int
    sequence_count: int
    delay_after_previous: float


@dataclass(frozen=True)
class ScheduledPost:
    post: PreparedPost
    offset_seconds: float


def parse_duration(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    if not text:
        raise argparse.ArgumentTypeError("Duration cannot be empty.")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)

    compact = re.sub(r"\s+", "", text)
    total = 0.0
    position = 0
    for match in DURATION_RE.finditer(compact):
        if match.start() != position:
            raise argparse.ArgumentTypeError(f"Invalid duration: {value!r}")
        position = match.end()
        number = float(match.group("number"))
        unit = (match.group("unit") or "s").casefold()
        if unit.startswith("h"):
            total += number * 60 * 60
        elif unit.startswith("m"):
            total += number * 60
        else:
            total += number

    if position != len(compact) or total <= 0:
        raise argparse.ArgumentTypeError(f"Invalid duration: {value!r}")
    return total


def parse_relative_duration(value: str) -> float:
    """Parse human timing used in headers such as '12 минут' or '1 час 5 минут'."""
    normalized = value.casefold().replace(",", ".").strip()
    replacements = (
        (r"\bчас(?:а|ов)?\b|\bч\b", "h"),
        (r"\bминут(?:а|ы)?\b|\bмин\b|\bм\b", "m"),
        (r"\bсекунд(?:а|ы)?\b|\bсек\b|\bс\b", "s"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", "", normalized)
    try:
        return parse_duration(normalized)
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(f"Invalid relative post delay: {value!r}") from exc


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def random_delay_for_profile(profile: str, delay_min: float, delay_max: float) -> float:
    if profile == "uniform":
        return random.uniform(delay_min, delay_max)

    buckets = DELAY_PROFILES[profile]
    weights = [bucket[2] for bucket in buckets]
    start, end, _weight = random.choices(buckets, weights=weights, k=1)[0]
    return random.uniform(start, end)


def build_delay_plan(args: argparse.Namespace, post_count: int) -> list[float]:
    if post_count <= 1:
        return []

    delays: list[float] = []
    for sent_count in range(1, post_count):
        if sent_count % args.delay_every == 0:
            delays.append(
                random_delay_for_profile(args.delay_profile, args.delay_min, args.delay_max)
            )
        else:
            delays.append(0)
    return delays


def build_scheduled_posts(
    args: argparse.Namespace,
    posts: Sequence[PreparedPost],
    owned_records: dict[int, dict[int, dict[str, object]]] | None = None,
) -> list[ScheduledPost]:
    if not posts:
        return []

    owned_records = owned_records or {}
    series: dict[int, list[PreparedPost]] = {}
    series_order: list[int] = []
    for post in posts:
        pid = utils.get_peer_id(post.target.entity)
        if pid not in series:
            series[pid] = []
            series_order.append(pid)
        series[pid].append(post)

    start_delays = build_delay_plan(args, len(series_order))
    start_offsets: dict[int, float] = {}
    current_offset = 0.0
    for index, pid in enumerate(series_order):
        if index > 0:
            current_offset += start_delays[index - 1]
        start_offsets[pid] = current_offset

    now_utc = datetime.now(timezone.utc)
    scheduled: list[tuple[float, int, int, ScheduledPost]] = []
    for order, pid in enumerate(series_order):
        previous_offset = start_offsets[pid]
        for post in sorted(series[pid], key=lambda item: item.sequence_index):
            offset = previous_offset
            if post.sequence_index > 1:
                previous_record = owned_records.get(pid, {}).get(post.sequence_index - 1)
                previous_sent_at = None
                if previous_record:
                    raw_sent_at = previous_record.get("sent_at")
                    if isinstance(raw_sent_at, str):
                        try:
                            previous_sent_at = datetime.fromisoformat(raw_sent_at)
                        except ValueError:
                            previous_sent_at = None
                if previous_sent_at is not None:
                    if previous_sent_at.tzinfo is None:
                        previous_sent_at = previous_sent_at.replace(tzinfo=timezone.utc)
                    due_at = previous_sent_at + timedelta(
                        seconds=post.delay_after_previous
                    )
                    offset = max(0.0, (due_at - now_utc).total_seconds())
                else:
                    offset = previous_offset + post.delay_after_previous
            item = ScheduledPost(post=post, offset_seconds=offset)
            scheduled.append((offset, order, post.sequence_index, item))
            previous_offset = offset

    return [item for _offset, _order, _sequence, item in sorted(scheduled)]


def print_scheduled_plan(posts: Sequence[ScheduledPost]) -> None:
    if not posts:
        return
    started_at = datetime.now()
    total_spread = max(item.offset_seconds for item in posts)
    print("\nTiming plan:")
    print(f"  total planned spread: {format_duration(total_spread)}")
    for index, item in enumerate(posts, start=1):
        post = item.post
        planned_at = started_at + timedelta(seconds=item.offset_seconds)
        print(
            f"[{index}/{len(posts)}] {planned_at:%Y-%m-%d %H:%M:%S} "
            f"(+{format_duration(item.offset_seconds)}) {post.target.title} "
            f"post {post.sequence_index}/{post.sequence_count}"
        )


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
        type=parse_duration,
        default=parse_duration(os.getenv("TG_DELAY_MIN", "2")),
        help="Minimum delay between posts. Accepts seconds, 10m, 1h. Default: 2s.",
    )
    parser.add_argument(
        "--delay-max",
        type=parse_duration,
        default=parse_duration(os.getenv("TG_DELAY_MAX", "6")),
        help="Maximum delay between posts. Accepts seconds, 10m, 1h. Default: 6s.",
    )
    parser.add_argument(
        "--delay-profile",
        choices=tuple(DELAY_PROFILES),
        default=os.getenv("TG_DELAY_PROFILE", "uniform"),
        help=(
            "Delay strategy between posts. "
            "uniform uses --delay-min/--delay-max; "
            "quick is mostly 30s-3m; mixed is 2-8m; slow is 5-15m. "
            "Default: uniform."
        ),
    )
    parser.add_argument(
        "--delay-every",
        type=int,
        default=int(os.getenv("TG_DELAY_EVERY", "1")),
        help=(
            "Wait only after every N posted channels. "
            "Use 2 to send two channels, then wait. Default: 1."
        ),
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
        "--skip-posted-today",
        action="store_true",
        help=(
            "Skip channels that already have a Telegram post today. "
            "The channel is checked during planning and again immediately before posting."
        ),
    )
    parser.add_argument(
        "--today-timezone",
        default=os.getenv("TG_TODAY_TIMEZONE", "Europe/Moscow"),
        help=(
            "Timezone used to decide what counts as today. "
            "Default: TG_TODAY_TIMEZONE or Europe/Moscow."
        ),
    )
    parser.add_argument(
        "--owned-posts-state",
        default=os.getenv("TG_OWNED_POSTS_STATE", "reports/autoposter_owned_posts.json"),
        help=(
            "Persistent JSON state used to recognize posts sent by this autoposter "
            "and resume multi-post series safely."
        ),
    )
    parser.add_argument(
        "--batch-id",
        help=(
            "Optional stable identifier for this posting batch. By default it is "
            "derived from today's date and the messages file contents."
        ),
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
    parser.add_argument(
        "--no-icheatbot",
        dest="no_icheatbot",
        action="store_true",
        default=True,
        help="Do not send automatic icheatbot API orders (current default).",
    )
    parser.add_argument(
        "--icheatbot",
        dest="no_icheatbot",
        action="store_false",
        help="Explicitly enable automatic icheatbot API orders for this run.",
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
        workspace_relative = path
        media_relative = media_dir / path
        path = workspace_relative if workspace_relative.exists() else media_relative
    return path


def payload_from_lines(lines: list[str], media_dir: Path, source_name: str) -> MessagePayload:
    body_lines: list[str] = []
    media_paths: list[Path] = []
    media_role: str | None = None

    for raw_line in lines:
        win_media_match = WIN_MEDIA_DIRECTIVE_RE.fullmatch(raw_line)
        if win_media_match:
            media_path = resolve_media_path(win_media_match.group(1), media_dir)
            if not media_path.exists():
                raise SystemExit(f"{source_name}: media file not found: {media_path}")
            media_paths.append(media_path)
            media_role = "win"
            continue
        match = MEDIA_DIRECTIVE_RE.fullmatch(raw_line)
        if match:
            media_path = resolve_media_path(match.group(1), media_dir)
            if not media_path.exists():
                raise SystemExit(f"{source_name}: media file not found: {media_path}")
            media_paths.append(media_path)
            continue
        if WIN_MEDIA_PLACEHOLDER_RE.fullmatch(raw_line):
            media_role = "win"
            continue
        body_lines.append(raw_line)

    body = "\n".join(body_lines).strip()
    if not body:
        raise SystemExit(f"{source_name}: message body is empty.")
    return MessagePayload(
        body=body,
        media_paths=tuple(media_paths),
        media_role=media_role,
    )


def read_message(path: str, media_dir: Path) -> MessagePayload:
    body = Path(path).read_text(encoding="utf-8").splitlines()
    return payload_from_lines(body, media_dir, path)


def split_channel_sequence(
    lines: list[str],
    media_dir: Path,
    source_name: str,
) -> tuple[SequencedPayload, ...]:
    headers = [index for index, line in enumerate(lines) if POST_HEADER_RE.fullmatch(line)]
    if not headers:
        return (
            SequencedPayload(
                payload=payload_from_lines(lines, media_dir, source_name),
                sequence_index=1,
            ),
        )

    preamble = lines[: headers[0]]
    if any(line.strip() for line in preamble):
        raise SystemExit(
            f"{source_name}: text before the first 'Пост N:' header is not allowed."
        )

    sequence: list[SequencedPayload] = []
    expected_index = 1
    for header_position, line_index in enumerate(headers):
        match = POST_HEADER_RE.fullmatch(lines[line_index])
        if match is None:
            continue
        delay_text, raw_index, first_line = match.groups()
        sequence_index = int(raw_index)
        if sequence_index != expected_index:
            raise SystemExit(
                f"{source_name}: expected Пост {expected_index}, got Пост {sequence_index}."
            )

        end_index = headers[header_position + 1] if header_position + 1 < len(headers) else len(lines)
        payload_lines = ([first_line] if first_line else []) + lines[line_index + 1 : end_index]
        delay = 0.0
        if sequence_index > 1 and delay_text:
            delay = parse_relative_duration(delay_text)
        sequence.append(
            SequencedPayload(
                payload=payload_from_lines(
                    payload_lines,
                    media_dir,
                    f"{source_name}: Пост {sequence_index}",
                ),
                sequence_index=sequence_index,
                delay_after_previous=delay,
            )
        )
        expected_index += 1

    return tuple(sequence)


def read_channel_messages(
    path: str,
    media_dir: Path,
) -> list[tuple[SequencedPayload, ...]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks: dict[int, list[str]] = {}
    current_index: int | None = None

    for raw_line in text.splitlines():
        match = CHANNEL_HEADER_RE.fullmatch(raw_line)
        if match:
            current_index = int(match.group(1))
            blocks.setdefault(current_index, [])
            continue
        if current_index is not None:
            blocks[current_index].append(raw_line)

    if not blocks:
        raise SystemExit("Messages file must contain blocks like 'КАНАЛ 1'.")

    messages: list[tuple[SequencedPayload, ...]] = []
    for index in sorted(blocks):
        messages.append(
            split_channel_sequence(
                blocks[index], media_dir, f"{path}: КАНАЛ {index}"
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
        if item.is_file()
        and item.suffix.casefold() in IMAGE_EXTENSIONS
        and WIN_MEDIA_NAME_RE.search(item.name) is None
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
    sequence_index: int = 1,
    sequence_count: int = 1,
    delay_after_previous: float = 0,
) -> None:
    link_note = "stream link replaced" if original_body != final_body else "no stream link change"
    if has_stream_link(original_body) and original_body == final_body:
        link_note = "stream link present, no channel mapping"

    media_note = ", ".join(path.name for path in media_paths) if media_paths else "no image"
    preview = final_body.replace("\n", " ")[:90]
    suffix = "..." if len(final_body) > 90 else ""
    sequence_note = ""
    if sequence_count > 1:
        sequence_note = f" | post {sequence_index}/{sequence_count}"
        if delay_after_previous > 0:
            sequence_note += f" | +{format_duration(delay_after_previous)}"
    print(f"[{index}/{total}] {target.title}{sequence_note}")
    print(f"  media: {media_note}")
    print(f"  links: {link_note}")
    print(f"  text: {preview}{suffix}")


def prepare_posts(
    targets: list[Target],
    body: MessagePayload | None,
    channel_messages: list[tuple[SequencedPayload, ...]],
    channel_links: dict[str, dict[str, str]],
    auto_media_by_channel: dict[str, Path],
    media_pool_dir: Path | None = None,
) -> list[PreparedPost]:
    prepared: list[PreparedPost] = []
    for index, target in enumerate(targets, start=1):
        if channel_messages:
            sequence = channel_messages[index - 1]
        elif body is not None:
            sequence = (SequencedPayload(payload=body, sequence_index=1),)
        else:
            raise SystemExit("No message body was loaded.")

        rotation_key = target_rotation_key(target)
        sequence_count = len(sequence)
        for item in sequence:
            current_payload = item.payload
            auto_media_path = None
            media_paths = current_payload.media_paths
            if current_payload.media_role == "win" and not media_paths:
                raise SystemExit(
                    f"{target.title}: Пост {item.sequence_index} requires a win "
                    "screenshot. Add 'СКРИН ЗАНОСА: <file>' to that post."
                )
            if (
                item.sequence_index == 1
                and not media_paths
                and current_payload.media_role is None
            ):
                auto_media_path = auto_media_by_channel.get(rotation_key)
                if auto_media_path is not None:
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
                    managed_media_paths=tuple(
                        media_path
                        for media_path in media_paths
                        if media_pool_dir is not None
                        and media_path.resolve().is_relative_to(media_pool_dir.resolve())
                    ),
                    rotation_key=rotation_key,
                    sequence_index=item.sequence_index,
                    sequence_count=sequence_count,
                    delay_after_previous=item.delay_after_previous,
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


async def latest_post_today(
    client: TelegramClient,
    target: Target,
    timezone: ZoneInfo,
) -> types.Message | None:
    """Return the newest real channel post from today, if one exists."""
    today = datetime.now(timezone).date()
    async for message in client.iter_messages(target.entity):
        if not isinstance(message, types.Message):
            continue
        message_date = getattr(message, "date", None)
        if message_date is None:
            continue
        local_date = message_date.astimezone(timezone).date()
        if local_date < today:
            return None
        if local_date == today:
            return message
    return None


async def posts_today_by_target(
    client: TelegramClient,
    targets: Sequence[Target],
    timezone: ZoneInfo,
) -> dict[int, types.Message]:
    found: dict[int, types.Message] = {}
    for target in targets:
        message = await latest_post_today(client, target, timezone)
        if message is not None:
            found[utils.get_peer_id(target.entity)] = message
    return found


def skipped_today_result(target: Target, message: types.Message, reason: str) -> PostResult:
    return PostResult(
        channel=target.title,
        message_id=message.id,
        link=post_link(target.entity, message.id),
        views=getattr(message, "views", None),
        static_id=None,
        reaction_id=None,
        random_views=None,
        random_reactions=None,
        status="skipped_today",
        error=reason,
    )


def make_batch_id(args: argparse.Namespace, timezone: ZoneInfo) -> str:
    if args.batch_id:
        return args.batch_id.strip()
    source_path = args.messages_file or args.message_file
    if not source_path:
        raise SystemExit("Cannot derive batch ID without a message file.")
    path = Path(source_path).resolve()
    digest = hashlib.sha256()
    digest.update(datetime.now(timezone).date().isoformat().encode("ascii"))
    digest.update(b"\0")
    digest.update(str(path).casefold().encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def load_owned_posts_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "batches": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"Invalid owned-posts state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid owned-posts state {path}: root must be an object.")
    if not isinstance(raw.get("batches"), dict):
        raw["batches"] = {}
    raw["version"] = 1
    return raw


def batch_channel_records(
    state: dict[str, object],
    batch_id: str,
) -> dict[int, dict[int, dict[str, object]]]:
    batches = state.get("batches")
    if not isinstance(batches, dict):
        return {}
    batch = batches.get(batch_id)
    if not isinstance(batch, dict):
        return {}
    channels = batch.get("channels")
    if not isinstance(channels, dict):
        return {}

    records: dict[int, dict[int, dict[str, object]]] = {}
    for raw_pid, raw_channel in channels.items():
        if not isinstance(raw_channel, dict):
            continue
        raw_posts = raw_channel.get("posts")
        if not isinstance(raw_posts, dict):
            continue
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            continue
        channel_posts: dict[int, dict[str, object]] = {}
        for raw_index, raw_post in raw_posts.items():
            if not isinstance(raw_post, dict):
                continue
            try:
                sequence_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            channel_posts[sequence_index] = raw_post
        if channel_posts:
            records[pid] = channel_posts
    return records


def save_owned_post(
    path: Path,
    state: dict[str, object],
    batch_id: str,
    timezone_name: str,
    post: PreparedPost,
    result: PostResult,
) -> None:
    if result.status != "posted" or result.message_id is None:
        return
    batches = state.setdefault("batches", {})
    if not isinstance(batches, dict):
        raise SystemExit("Owned-posts state has an invalid batches value.")
    batch = batches.setdefault(
        batch_id,
        {
            "created_at": datetime.now().astimezone().isoformat(),
            "timezone": timezone_name,
            "channels": {},
        },
    )
    if not isinstance(batch, dict):
        raise SystemExit(f"Owned-posts batch {batch_id} has an invalid value.")
    channels = batch.setdefault("channels", {})
    if not isinstance(channels, dict):
        raise SystemExit(f"Owned-posts batch {batch_id} has invalid channels.")
    pid = str(utils.get_peer_id(post.target.entity))
    channel = channels.setdefault(pid, {"title": post.target.title, "posts": {}})
    if not isinstance(channel, dict):
        raise SystemExit(f"Owned-posts channel {pid} has an invalid value.")
    posts = channel.setdefault("posts", {})
    if not isinstance(posts, dict):
        raise SystemExit(f"Owned-posts channel {pid} has invalid posts.")
    posts[str(post.sequence_index)] = {
        "message_id": result.message_id,
        "link": result.link,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


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


ICHEATBOT_API_URL = "https://icheatbot.com/api/v2"
ICHEATBOT_SSL_CTX = ssl.create_default_context()
ICHEATBOT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/x-www-form-urlencoded",
}


def icheatbot_add_order(
    api_key: str,
    service_id: int,
    link: str,
    quantity: int,
) -> int | None:
    """Place an order via icheatbot API. Returns the order ID or None on failure."""
    payload = urllib.parse.urlencode({
        "key": api_key,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity,
    }).encode()

    req = urllib.request.Request(
        ICHEATBOT_API_URL, data=payload, method="POST",
    )
    for header_name, header_value in ICHEATBOT_HEADERS.items():
        req.add_header(header_name, header_value)

    try:
        with urllib.request.urlopen(req, timeout=10, context=ICHEATBOT_SSL_CTX) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        print(f"  icheatbot API error: {exc}")
        return None

    if isinstance(result, dict) and "order" in result:
        return int(result["order"])

    error = result.get("error", result) if isinstance(result, dict) else result
    print(f"  icheatbot order rejected: {error}")
    return None


def icheatbot_place_orders(
    api_key: str,
    result: PostResult,
) -> None:
    """Place icheatbot orders for views and reactions on a successfully posted message."""
    if not api_key or result.status != "posted" or not result.link:
        return

    # Order views
    if result.static_id is not None and result.random_views is not None:
        order_id = icheatbot_add_order(
            api_key, result.static_id, result.link, result.random_views,
        )
        result.icheatbot_views_order = order_id
        if order_id:
            print(
                f"  icheatbot views: order #{order_id} "
                f"(service={result.static_id}, qty={result.random_views})"
            )

    # Order reactions
    if result.reaction_id is not None and result.random_reactions is not None:
        order_id = icheatbot_add_order(
            api_key, result.reaction_id, result.link, result.random_reactions,
        )
        result.icheatbot_reaction_order = order_id
        if order_id:
            print(
                f"  icheatbot reactions: order #{order_id} "
                f"(service={result.reaction_id}, qty={result.random_reactions})"
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
                "icheatbot_views_order",
                "icheatbot_reaction_order",
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
                    "icheatbot_views_order": (
                        "" if result.icheatbot_views_order is None
                        else result.icheatbot_views_order
                    ),
                    "icheatbot_reaction_order": (
                        "" if result.icheatbot_reaction_order is None
                        else result.icheatbot_reaction_order
                    ),
                }
            )


def write_copy_lines(path: Path, results: list[PostResult]) -> None:
    lines: list[str] = []
    for result in results:
        lines.extend(copy_friendly_lines(result))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_copy_lines(path: Path, result: PostResult) -> list[str]:
    lines = copy_friendly_lines(result)
    if not lines:
        return []

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as copy_file:
        copy_file.write("\n".join(lines) + "\n")
    return lines


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
    try:
        today_timezone = ZoneInfo(args.today_timezone)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"Unknown --today-timezone: {args.today_timezone}") from exc

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
    if args.delay_every < 1:
        raise SystemExit("--delay-every must be at least 1.")
    if args.delay_profile not in DELAY_PROFILES:
        choices = ", ".join(DELAY_PROFILES)
        raise SystemExit(f"--delay-profile must be one of: {choices}.")
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
    batch_id = make_batch_id(args, today_timezone)
    owned_posts_state_path = Path(args.owned_posts_state)
    owned_posts_state = load_owned_posts_state(owned_posts_state_path)
    owned_records = batch_channel_records(owned_posts_state, batch_id)
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
        if not targets:
            raise SystemExit("No matching channel targets found.")
        skipped_targets = [target for target in targets if target_should_skip_post(target)]
        post_targets = [target for target in targets if not target_should_skip_post(target)]

        if channel_messages and len(channel_messages) < len(targets):
            raise SystemExit(
                f"Messages file has {len(channel_messages)} block(s), "
                f"but {len(targets)} target(s) were matched."
            )

        posts_today: dict[int, types.Message] = {}
        skipped_today_targets: list[Target] = []
        resumed_targets: list[Target] = []
        if args.skip_posted_today:
            print(
                f"Checking {len(post_targets)} channel(s) for posts today "
                f"({args.today_timezone})..."
            )
            posts_today = await posts_today_by_target(
                client,
                post_targets,
                today_timezone,
            )
            resumed_targets = [
                target
                for target in post_targets
                if utils.get_peer_id(target.entity) in posts_today
                and utils.get_peer_id(target.entity) in owned_records
            ]
            skipped_today_targets = [
                target
                for target in post_targets
                if utils.get_peer_id(target.entity) in posts_today
                and utils.get_peer_id(target.entity) not in owned_records
            ]
            post_targets = [
                target
                for target in post_targets
                if utils.get_peer_id(target.entity) not in {
                    utils.get_peer_id(skipped.entity)
                    for skipped in skipped_today_targets
                }
            ]
        channel_links = load_channel_links(Path(args.channel_links), targets)
        media_pool_dir = Path(args.media_pool_dir)
        media_pool_dir.mkdir(parents=True, exist_ok=True)
        media_rotation_state_path = Path(args.media_rotation_state)
        media_rotation_state = load_media_rotation_state(media_rotation_state_path)
        explicitly_assigned_media = {
            media_path.resolve()
            for sequence in channel_messages
            for item in sequence
            for media_path in item.payload.media_paths
        }
        media_files = (
            []
            if args.no_auto_media
            else [
                media_path
                for media_path in list_media_pool_files(media_pool_dir)
                if media_path.resolve() not in explicitly_assigned_media
            ]
        )
        media_targets = [
            target
            for target in post_targets
            if 1 not in owned_records.get(utils.get_peer_id(target.entity), {})
        ]
        auto_media_by_channel = auto_media_assignments(
            media_targets,
            media_files,
            media_rotation_state,
        )
        all_prepared_posts = prepare_posts(
            targets,
            body,
            channel_messages,
            channel_links,
            auto_media_by_channel,
            media_pool_dir,
        )
        post_target_ids = {utils.get_peer_id(target.entity) for target in post_targets}
        prepared_posts = [
            post
            for post in all_prepared_posts
            if utils.get_peer_id(post.target.entity) in post_target_ids
            and post.sequence_index
            not in owned_records.get(utils.get_peer_id(post.target.entity), {})
        ]
        scheduled_posts = build_scheduled_posts(args, prepared_posts, owned_records)

        print(f"Batch ID: {batch_id}")
        print(f"Matched {len(prepared_posts)} pending post(s):")
        for post in prepared_posts:
            target = post.target
            print(
                f"- {target.title}: post {post.sequence_index}/{post.sequence_count}"
            )
        if skipped_targets:
            print("\nTemporarily skipped target(s):")
            for target in skipped_targets:
                print(f"- {target.title}")
        if skipped_today_targets:
            print(
                f"\nSkipped because a post already exists today "
                f"({args.today_timezone}):"
            )
            for target in skipped_today_targets:
                message = posts_today[utils.get_peer_id(target.entity)]
                timestamp = message.date.astimezone(today_timezone).strftime("%H:%M:%S")
                print(
                    f"- {target.title}: {timestamp} "
                    f"{post_link(target.entity, message.id)}"
                )
        if resumed_targets:
            print("\nContinuing series previously started by this autoposter:")
            for target in resumed_targets:
                completed = sorted(owned_records[utils.get_peer_id(target.entity)])
                print(f"- {target.title}: completed post(s) {completed}")
        print("\nPreview:")
        for index, post in enumerate(prepared_posts, start=1):
            preview_target(
                index,
                len(prepared_posts),
                post.target,
                post.original_body,
                post.body,
                post.media_paths,
                post.sequence_index,
                post.sequence_count,
                post.delay_after_previous,
            )
        if scheduled_posts:
            print_scheduled_plan(scheduled_posts)

        if args.dry_run:
            print("Dry run complete. No messages were posted.")
            return

        premium_emojis: list[PremiumEmoji] = []
        if prepared_posts and not args.no_premium_emoji:
            premium_emojis = await load_premium_emojis(client)
            if premium_emojis:
                print(f"Loaded {len(premium_emojis)} premium emoji candidate(s).")
            else:
                print("No premium emoji candidates found; posting plain text.")

        output_path = report_path(args.report)
        copy_output_path = copy_lines_path(output_path)
        copy_output_path.parent.mkdir(parents=True, exist_ok=True)
        copy_output_path.write_text("", encoding="utf-8")
        print(f"Live copy lines file: {copy_output_path.resolve()}")

        icheatbot_api_key = "" if args.no_icheatbot else os.getenv("ICHEATBOT_API_KEY", "")
        if icheatbot_api_key:
            print("icheatbot auto-ordering enabled")
        else:
            if not args.no_icheatbot:
                print("icheatbot auto-ordering disabled (no ICHEATBOT_API_KEY in .env)")

        results: list[PostResult] = [
            skipped_today_result(
                target,
                posts_today[utils.get_peer_id(target.entity)],
                f"A post already existed today in {args.today_timezone} during planning.",
            )
            for target in skipped_today_targets
        ]
        posted_auto_media_keys: list[str] = []
        posted_auto_media_paths: list[Path] = []
        skipped_series_ids: set[int] = set()
        failed_series_ids: set[int] = set()
        event_loop = asyncio.get_running_loop()
        schedule_started_at = event_loop.time()

        def register_success(post: PreparedPost, result: PostResult) -> None:
            results.append(result)
            save_owned_post(
                owned_posts_state_path,
                owned_posts_state,
                batch_id,
                args.today_timezone,
                post,
                result,
            )
            owned_records.clear()
            owned_records.update(batch_channel_records(owned_posts_state, batch_id))
            if icheatbot_api_key:
                icheatbot_place_orders(icheatbot_api_key, result)
            if result.status == "posted" and post.auto_media_path is not None:
                posted_auto_media_keys.append(post.rotation_key)
            if result.status == "posted" and post.managed_media_paths:
                posted_auto_media_paths.extend(post.managed_media_paths)

        pending_schedule = list(scheduled_posts)
        completed_schedule_items = 0
        while pending_schedule:
            for scheduled in list(pending_schedule):
                pid = utils.get_peer_id(scheduled.post.target.entity)
                if pid not in skipped_series_ids and pid not in failed_series_ids:
                    continue
                reason = "skipped" if pid in skipped_series_ids else "failed"
                print(
                    f"Skipping {scheduled.post.target.title} post "
                    f"{scheduled.post.sequence_index}: an earlier post in the "
                    f"series was {reason}."
                )
                pending_schedule.remove(scheduled)

            if not pending_schedule:
                break

            candidates: list[tuple[float, int, ScheduledPost]] = []
            now_monotonic = event_loop.time()
            now_utc = datetime.now(timezone.utc)
            for order, candidate in enumerate(pending_schedule):
                candidate_post = candidate.post
                candidate_pid = utils.get_peer_id(candidate_post.target.entity)
                if candidate_post.sequence_index == 1:
                    due_monotonic = schedule_started_at + candidate.offset_seconds
                else:
                    previous_record = owned_records.get(candidate_pid, {}).get(
                        candidate_post.sequence_index - 1
                    )
                    if previous_record is None:
                        continue
                    raw_sent_at = previous_record.get("sent_at")
                    if not isinstance(raw_sent_at, str):
                        continue
                    try:
                        previous_sent_at = datetime.fromisoformat(raw_sent_at)
                    except ValueError:
                        continue
                    if previous_sent_at.tzinfo is None:
                        previous_sent_at = previous_sent_at.replace(tzinfo=timezone.utc)
                    due_at = previous_sent_at + timedelta(
                        seconds=candidate_post.delay_after_previous
                    )
                    due_monotonic = now_monotonic + max(
                        0.0,
                        (due_at - now_utc).total_seconds(),
                    )
                candidates.append((due_monotonic, order, candidate))

            if not candidates:
                for scheduled in pending_schedule:
                    results.append(
                        PostResult(
                            channel=scheduled.post.target.title,
                            message_id=None,
                            link="",
                            views=None,
                            static_id=None,
                            reaction_id=None,
                            random_views=None,
                            random_reactions=None,
                            status="failed",
                            error="Previous post in the series was not recorded.",
                        )
                    )
                print("No remaining series post has a recorded predecessor; stopping.")
                break

            due_monotonic, _order, scheduled = min(candidates)
            pending_schedule.remove(scheduled)
            completed_schedule_items += 1
            index = completed_schedule_items
            post = scheduled.post
            pid = utils.get_peer_id(post.target.entity)
            remaining = due_monotonic - event_loop.time()
            if remaining > 0:
                print(
                    f"[{index}/{len(scheduled_posts)}] Waiting "
                    f"{format_duration(remaining)} for {post.target.title} "
                    f"post {post.sequence_index}/{post.sequence_count}..."
                )
                await asyncio.sleep(remaining)

            series_started_by_us = bool(owned_records.get(pid))
            if args.skip_posted_today and not series_started_by_us:
                existing_message = await latest_post_today(
                    client,
                    post.target,
                    today_timezone,
                )
                if existing_message is not None:
                    result = skipped_today_result(
                        post.target,
                        existing_message,
                        (
                            "A post appeared today after planning; skipped during "
                            "the final pre-send check."
                        ),
                    )
                    results.append(result)
                    skipped_series_ids.add(pid)
                    print(
                        f"[{index}/{len(scheduled_posts)}] Skipping "
                        f"{post.target.title} series: a post already exists today "
                        f"({result.link})"
                    )
                    continue
            try:
                print(
                    f"[{index}/{len(scheduled_posts)}] Posting to {post.target.title} "
                    f"(post {post.sequence_index}/{post.sequence_count})..."
                )
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
                register_success(post, result)
                print(f"  posted: {result.link}")
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
                    register_success(post, result)
                    print(f"  posted after wait: {result.link}")
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
                    failed_series_ids.add(pid)
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
                failed_series_ids.add(pid)
                print(f"  failed: {exc}")

            if results:
                live_copy_lines = append_copy_lines(copy_output_path, results[-1])
                if live_copy_lines:
                    print("  copy lines:")
                    for line in live_copy_lines:
                        print(f"  {line}")

        write_report(output_path, results)
        write_copy_lines(copy_output_path, results)
        if posted_auto_media_keys:
            mark_auto_media_used(
                media_rotation_state_path,
                media_rotation_state,
                posted_auto_media_keys,
            )
        if posted_auto_media_paths and not args.keep_used_media:
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
