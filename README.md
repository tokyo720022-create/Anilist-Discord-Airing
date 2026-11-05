# AniList Discord Airing Radar

Hourly AniList airing alerts for **Orewatokyo**, delivered to Discord.

## Features
- Refreshes the AniList anime ID cache every 12 hours.
- Uses AniList `airingSchedules` filtered to cached media IDs and the next 24 hours.
- Sends 3-hour, 1-hour, and 30-minute reminders (the final 1-hour notice supersedes a missed 30-minute notice).
- Batches up to 10 alert embeds per Discord webhook request.
- Publishes one daily schedule board in India Standard Time and edits that message on later hourly runs.
- Preserves existing `db_anime_airing.json` alert history and migrates legacy string statuses automatically.
- Prunes history for anime removed from the AniList list and episodes more than three episodes behind the latest known airing.
- Sends a GitHub Actions failure notification to Discord.

## GitHub Actions secrets
- `DISCORD_AIRING_WEBHOOK` — required Discord channel webhook.
- `ANILIST_TARGET_TOKEN` — optional; only needed if the AniList list is not public.

## Schedule
Runs every 15 minutes at minutes 7, 22, 37 and 52 UTC (`7,22,37,52 * * * *`). This is intentional: an hourly run cannot reliably deliver a 30-minute reminder. The daily schedule board uses Asia/Kolkata dates and times. GitHub scheduled workflows can be delayed during platform load.

## State files
- `db_anime_airing.json` — sent alert history (existing file retained).
- `airing_cache.json` — cached AniList media IDs, refreshed every 12 hours.
- `daily_board.json` — Discord daily board message ID/date.

**Important:** When copying these files into the existing repository, do not overwrite or delete the existing `db_anime_airing.json`; the updated code reads and migrates its existing entries.

Run manually from **Actions → AniList Airing Alerts → Run workflow**.
