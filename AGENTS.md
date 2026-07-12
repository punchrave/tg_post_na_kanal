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

## Daily Duplicate Prevention

- When the user asks how many channels have posts today, how many still need posts, or asks a similar preflight question, inspect the full Telegram folder before requesting or preparing post text. Report: total channels, count already posted today, count still empty today, and a numbered folder-order list of the empty channels.
- Include the names of channels already posted today, with post links and local times when useful, so the user can verify the result. Do not send anything during this inspection.
- The numbered empty-channel list becomes the input order for the user's next `КАНАЛ N` blocks. Preserve that exact subset and order by generating a matching channels file for the later dry-run and real run; do not remap those blocks against the full folder.
- Treat the preflight list as advisory because another administrator may post afterward. Keep `--skip-posted-today` enabled during the later real run so any channel that changed after the preflight is safely skipped.
- When another person may also be posting to some of the channels, add `--skip-posted-today` to both the dry-run and the real run.
- This mode checks for any Telegram post dated today in the `Europe/Moscow` timezone, regardless of which administrator published it.
- The autoposter checks once while building the target list and again immediately before each real send. If a post appears during a delayed batch, skip that channel instead of creating a duplicate.
- Keep every original `КАНАЛ N` block in folder order. Filtering happens after channel-to-block matching, so skipped channels do not shift another channel's text or stream link.
- A channel skipped by this check must not consume an image and must not receive icheatbot orders. In the final answer, list the channels skipped because they already had a post today.
- If the user explicitly wants an additional post even though the channel already has one today, omit `--skip-posted-today` for that run.

## Multiple Posts Per Channel

- A channel block may contain `Пост 1`, `Пост 2`, and further posts. Treat bracketed timing such as `[Через 12 минут] Пост 2` as a delay relative to the preceding post in that same channel.
- Preserve these headers in `posts.txt`; the autoposter parses them directly. For a marked win post, replace the placeholder with `СКРИН ЗАНОСА: media_pool/<copied-file>` so the mapping is explicit and machine-checked.
- Decide whether a channel is eligible before starting its planned series. If it had no post today at that point, send every explicitly planned follow-up in the series; do not mistake the series' own first post for a pre-existing post and cancel later posts.
- Recheck the daily-duplicate condition immediately before the first post of each channel series. Once that series starts, follow its stated timing unless the user explicitly changes or cancels it.
- Keep different channels' sequences independent. A delay inside one channel describes that channel's follow-up timing, not a reason to block unrelated ready posts in other channels.
- Keep the default `reports/autoposter_owned_posts.json` state file. It records each successful Telegram message ID immediately, allows a delayed series to survive a script restart, and prevents already completed sequence numbers from being sent twice.

## Image Roles and Priority

- The user may classify attached images as ordinary images and win screenshots (`скрины заносов`). Preserve that classification when copying and naming the files: use names such as `YYYYMMDD_ordinary_01.png` and `YYYYMMDD_win_01.png`. Files marked `_win_` are excluded from ordinary random rotation.
- Text markers such as `[СЮДА КИДАЕМ СКРИНШОТ ЗАНОСА]`, `здесь скрин заноса`, or equivalent wording require a win screenshot on that exact post. This explicit role has priority over normal image rotation.
- If the user maps a particular image to a post, that mapping has highest priority. Otherwise, assign ordinary images and win screenshots within their own groups in the order the user supplied them.
- Win-screenshot posts must preferentially go to Telegram channels whose effective stream link in `channel_links.json` points to `kick.com`. Before writing `posts.txt`, inspect every block containing a win placeholder and the matched target's effective link. If a win block lands on a Twitch-linked target while an eligible Kick-linked target has a non-win block, swap/reassign the whole post block so the win post goes to the Kick-linked target. Aim for all win posts to use Kick-linked targets whenever enough eligible Kick channels exist, not merely half or a plurality.
- The pasted `КАНАЛ N` numbering alone is not an explicit image-to-channel instruction and may be remapped to satisfy the Kick priority. Only preserve a non-Kick win assignment when the user explicitly names that Telegram channel/username as the destination, or when there are not enough eligible Kick-linked targets. A separately stated user mapping still has highest priority.
- In the dry-run preview, explicitly verify and report the effective stream service for every win-screenshot target. Do not start the real send if a win post remains on a Twitch-linked target while an unused eligible Kick-linked target is available.
- Never put an ordinary image into a win-screenshot placeholder. Never consume a win screenshot for an ordinary-image post while a marked win post still needs one.
- When there are equal numbers of marked win posts and supplied win screenshots, use each screenshot exactly once. If the counts do not match and the user's intent cannot be determined safely, report the mismatch before a real send.
- Remove instructional placeholders such as `[СЮДА КИДАЕМ СКРИНШОТ ЗАНОСА]` from the Telegram caption after attaching the selected image.

## Delayed Posting

- For real Telegram sends, use delayed posting by default even if the user does not explicitly ask for delay. Do not run an immediate real send unless the user explicitly says to send immediately, without delay, or "сразу".
- The normal default real-send args are `--delay-every 2 --delay-min 5m --delay-max 5m`. Use the same delay args in dry-run so the timing plan is visible before posting.
- If the user asks to send posts at different times, with gaps, spread, delay, or "не в один тайм", use delayed posting.
- For a local computer, prefer compact schedules that fit the user's available runtime. Good default: `--delay-every 2 --delay-min 5m --delay-max 5m`, which sends two channels, waits five minutes, then continues.
- If the user gives an explicit range, use readable durations such as `--delay-min 2m --delay-max 5m` or `--delay-every 2 --delay-min 5m --delay-max 5m`.
- Avoid hour-scale delays unless the user explicitly asks for them or a server-side Telegram scheduling mode is being used.
- Mention before the real run how long the delayed batch will take according to the dry-run timing plan.
- During delayed runs, the autoposter writes copy-friendly lines to the report file immediately after each successful post, so the user does not need to wait for the whole batch to finish.

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
python .\telegram_autoposter.py --messages-file .\posts.txt --dry-run --skip-posted-today --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
python .\telegram_autoposter.py --messages-file .\posts.txt --skip-posted-today --media-rotation-state .\media_rotation_state_YYYYMMDD_posts.json
```

- The real posting run archives used images from `media_pool` into `media_used\YYYYMMDD_HHMMSS`. Verify the archive count and that `media_pool` is empty when all provided images were consumed.

## icheatbot Auto-Ordering

- icheatbot auto-ordering is enabled again. Do not add `--no-icheatbot` to normal dry-run or real posting commands unless the user explicitly asks to disable ordering for that run.
- The autoposter automatically places icheatbot.com API orders for views and reactions immediately after each post is published. No manual copy-paste is needed.
- The API key is stored in `.env` as `ICHEATBOT_API_KEY`. If the key is missing, auto-ordering is silently skipped.
- For each posted channel, the autoposter sends two API orders:
  1. **Views**: `service=static_id`, `quantity=random_views` (2200–2800)
  2. **Reactions**: `service=reaction_id`, `quantity=random_reactions` (30–50 or 70–100 for reaction_id 365)
- Channels in `CHANNEL_REACTION_ID_SKIPS` get views only (no reaction order).
- Order IDs are printed inline during posting and saved to the CSV report (`icheatbot_views_order`, `icheatbot_reaction_order` columns).
- Use `--no-icheatbot` to disable auto-ordering for a specific run.
- If the API returns an error (e.g., insufficient balance), the error is printed but posting continues normally.

## Premium Emoji

- Leave premium Telegram emoji enabled unless the user explicitly asks otherwise.
- Every `twitch.tv` stream link must always have the fixed six-part purple Twitch + `СТРИМ` custom-emoji sequence immediately to its left.
- For each `kick.com` stream link, randomly choose one of three source groups with equal source-level probability: the complete six-part green Kick wordmark from `FJKSTREAM`; one random K emoji from the three approved `Emoji slots` IDs; or one random emoji from the approved `Kick Emojis @liltenref` pack IDs. Never use an emoji outside these approved Kick sources as the link marker.
- Platform link markers are mandatory and deterministic. Random premium/custom emoji may still decorate other eligible positions in the post, but must not replace, split, or precede the platform marker at the URL position.
- The autoposter should load premium/custom emoji from all account emoji packs and choose each inserted emoji randomly from that full pool.
- Do not add ordinary Unicode emoji as a separate random decoration. Normal emoji characters may only appear as the required alt text behind `MessageEntityCustomEmoji`; the visible decoration should be Telegram premium/custom emoji.
- If a future change makes the log show only a tiny candidate count such as `40`, inspect `load_premium_emojis`; that usually means it fell back to seed search instead of account packs.

## Required Final Response

After the real send completes, include:

- The post count and whether all provided images were used.
- Links to the generated report files in `reports`.
- The full contents of `reports\copy_YYYYMMDD_HHMMSS.txt` in a text block.

Do not stop after saying the files are prepared unless the user explicitly asks only to prepare files.
