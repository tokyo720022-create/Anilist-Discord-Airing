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

## Operating hours

The live engine runs every 15 minutes from **10:00 AM through 9:45 PM India Standard Time (IST)**. It rests from **10:00 PM until 10:00 AM IST** (a 12-hour break).

GitHub Actions cron uses UTC, so the schedule is:
- `30,45 4 * * *` — 10:00 and 10:15 AM IST.
- `*/15 5-15 * * *` — 10:30 AM through 9:15 PM IST.
- `0,15 16 * * *` — 9:30 and 9:45 PM IST.

Manual workflow runs are also blocked from executing the live bot outside 10:00–22:00 IST. Pull requests and pushes to `main` run compile checks and unit tests only; they do not send Discord messages or execute the live radar. Scheduled GitHub workflows can be delayed by platform load.

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

Run manually from **Actions → Tokyo Airing Radar → Run workflow** on `main`. GitHub's operating-hours guard still applies to the live workflow.
