# Tokyo Airing Radar v2.2 — Overnight Intelligence

AniList airing alerts for **Orewatokyo**, delivered to Discord, with schedule intelligence, configurable anime categories, overnight catch-up, a weekly calendar, and delivery analytics.

## Features

- Refreshes the AniList anime list/status cache every 12 hours. Existing `media_ids` are retained while `media_entries` are added for status-aware filtering.
- Sends 3-hour, 1-hour, and 30-minute reminders. A late workflow run chooses the nearest useful reminder instead of sending stale earlier notices.
- Batches up to 10 alert embeds per Discord webhook request.
- Publishes one daily schedule board in India Standard Time and edits that message on later runs.
- Detects schedule delays, earlier reschedules, schedule record replacements, missing schedules (only after three consecutive absent checks), and restored schedules.
- **Morning catch-up digest:** after the 10 PM–10 AM break, reports episodes that the last saved schedule expected to air overnight and indicates whether any reminder was recorded as delivered. Failed digest delivery is retained for retry.
- **Weekly calendar:** posts a seven-day schedule grouped by IST date once each Monday.
- **Notification and API analytics:** cumulative AniList/Discord request counts, errors, retries, delivered reminders/events, catch-up and calendar posts, plus the last 100 run summaries. Weekly report includes health totals.
- **Preferences control form:** configure Favourite, Muted and AniList status filters through GitHub Actions without editing JSON manually.
- Supports **Favourite**, **Watching**, **Muted**, and **Other** categories. Watching is derived from AniList `CURRENT` / `REPEATING` status; favourite and muted IDs are manually configured.
- Uses atomic JSON writes and keeps the existing alert history, cache IDs, and daily board reference.

## Preferences control panel (no JSON editing)

Open **GitHub → Actions → Tokyo Airing Radar Preferences → Run workflow** on `main`.

Choose one action:
- `add_favourite` / `remove_favourite`
- `add_muted` / `remove_muted`
- `set_status_filter` — supply comma-separated values such as `CURRENT,PLANNING,COMPLETED`
- `reset_status_filter` — restore all six AniList statuses

For favourite/mute actions, enter the numeric AniList media ID. The workflow validates the input and commits the changed preference file to `main`; it does not run the airing bot or send Discord messages.

**Discord interaction note:** the configured Discord webhook can post messages but cannot receive slash commands or button clicks. This release therefore provides the control form in GitHub Actions. A native Discord command/button panel would require a separate Discord bot application/token and interaction endpoint.

## GitHub Actions secrets

- `DISCORD_AIRING_WEBHOOK` — required Discord channel webhook.
- `ANILIST_TARGET_TOKEN` — optional; only needed if the AniList list is not public.

## Operating hours

The live engine runs every 15 minutes from **10:00 AM through 9:45 PM India Standard Time (IST)**. It rests from **10:00 PM until 10:00 AM IST** (a 12-hour break).

GitHub Actions cron uses UTC:
- `30,45 4 * * *` — 10:00 and 10:15 AM IST.
- `*/15 5-15 * * *` — 10:30 AM through 9:15 PM IST.
- `0,15 16 * * *` — 9:30 and 9:45 PM IST.

Manual runs are blocked from executing the live bot outside 10:00–22:00 IST. Pull requests and pushes to `main` run compile checks and unit tests only; they do not send Discord messages or execute the live radar. Scheduled GitHub workflows can be delayed by platform load.

## State files

- `db_anime_airing.json` — sent reminder history; legacy string values and list values are both supported.
- `airing_cache.json` — existing AniList ID cache plus refreshed media-list statuses.
- `daily_board.json` — Discord daily board message ID/date.
- `anime_preferences.json` — favourite/muted media IDs and allowed AniList list statuses.
- `schedule_history.json` — observed schedule snapshots, change events, and pending Discord notifications.
- `anime_stats.json` — latest statistics, delivery counters, pending morning digest (when needed), weekly reports/calendars, and bounded run history.

**Migration / preservation:** Existing `db_anime_airing.json`, `airing_cache.json`, and `daily_board.json` are preserved. The cache retains the legacy `media_ids` array while storing statuses. Alert history continues to accept its original string reminder values. Do not delete these files when updating the repository.

## Local development

```bash
python -m pip install -r requirements.txt
python -m py_compile airing_alerts.py anime_intelligence.py radar_v22.py manage_preferences.py
python -m unittest discover -s tests -v
python airing_alerts.py
```

Run the bot manually from **Actions → Tokyo Airing Radar → Run workflow** on `main`. The operating-hours guard still applies.
