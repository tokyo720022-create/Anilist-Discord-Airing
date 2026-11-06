import unittest

from anime_intelligence import (
    anime_category,
    normalize_preferences,
    normalize_sent_reminders,
    observe_schedules,
    select_due_reminder,
    should_track,
    weekly_report_due,
    weekly_report_key,
)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.prefs = normalize_preferences({
            "favourite_media_ids": [10, "11", -1, "bad"],
            "muted_media_ids": [12],
            "list_status_filter": ["CURRENT", "planning", "INVALID"],
        })

    def test_normalizes_ids_and_statuses(self):
        self.assertEqual(self.prefs["favourite_media_ids"], [10, 11])
        self.assertEqual(self.prefs["list_status_filter"], ["CURRENT", "PLANNING"])

    def test_favourite_overrides_status_filter(self):
        self.assertTrue(should_track(10, "COMPLETED", self.prefs))
        self.assertEqual(anime_category(10, "COMPLETED", self.prefs), "favourite")

    def test_muted_overrides_favourite(self):
        prefs = normalize_preferences({"favourite_media_ids": [12], "muted_media_ids": [12]})
        self.assertFalse(should_track(12, "CURRENT", prefs))
        self.assertEqual(anime_category(12, "CURRENT", prefs), "muted")

    def test_watching_category_uses_current_and_repeating(self):
        self.assertEqual(anime_category(20, "CURRENT", self.prefs), "watching")
        self.assertEqual(anime_category(20, "REPEATING", self.prefs), "watching")

    def test_list_status_filter(self):
        self.assertTrue(should_track(30, "PLANNING", self.prefs))
        self.assertFalse(should_track(31, "DROPPED", self.prefs))


class ReminderTests(unittest.TestCase):
    def test_reminder_selects_closest_window(self):
        now = 1_000_000
        self.assertEqual(select_due_reminder(now + 3 * 3600, now, []), "3h")
        self.assertEqual(select_due_reminder(now + 55 * 60, now, ["3h"]), "1h")
        self.assertEqual(select_due_reminder(now + 25 * 60, now, ["3h", "1h"]), "30m")

    def test_late_run_does_not_send_stale_one_hour_reminder(self):
        now = 1_000_000
        self.assertEqual(select_due_reminder(now + 10 * 60, now, ["3h"]), "30m")

    def test_sent_reminder_is_not_duplicated_and_legacy_strings_work(self):
        now = 1_000_000
        self.assertEqual(normalize_sent_reminders("1h"), {"1h"})
        self.assertIsNone(select_due_reminder(now + 55 * 60, now, "1h"))
        self.assertIsNone(select_due_reminder(now - 1, now, []))


class ScheduleHistoryTests(unittest.TestCase):
    def test_detects_delay_after_existing_baseline(self):
        now = 2_000_000
        first = [{"media_id": 1, "episode": 2, "title": "Example", "schedule_id": "a", "airing_at": now + 3600}]
        state = observe_schedules({}, first, now)
        shifted = [{"media_id": 1, "episode": 2, "title": "Example", "schedule_id": "a", "airing_at": now + 5400}]
        state = observe_schedules(state, shifted, now + 900)
        self.assertEqual(state["pending_events"][-1]["type"], "delay")
        self.assertEqual(state["pending_events"][-1]["delta_seconds"], 1800)

    def test_missing_schedule_requires_repeated_checks(self):
        now = 2_000_000
        first = [{"media_id": 1, "episode": 2, "title": "Example", "schedule_id": "a", "airing_at": now + 3600}]
        state = observe_schedules({}, first, now)
        state = observe_schedules(state, [], now + 900)
        state = observe_schedules(state, [], now + 1800)
        self.assertEqual(state["pending_events"], [])
        state = observe_schedules(state, [], now + 2700)
        self.assertEqual(state["pending_events"][-1]["type"], "missing")

    def test_restored_schedule_is_notified(self):
        now = 2_000_000
        first = [{"media_id": 1, "episode": 2, "title": "Example", "schedule_id": "a", "airing_at": now + 3600}]
        state = observe_schedules({}, first, now)
        for offset in (900, 1800, 2700):
            state = observe_schedules(state, [], now + offset)
        restored = [{"media_id": 1, "episode": 2, "title": "Example", "schedule_id": "b", "airing_at": now + 7200}]
        state = observe_schedules(state, restored, now + 3600)
        self.assertIn("restored", [event["type"] for event in state["pending_events"]])


class WeeklyReportTests(unittest.TestCase):
    def test_week_key_and_monday_report_gate(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        monday = int(datetime(2026, 11, 9, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        self.assertTrue(weekly_report_due(monday, {}))
        self.assertEqual(weekly_report_key(monday), "2026-W46")
        self.assertFalse(weekly_report_due(monday, {"last_weekly_report": "2026-W46"}))


if __name__ == "__main__":
    unittest.main()
