# Telegram Autoposter

Small Telegram API script for posting one prepared message to every channel in a Telegram folder/filter.

The script does not buy, add, or automate artificial views/reactions. It posts to channels you can access and writes a report with the Telegram message link and the current view counter returned by Telegram.

## Setup

1. Install Python 3.10+.
2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Copy the example environment file and fill in your own values:

```powershell
Copy-Item .env.example .env
notepad .env
```

Use your Telegram `api_id` and `api_hash` from my.telegram.org. Do not commit or share `.env`.

4. Create the post text file:

```powershell
Copy-Item message.txt.example message.txt
notepad message.txt
```

## Check Targets

Run a dry run first. This only prints channels from the folder and does not post:

```powershell
python .\telegram_autoposter.py --message-file .\message.txt --folder "My folder" --dry-run
```

You can also use a file with channels instead of a Telegram folder:

```powershell
python .\telegram_autoposter.py --message-file .\message.txt --channels-file .\channels.txt --dry-run
```

`channels.txt` format:

```text
@public_channel
https://t.me/another_public_channel
-1001234567890
```

## Post

```powershell
python .\telegram_autoposter.py --message-file .\message.txt --folder "My folder"
```

Useful options:

```powershell
python .\telegram_autoposter.py --message-file .\message.txt --folder "My folder" --limit 1
python .\telegram_autoposter.py --message-file .\message.txt --folder "My folder" --parse-mode html
python .\telegram_autoposter.py --message-file .\message.txt --folder "My folder" --no-link-preview
```

On the first run, Telegram will ask for the login code and possibly the 2FA password. After that, the local `.session` file is reused.

## Batch Channel Posts

For a prepared `posts.txt` with blocks like `КАНАЛ 1`, `КАНАЛ 2`, etc., run:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run
python .\telegram_autoposter.py --messages-file .\posts.txt
```

When a fresh batch of images is provided, copy them to `media_pool` and use a fresh rotation state so the whole new batch can be attached instead of being limited by an old rotation cycle:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
python .\telegram_autoposter.py --messages-file .\posts.txt --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
```

After posting, copy-friendly lines are written to `reports/copy_YYYYMMDD_HHMMSS.txt`; these are the lines to send back to the user.

## Delayed Posting

By default, posts are sent with a short random delay of 2-6 seconds between channels.
For a compact local spread, use a delay profile or explicit min/max durations:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run --delay-profile mixed
python .\telegram_autoposter.py --messages-file .\posts.txt --delay-profile mixed
```

The `mixed` profile randomly waits around 2-8 minutes between posts. The dry run prints a timing plan before anything is posted.

You can also set a simple random range, or wait only after every N channels:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --delay-min 10m --delay-max 1h
python .\telegram_autoposter.py --messages-file .\posts.txt --delay-every 2 --delay-min 5m --delay-max 5m
```

## Skip Channels Already Posted Today

When more than one administrator may publish to the same channels, add
`--skip-posted-today` to both the dry run and the real run:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run --skip-posted-today --delay-every 2 --delay-min 5m --delay-max 5m
python .\telegram_autoposter.py --messages-file .\posts.txt --skip-posted-today --delay-every 2 --delay-min 5m --delay-max 5m
```

The check uses `Europe/Moscow` by default. It runs once while preparing the
batch and again immediately before each send, so a channel is also skipped if
another administrator posts during a delayed run. Use `--today-timezone` to
override the timezone.

## Multiple Posts in One Channel

`--messages-file` also accepts a numbered series inside a channel block:

```text
КАНАЛ 1

Пост 1: запустил. балик на месте, заходите.

https://twitch.tv/yourlink

[Через 12 минут] Пост 2: вау, вот это занесло. скриншот ниже.

СКРИН ЗАНОСА: media_pool/20260710_win_01.png
```

The delay is relative to the preceding post in the same channel. Other channel
series remain independent and can be posted while this follow-up is waiting.
The forms `12 минут`, `1 час 5 минут`, `10m`, and `30s` are supported.

The instruction placeholder `[СЮДА КИДАЕМ СКРИНШОТ ЗАНОСА]` is removed from
the caption. Before the real run it must be paired with an explicit
`СКРИН ЗАНОСА: <file>` directive; an ordinary rotation image is never used as
a replacement for a required win screenshot.

After each successful send, the script immediately stores the batch ID,
channel, sequence number, Telegram message ID, and send time in
`reports/autoposter_owned_posts.json`. Follow-ups from that same batch are
therefore recognized as part of a series instead of being rejected by
`--skip-posted-today`. Re-running the same daily batch resumes unsent posts and
does not resend completed sequence numbers. Use `--batch-id` only when a
manually chosen stable batch identifier is needed.

icheatbot ordering is enabled by default when `ICHEATBOT_API_KEY` is present.
Use `--no-icheatbot` to disable orders for a specific run.

## Report

After posting, the script writes a CSV file:

```text
reports/posted_YYYYMMDD_HHMMSS.csv
```

It also prints copy-friendly lines:

```text
message_id | link | current_views
```

For private channels, links use Telegram's `https://t.me/c/...` format and are visible only to users who have access to that channel.
