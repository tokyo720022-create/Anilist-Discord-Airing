# AniList Airing Alerts

This repository is dedicated to one task: checking the upcoming episodes in the AniList anime list for **Orewatokyo** and posting airing warnings to Discord.

## What it does

- Checks AniList once every hour through GitHub Actions.
- Sends a **3-hour warning** when an episode is between one and three hours away.
- Sends a **final 1-hour warning** when an episode is within the next hour.
- Includes the anime title, episode number, cover image, telecast time, and Discord countdown.
- Remembers which warnings were already sent, so the same warning is not repeatedly posted.
- Stores alert history in the existing database file.

## Required GitHub secret

In **Repository → Settings → Secrets and variables → Actions**, add:

- **DISCORD_AIRING_WEBHOOK** — the Discord channel webhook URL.

## Optional GitHub secret

- **ANILIST_TARGET_TOKEN** — only needed when the AniList list requires authentication. The username is set to Orewatokyo in the workflow.

## Schedule

The workflow uses the cron schedule `0 * * * *`, which means once every hour. GitHub Actions scheduled runs can be delayed slightly during platform load; they are not guaranteed to start at the exact minute.

Because GitHub Actions cron is in UTC, the hourly checks occur at approximately **:30 past each hour in India (IST)**.

You can also start a check manually from **Actions → AniList Airing Alerts → Run workflow**.

## Files

- `.github/workflows/airing_alerts.yml` — hourly schedule and state persistence.
- `airing_alerts.py` — AniList lookup and Discord notification logic.
- `db_anime_airing.json` — sent-alert history.
- `requirements.txt` — Python dependency list.
- `README.md` — project notes.
