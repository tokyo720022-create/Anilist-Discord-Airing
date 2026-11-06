import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from radar_v22 import (
    apply_preference_action,
    collect_overnight_airings,
    morning_digest_embed,
    update_delivery_analytics,
    weekly_calendar_due,
    weekly_calendar_embed,
)


class OvernightDigestTests(unittest.TestCase):
    def test_collects_episodes_in_overnight_interval_and_detects_missed_reminders(self):
        start = 1_800_000_000
        history = {"airings": {
            "1_ep4": {"media_id": 1, "episode": 4, "title": "Night Anime", "airing_at": start + 3600},
            "2_ep8": {"media_id": 2, "episode": 8, "title": "Reminder Anime", "airing_at": start + 7200},
            "3_ep1": {"media_id": 3, "episode": 1, "title": "Outside", "airing_at": start + 90000},
        }}
        alerts = {"2_ep8": ["1h"]}
        items, missed = collect_overnight_airings(history, alerts, start, start + 8 * 3600)
        self.assertEqual([item["media_id"] for item in items], [1, 2])
        self.assertEqual(missed, 1)
        self.assertTrue(items[0]["reminder_missed"])
        self.assertFalse(items[1]["reminder_missed"])

    def test_excludes_episode_rescheduled_after_the_break(self):
        start = 1_800_000_000
        history = {"airings": {
            "5_ep3": {"media_id": 5, "episode": 3, "title": "Moved Anime", "airing_at": start + 3600}
        }}
        current = [{"media_id": 5, "episode": 3, "airing_at": start + 86400}]
        items, missed = collect_overnight_airings(history, {}, start, start + 8 * 3600, current_airings=current)
        self.assertEqual(items, [])
        self.assertEqual(missed, 0)

    def test_morning_digest_is_single_embed_and_handles_empty_night(self):
        now = int(datetime(2026, 11, 7, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        embed = morning_digest_embed([], 0, now - 12 * 3600, now)
        self.assertIn("MORNING CATCH-UP", embed["author"]["name"])
        self.assertEqual(embed["fields"][1]["value"], "0")
        self.assertIn("Nothing", embed["description"])


class WeeklyCalendarTests(unittest.TestCase):
    def test_calendar_groups_seven_days_and_uses_local_time_tokens(self):
        now = int(datetime(2026, 11, 6, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        airings = [
            {"media_id": 21, "episode": 4, "title": "Anime A", "airing_at": now + 3600},
            {"media_id": 22, "episode": 9, "title": "Anime B", "airing_at": now + 86400},
        ]
        embed = weekly_calendar_embed(airings, now)
        self.assertEqual(len(embed["fields"]), 7)
        self.assertIn("Anime A", embed["fields"][0]["value"])
        self.assertIn("Anime B", embed["fields"][1]["value"])

    def test_calendar_only_due_once_per_monday_week(self):
        monday = int(datetime(2026, 11, 9, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        self.assertTrue(weekly_calendar_due(monday, {}))
        self.assertFalse(weekly_calendar_due(monday, {"last_weekly_calendar": "2026-W46"}))


class PreferenceControlTests(unittest.TestCase):
    def test_add_and_remove_favourite(self):
        prefs = apply_preference_action({}, "add_favourite", media_id=21)
        self.assertEqual(prefs["favourite_media_ids"], [21])
        prefs = apply_preference_action(prefs, "remove_favourite", media_id=21)
        self.assertEqual(prefs["favourite_media_ids"], [])

    def test_muted_wins_and_can_be_removed(self):
        prefs = apply_preference_action({}, "add_muted", media_id=99)
        self.assertEqual(prefs["muted_media_ids"], [99])
        prefs = apply_preference_action(prefs, "remove_muted", media_id=99)
        self.assertEqual(prefs["muted_media_ids"], [])

    def test_status_filter_is_validated(self):
        prefs = apply_preference_action({}, "set_status_filter", statuses=["CURRENT", "PLANNING"])
        self.assertEqual(prefs["list_status_filter"], ["CURRENT", "PLANNING"])
        with self.assertRaises(ValueError):
            apply_preference_action(prefs, "set_status_filter", statuses=["BOGUS"])


class DeliveryAnalyticsTests(unittest.TestCase):
    def test_delivery_counters_accumulate_and_run_history_is_bounded(self):
        state = {"delivery": {"discord_errors": 2}, "run_history": [{"at": i} for i in range(100)]}
        metrics = {
            "anilist_requests": 3, "anilist_errors": 1, "discord_requests": 4,
            "discord_successes": 3, "discord_errors": 1, "discord_retries": 1,
        }
        updated = update_delivery_analytics(state, 12345, metrics, 2, 1, True, False)
        self.assertEqual(updated["delivery"]["discord_errors"], 3)
        self.assertEqual(updated["delivery"]["reminders_sent"], 2)
        self.assertEqual(len(updated["run_history"]), 100)
        self.assertEqual(updated["run_history"][-1]["at"], 12345)


if __name__ == "__main__":
    unittest.main()
