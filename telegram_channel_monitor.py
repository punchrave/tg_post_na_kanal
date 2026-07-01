from __future__ import annotations

import sys

# Force UTF-8 output so emoji don't crash on Windows cp1251 console.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

"""
telegram_channel_monitor.py
----------------------------
Мониторит все каналы из Telegram-папки (TG_FOLDER) и при каждом новом посте
выводит две строки:

    {static_id} {emotion_id} {post_link} {rand_views}       <- 2200-2800
    {static_id} {emotion_id} {post_link} {rand_reactions}   <- 30-50, для 365: 70-100

Эмоция определяется по топ-реакции поста (если реакций нет - fallback_id).

Использование:
    python telegram_channel_monitor.py
    python telegram_channel_monitor.py --last 3

Параметры через .env:
    TG_FOLDER=KICKI
    TG_MONITOR_STATIC_ID=1806
    TG_MONITOR_POLL=15
    TG_MONITOR_FALLBACK_ID=343
"""

import argparse
import asyncio
import os
import random
from datetime import date, datetime

from dotenv import load_dotenv
from telethon import TelegramClient, functions, types
from telethon import utils as tg_utils
from telethon.errors import RPCError

# ---------------------------------------------------------------------------
# Таблица эмоций: emoji -> ID
# ---------------------------------------------------------------------------
EMOTION_MAP: dict[str, int] = {
    "🗿": 349,
    "💩": 350,
    "👎": 351,
    "💔": 351,
    "🎉": 353,
    "😭": 354,
    "💯": 355,
    "🥴": 355,
    "😁": 356,
    "🤣": 358,
    "👏": 358,
    "🍓": 360,
    "😱": 361,
    "🆒": 9552,
    "🏆": 9554,
    "✍️": 9555,
    "✍": 9555,
    "🔥": 340,
    "👍": 341,
    "🙏": 341,
    "💋": 342,
    "💘": 342,
    "❤️": 343,
    "❤": 343,
    "🤩": 345,
    "👌": 346,
    "⚡": 327,
    "💸": 328,
    "👻": 329,
    "🤝": 332,
    "🤮": 333,
    "🤡": 333,
    "🤯": 333,
    "🙈": 9550,
    "🙉": 9551,
}

DEFAULT_FALLBACK_ID = 343

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


def log(message: str = "") -> None:
    print(message, file=sys.stderr)


def env_int(name: str, default: int | None = None) -> int:
    value = os.getenv(name)
    if not value:
        if default is not None:
            return default
        raise SystemExit(f"Missing env var: {name}")
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be integer") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor a Telegram folder for new posts."
    )
    parser.add_argument(
        "--folder",
        default=os.getenv("TG_FOLDER"),
        help="Telegram folder title or numeric id. Env: TG_FOLDER.",
    )
    parser.add_argument(
        "--static-id",
        type=int,
        default=None,
        help="Fixed ID on every output line. Env: TG_MONITOR_STATIC_ID.",
    )
    parser.add_argument(
        "--poll",
        type=int,
        default=int(os.getenv("TG_MONITOR_POLL", "15")),
        help="Poll interval in seconds (default: 15). Env: TG_MONITOR_POLL.",
    )
    parser.add_argument(
        "--fallback-id",
        type=int,
        default=int(os.getenv("TG_MONITOR_FALLBACK_ID", str(DEFAULT_FALLBACK_ID))),
        help=f"Emotion ID when no reactions (default: {DEFAULT_FALLBACK_ID}). Env: TG_MONITOR_FALLBACK_ID.",
    )
    parser.add_argument(
        "--session",
        default=os.getenv("TG_SESSION", "telegram_autoposter"),
        help="Telethon session file name.",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=0,
        help="Show last N posts per channel on startup (0 = new only).",
    )
    parser.add_argument(
        "--today",
        action="store_true",
        help="Show all posts from today on startup.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after printing startup posts from --today or --last.",
    )
    parser.add_argument(
        "--include-groups",
        action="store_true",
        help="Also monitor megagroups/chats in folder.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Folder resolution (same logic as telegram_autoposter.py)
# ---------------------------------------------------------------------------

def filter_title(dialog_filter: object) -> str:
    title = getattr(dialog_filter, "title", "")
    if hasattr(title, "text"):
        return str(title.text)
    return str(title)


def peer_id_safe(value: object) -> int | None:
    try:
        return tg_utils.get_peer_id(value)
    except Exception:
        return None


def is_channel_target(entity: object, include_groups: bool) -> bool:
    if isinstance(entity, types.Channel):
        if getattr(entity, "broadcast", False):
            return True
        if include_groups and getattr(entity, "megagroup", False):
            return True
    if include_groups and isinstance(entity, types.Chat):
        return True
    return False


async def resolve_folder_targets(
    client: TelegramClient, selector: str, include_groups: bool
) -> list[tuple[str, object]]:
    response = await client(functions.messages.GetDialogFiltersRequest())
    filters = getattr(response, "filters", response)

    dialog_filter = None
    for f in filters:
        if selector.isdigit() and str(getattr(f, "id", "")) == selector:
            dialog_filter = f
            break
        if filter_title(f).casefold() == selector.casefold():
            dialog_filter = f
            break

    if dialog_filter is None:
        available = [
            f"{getattr(item, 'id', '?')}: {filter_title(item) or '<untitled>'}"
            for item in filters
            if not isinstance(item, types.DialogFilterDefault)
        ]
        raise SystemExit(
            "Folder not found. Available:\n" + ("\n".join(available) if available else "<none>")
        )

    exclude_ids = {
        pid
        for pid in (peer_id_safe(p) for p in getattr(dialog_filter, "exclude_peers", []))
        if pid is not None
    }

    seen: set[int] = set()
    targets: list[tuple[str, object]] = []

    manual = list(getattr(dialog_filter, "pinned_peers", [])) + list(
        getattr(dialog_filter, "include_peers", [])
    )
    for input_peer in manual:
        try:
            entity = await client.get_entity(input_peer)
        except RPCError as exc:
            log(f"  Skipping unresolved peer: {exc}")
            continue
        pid = peer_id_safe(entity)
        if pid in exclude_ids or pid in seen:
            continue
        if is_channel_target(entity, include_groups):
            seen.add(pid)
            targets.append((tg_utils.get_display_name(entity), entity))

    auto_flags = ("broadcasts", "groups", "bots", "contacts", "non_contacts")
    if any(getattr(dialog_filter, flag, False) for flag in auto_flags):
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            pid = peer_id_safe(entity)
            if pid in exclude_ids or pid in seen:
                continue
            if getattr(dialog_filter, "exclude_archived", False) and getattr(dialog, "folder_id", None):
                continue
            if is_channel_target(entity, include_groups):
                seen.add(pid)
                targets.append((dialog.name, entity))

    return targets


# ---------------------------------------------------------------------------
# Post helpers
# ---------------------------------------------------------------------------

def build_post_link(entity: object, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    try:
        pid = str(tg_utils.get_peer_id(entity))
    except Exception:
        return ""
    if pid.startswith("-100"):
        pid = pid[4:]
    elif pid.startswith("-"):
        pid = pid[1:]
    return f"https://t.me/c/{pid}/{message_id}"


def detect_emotion_id(message: types.Message, fallback_id: int) -> int:
    reactions = getattr(message, "reactions", None)
    if reactions is None:
        return fallback_id
    results = getattr(reactions, "results", [])
    if not results:
        return fallback_id
    top = max(results, key=lambda r: getattr(r, "count", 0))
    reaction = getattr(top, "reaction", None)
    if reaction is None:
        return fallback_id
    emoticon = getattr(reaction, "emoticon", None)
    if emoticon:
        found = EMOTION_MAP.get(emoticon)
        if found is not None:
            return found
    return fallback_id


def channel_reaction_override_id(channel_name: str, entity: object) -> int | None:
    username = getattr(entity, "username", None)
    if username:
        found = CHANNEL_REACTION_ID_OVERRIDES.get(username.casefold())
        if found is not None:
            return found
    return CHANNEL_REACTION_ID_OVERRIDES.get(channel_name.casefold())


def channel_reaction_should_skip(channel_name: str, entity: object) -> bool:
    username = getattr(entity, "username", None)
    if username and username.casefold() in CHANNEL_REACTION_ID_SKIPS:
        return True
    return channel_name.casefold() in CHANNEL_REACTION_ID_SKIPS


def random_reaction_count(emotion_id: int | None) -> int:
    if emotion_id == 365:
        return random.randint(70, 100)
    return random.randint(30, 50)


def message_local_date(message: types.Message) -> date | None:
    if not getattr(message, "date", None):
        return None
    return message.date.astimezone().date()


def print_post(
    static_id: int,
    channel_name: str,
    entity: object,
    message: types.Message,
    fallback_id: int,
) -> None:
    link = build_post_link(entity, message.id)
    emotion_id = None
    if not channel_reaction_should_skip(channel_name, entity):
        emotion_id = (
            channel_reaction_override_id(channel_name, entity)
            or detect_emotion_id(message, fallback_id)
        )

    timestamp = ""
    if hasattr(message, "date") and message.date:
        ts = message.date.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        timestamp = f" [{ts}]"

    text_preview = ""
    if message.text:
        preview = message.text[:50].replace("\n", " ")
        suffix = "..." if len(message.text) > 50 else ""
        text_preview = f" | {preview}{suffix}"

    rand_views = random.randint(2200, 2800)
    rand_react = random_reaction_count(emotion_id)

    sep = "-" * 64
    log(f"{sep}")
    log(f"[{channel_name}] Post #{message.id}{timestamp}{text_preview}")
    print(f"{static_id} | {link} | {rand_views}")
    if emotion_id is not None:
        print(f"{emotion_id} | {link} | {rand_react}")
    log(sep)


async def seed_latest_seen(
    client: TelegramClient,
    targets: list[tuple[str, object]],
    last_seen: dict[int, int],
) -> None:
    for _, entity in targets:
        pid = peer_id_safe(entity) or 0
        async for msg in client.iter_messages(entity, limit=1):
            if isinstance(msg, types.Message):
                last_seen[pid] = max(last_seen.get(pid, 0), msg.id)
                break


async def print_today_posts(
    client: TelegramClient,
    targets: list[tuple[str, object]],
    static_id: int,
    fallback_id: int,
    last_seen: dict[int, int],
) -> int:
    today = datetime.now().astimezone().date()
    printed = 0

    for name, entity in targets:
        pid = peer_id_safe(entity) or 0
        messages: list[types.Message] = []

        async for msg in client.iter_messages(entity):
            if not isinstance(msg, types.Message):
                continue

            msg_date = message_local_date(msg)
            if msg_date is None:
                continue
            if msg_date < today:
                break
            if msg_date != today:
                continue

            messages.append(msg)
            last_seen[pid] = max(last_seen.get(pid, 0), msg.id)

        for msg in reversed(messages):
            print_post(static_id, name, entity, msg, fallback_id)
            printed += 1

    return printed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def amain() -> None:
    load_dotenv()
    args = parse_args()

    if not args.folder:
        raise SystemExit("Specify --folder or set TG_FOLDER in .env")

    static_id_env = os.getenv("TG_MONITOR_STATIC_ID")
    if args.static_id is not None:
        static_id = args.static_id
    elif static_id_env:
        try:
            static_id = int(static_id_env)
        except ValueError:
            raise SystemExit("TG_MONITOR_STATIC_ID must be integer")
    else:
        raise SystemExit("Specify --static-id or set TG_MONITOR_STATIC_ID in .env")

    api_id = env_int("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_hash:
        raise SystemExit("Missing TG_API_HASH in .env")

    client = TelegramClient(args.session, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        phone = os.getenv("TG_PHONE")
        if phone:
            await client.start(phone=phone)
        else:
            await client.start(
                phone=lambda: input("Enter phone number: ").strip()
            )

    log(f"Resolving folder: {args.folder} ...")
    targets = await resolve_folder_targets(client, args.folder, args.include_groups)

    if not targets:
        raise SystemExit("No channel targets found in folder.")

    log(f"Monitoring {len(targets)} channel(s) from folder '{args.folder}'")
    log(f"static_id={static_id}  fallback_emotion={args.fallback_id}  poll={args.poll}s")
    log("Output: <id> | <link> | <rand>")
    log("  Views line:     static_id, 2200-2800")
    log("  Reaction line:  emotion_id, 30-50 (365: 70-100)")
    log()

    for name, _ in targets:
        log(f"  - {name}")
    log()

    # Per-channel last seen message id
    last_seen: dict[int, int] = {}

    if args.today:
        printed = await print_today_posts(
            client,
            targets,
            static_id,
            args.fallback_id,
            last_seen,
        )
        log(f"Printed today's posts: {printed}")
    elif args.last > 0:
        log(f"--- Last {args.last} post(s) per channel ---")
        for name, entity in targets:
            pid = peer_id_safe(entity) or 0
            async for msg in client.iter_messages(entity, limit=args.last):
                if isinstance(msg, types.Message):
                    print_post(static_id, name, entity, msg, args.fallback_id)
                    if msg.id > last_seen.get(pid, 0):
                        last_seen[pid] = msg.id
    await seed_latest_seen(client, targets, last_seen)

    if args.once:
        log("Done.")
        return

    log(f"\nMonitoring new posts... (Ctrl+C to stop)\n")

    try:
        while True:
            await asyncio.sleep(args.poll)
            for name, entity in targets:
                pid = peer_id_safe(entity) or 0
                min_id = last_seen.get(pid, 0)
                async for msg in client.iter_messages(entity, min_id=min_id, limit=20):
                    if not isinstance(msg, types.Message):
                        continue
                    if msg.id <= min_id:
                        continue
                    print_post(static_id, name, entity, msg, args.fallback_id)
                    if msg.id > last_seen.get(pid, 0):
                        last_seen[pid] = msg.id
    except KeyboardInterrupt:
        log("\nStopped.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(amain())
