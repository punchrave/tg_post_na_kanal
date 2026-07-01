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
