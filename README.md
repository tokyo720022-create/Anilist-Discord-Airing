# Tokyo Airing Radar v2.1 — Anime Intelligence

AniList airing alerts for **Orewatokyo**, delivered to Discord, with schedule intelligence, configurable anime categories, and weekly reports.

## Features

- Refreshes the AniList anime list/status cache every 12 hours. Existing `media_ids` are retained while `media_entries` are added for status-aware filtering.
- Sends 3-hour, 1-hour, and 30-minute reminders. A late workflow run chooses the nearest useful reminder instead of sending stale earlier notices.
- Batches up to 10 alert embeds per Discord webhook request.
- Publishes one daily schedule board in India Standard Time and edits that message on later runs.
- Detects schedule delays, earlier reschedules, schedule record replacements, missing schedules (only after three consecutive absent checks), and restored schedules.
- Preserves pending schedule-change notifications so temporary Discord delivery failures can be retried.
- Supports **Favourite**, **Watching**, **Muted**, and **Other** categories. Watching is derived from AniList `CURRENT` / `REPEATING` status; favourite and muted IDs are manually configured.
- Filters the tracked list by AniList statuses: `CURRENT`, `PLANNING`, `COMPLETED`, `DROPPED`, `PAUSED`, and `REPEATING`.
- Stores current anime statistics and sends a weekly intelligence report on Mondays (Asia/Kolkata).
- Uses atomic JSON writes and keeps the pre-existing alert history, cache IDs, and daily board reference.
- Sends a GitHub Actions failure notification to Discord.

## Configure categories and list filtering

Edit `anime_preferences.json`:

```json
{
  "version": 1,
  "favourite_media_ids": [21, 235],
  "muted_media_ids": [8687],
  "list_status_filter": ["CURRENT", "PLANNING", "COMPLETED", "REPEATING"]
}
```

Use AniList media IDs in the two ID lists. Favourite entries bypass the list-status filter; muted entries always suppress alerts. If an ID appears in both lists, **Muted wins**. Watching is automatic for AniList statuses `CURRENT` and `REPEATING`. The default status filter includes all six statuses, preserving the previous all-list tracking behaviour.

## GitHub Actions secrets

- `DISCORD_AIRING_WEBHOOK` — required Discord channel webhook.
- `ANILIST_TARGET_TOKEN` — optional; only needed if the AniList list is not public.

## Schedule

The workflow checks every 15 minutes at minutes 7, 22, 37 and 52 UTC (`7,22,37,52 * * * *`). The daily schedule board and weekly report use `Asia/Kolkata`. Scheduled GitHub workflows can be delayed by platform load.

Pull requests and pushes to `main` run compile checks and unit tests only; they do not send Discord messages or execute the live radar. Scheduled and manual runs on `main` execute the bot and persist state.

## State files

- `db_anime_airing.json` — sent reminder history; legacy string values and list values are both supported.
- `airing_cache.json` — existing AniList ID cache plus refreshed media-list statuses.
- `daily_board.json` — Discord daily board message ID/date.
- `anime_preferences.json` — favourite/muted media IDs and allowed AniList list statuses.
- `schedule_history.json` — observed schedule snapshots, change events, and pending Discord notifications.
- `anime_stats.json` — latest statistics and the last 12 successful weekly report snapshots.

**Migration / preservation:** Existing `db_anime_airing.json`, `airing_cache.json`, and `daily_board.json` are not reset. The cache is refreshed in its existing file with the old `media_ids` list retained. Alert history continues to accept its original string reminder values. Do not delete these files when updating the repository.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python airing_alerts.py
```

Run manually from **Actions → Tokyo Airing Radar → Run workflow** on `main`.