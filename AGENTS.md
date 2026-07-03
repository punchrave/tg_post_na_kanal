# Codex Posting Workflow

Use this workflow when the user sends Telegram channel post blocks and images, or says to make/send posts to the channels.

## Default Action

- Treat "сделай посты", "напиши на каналы посты", or a pasted list like `КАНАЛ 1 ...` plus images as a request to prepare and send the Telegram posts, not only to stage files.
- Do not ask for confirmation if the post blocks and images are clear. Run a dry-run check, then send.
- After sending, always print the copy-friendly output lines in the final answer: `static_id | post_link | views_count` and, when present, `reaction_id | post_link | reactions_count`.

## Selective Posting

- The user may ask to post to all channels except one or more named channels, usernames, links, or channel numbers because those posts will be handled manually.
- In that case, exclude the specified target(s) from the real send instead of asking for confirmation.
- Make sure `posts.txt` and the dry-run/real-run target count match the included channels only. In the final answer, mention which channel(s) were skipped.

## Delayed Posting

- If the user asks to send posts at different times, with gaps, spread, delay, or "не в один тайм", use delayed posting.
- For a local computer, prefer compact schedules that fit the user's available runtime. Good default: `--delay-every 2 --delay-min 5m --delay-max 5m`, which sends two channels, waits five minutes, then continues.
- If the user gives an explicit range, use readable durations such as `--delay-min 2m --delay-max 5m` or `--delay-every 2 --delay-min 5m --delay-max 5m`.
- Avoid hour-scale delays unless the user explicitly asks for them or a server-side Telegram scheduling mode is being used.
- Mention before the real run how long the delayed batch will take according to the dry-run timing plan.

## Preparing Posts

- Save the pasted channel blocks into `posts.txt` using the script's exact block format:

```text
КАНАЛ 1

post text

КАНАЛ 2

post text
```

- Strip ChatGPT/Markdown link wrappers from pasted links. Keep only plain URLs such as `https://kick.com/name` or `https://twitch.tv/name`.
- If the user gives channel-specific stream links, record them in `channel_links.json` under the Telegram channel username/title. If a channel must always use a Kick link even when the post template contains `twitch.tv/yourlink`, set both `kick` and `twitch` to that Kick URL.

## Preparing Images

- Copy attached images into `media_pool` with clear dated names such as `YYYYMMDD_01.png`, `YYYYMMDD_02.png`, etc. Copy them; do not move or delete the original temp files.
- For a new user-provided image batch, use a fresh media rotation state file so old rotation state does not limit the number of attached images:

```powershell
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
python .\telegram_autoposter.py --messages-file .\posts.txt --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
```

- The real posting run archives used images from `media_pool` into `media_used\YYYYMMDD_HHMMSS`. Verify the archive count and that `media_pool` is empty when all provided images were consumed.

## Premium Emoji

- Leave premium Telegram emoji enabled unless the user explicitly asks otherwise.
- The autoposter should load premium/custom emoji from all account emoji packs and choose each inserted emoji randomly from that full pool.
- Do not add ordinary Unicode emoji as a separate random decoration. Normal emoji characters may only appear as the required alt text behind `MessageEntityCustomEmoji`; the visible decoration should be Telegram premium/custom emoji.
- If a future change makes the log show only a tiny candidate count such as `40`, inspect `load_premium_emojis`; that usually means it fell back to seed search instead of account packs.

## Required Final Response

After the real send completes, include:

- The post count and whether all provided images were used.
- Links to the generated report files in `reports`.
- The full contents of `reports\copy_YYYYMMDD_HHMMSS.txt` in a text block.

Do not stop after saying the files are prepared unless the user explicitly asks only to prepare files.
