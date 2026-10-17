"""Weighed cup, «не несутся» follow-up, why eggs did not hatch, admin activity."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.domain import IncubationBatch
from app.services.eggs import EggService
from app.services.farm_overview import (
    BatchLosses,
    incubation_results_lines,
    load_batch_losses,
    parse_batch_losses,
    save_batch_losses,
)
from app.services.feeding import FeedingService, parse_cup_weight, parse_mix_text
from app.services.feeds import FeedService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeding import FeedingRepository
from app.storage.repositories.feeds import FeedRepository


TODAY = date(2026, 10, 17)


class RefinementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        self.feeds = FeedRepository(self.database)
        self.feed_service = FeedService(self.feeds)
        self.feeding = FeedingService(FeedingRepository(self.database), self.feeds)
        self.eggs = EggService(EggRepository(self.database), self.feeds, timezone_name="Europe/Moscow")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- weighed cup

    def test_weighed_cup_scales_every_ingredient(self) -> None:
        estimate = self.feeding.mix_kg_per_cup(1)
        before = dict((part.name, kg) for part, kg in self.feeding.split_cups(1, 3))

        self.feeding.set_cup_kg(1, 0.8)
        after = dict((part.name, kg) for part, kg in self.feeding.split_cups(1, 3))

        self.assertAlmostEqual(self.feeding.mix_kg_per_cup(1), 0.8, places=2)
        self.assertAlmostEqual(sum(after.values()), 2.4, places=1)
        for name, kg in before.items():
            self.assertAlmostEqual(after[name], kg * 0.8 / estimate, places=2)

    def test_weighed_cup_resets_when_cup_or_mix_changes(self) -> None:
        self.feeding.set_cup_kg(1, 0.8)
        self.feeding.set_cup_liters(1, 1.0)  # same cup: keep
        self.assertEqual(self.feeding.cup_kg(1), 0.8)

        self.feeding.set_cup_liters(1, 0.5)
        self.assertIsNone(self.feeding.cup_kg(1))

        self.feeding.set_cup_kg(1, 0.4)
        self.feeding.set_mix(1, parse_mix_text("Кукуруза 4\nКомбикорм 2"))
        self.assertIsNone(self.feeding.cup_kg(1))

    def test_parse_cup_weight(self) -> None:
        self.assertEqual(parse_cup_weight("780 г"), 0.78)
        self.assertEqual(parse_cup_weight("780"), 0.78)
        self.assertEqual(parse_cup_weight("0,78"), 0.78)
        self.assertEqual(parse_cup_weight("1 кг"), 1.0)
        self.assertIsNone(parse_cup_weight("0"))
        with self.assertRaises(ValueError):
            parse_cup_weight("много")
        with self.assertRaises(ValueError):
            parse_cup_weight("10 г")

    # --- «не несутся»

    def test_exclusion_group_extend_and_stale(self) -> None:
        hens = self.feed_service.create_bird_group(user_id=1, name="Несушки", bird_count=10, role="hens")
        young = self.feed_service.create_bird_group(user_id=1, name="Молодки", bird_count=4, role="hens")
        roosters = self.feed_service.create_bird_group(user_id=1, name="Петухи", bird_count=2, role="roosters")

        self.assertEqual({g.id for g in self.eggs.laying_groups(1)}, {hens.id, young.id})
        with self.assertRaises(ValueError):
            self.eggs.create_exclusion(user_id=1, hens_count=5, reason="molting", bird_group_id=young.id)
        with self.assertRaises(ValueError):
            self.eggs.create_exclusion(user_id=1, hens_count=1, reason="molting", bird_group_id=roosters.id)

        started = TODAY - timedelta(days=20)
        dated = self.eggs.create_exclusion(
            user_id=1, hens_count=2, reason="molting", started_at=started,
            expected_until=TODAY - timedelta(days=1), bird_group_id=young.id,
        )
        undated = self.eggs.create_exclusion(user_id=1, hens_count=1, reason="broody", started_at=TODAY - timedelta(days=31))
        fresh = self.eggs.create_exclusion(user_id=1, hens_count=1, reason="broody", started_at=TODAY - timedelta(days=3))

        stale = {item.id for item in self.eggs.stale_exclusions(1, today=TODAY)}
        self.assertEqual(stale, {dated.id, undated.id})
        self.assertNotIn(fresh.id, stale)
        self.assertEqual(
            next(i for i in self.eggs.list_open_exclusions(1) if i.id == dated.id).bird_group_name, "Молодки"
        )

        extended = self.eggs.extend_exclusion(user_id=1, exclusion_id=dated.id)
        self.assertGreaterEqual(extended.expected_until, date.today() + timedelta(days=6))
        self.assertIsNone(self.eggs.extend_exclusion(user_id=2, exclusion_id=dated.id))

    # --- why eggs did not hatch

    def test_batch_losses(self) -> None:
        from app.storage.repositories.batches import BatchRepository
        from app.services.incubation import IncubationService

        service = IncubationService(BatchRepository(self.database))
        batch = service.create_batch(user_id=1, species="chicken", eggs_count=30, start_date=TODAY - timedelta(days=25))
        with self.assertRaises(ValueError):
            save_batch_losses(self.database, user_id=1, batch=batch, losses=BatchLosses(1, 1, 1))
        done = service.complete_batch(batch_id=batch.id, user_id=1, hatched_count=20, completed_at=TODAY)

        with self.assertRaises(ValueError):
            save_batch_losses(self.database, user_id=1, batch=done, losses=BatchLosses(6, 3, 2))  # 11 > 10
        save_batch_losses(self.database, user_id=1, batch=done, losses=parse_batch_losses("6 3 1"))
        save_batch_losses(self.database, user_id=1, batch=done, losses=parse_batch_losses("5, 3, 1"))  # update

        losses = load_batch_losses(self.database, 1)
        self.assertEqual(losses[done.id], BatchLosses(5, 3, 1))
        text = "\n".join(incubation_results_lines([done], {"chicken": "Куры"}, losses))
        self.assertIn("неоплод 5, замершие 3, не вылупились 1", text)
        self.assertIn("проверьте петуха", text)
        self.assertEqual(load_batch_losses(self.database, 2), {})
        with self.assertRaises(ValueError):
            parse_batch_losses("5 3")

    def test_results_hint_without_losses(self) -> None:
        batch = IncubationBatch(1, 1, "chicken", 10, TODAY, "Партия", False, 8)
        self.assertIn("Почему не вывелись", "\n".join(incubation_results_lines([batch], {})))


class AdminActivityTest(RefinementsTest):
    def test_admin_stats_show_activity_and_release(self) -> None:
        from types import SimpleNamespace

        from app.services.admin import AdminService
        from app.storage.repositories.analytics import AnalyticsRepository
        from app.storage.repositories.notifications import NotificationRepository
        from app.storage.repositories.users import UserRepository

        self.feed_service.create_bird_group(user_id=1, name="Несушки", bird_count=10, role="hens")
        self.eggs.record_today(1, 9)
        self.feeding.record(1, cups=3)
        config = SimpleNamespace(
            db_path=self.database.path, backup_dir=Path(self.temp_dir.name), admin_ids=frozenset({1}),
            release_version="0.1.9-beta", release_commit="abcdef1234567", release_deployed_at="2026-10-17T08:00:00Z",
        )
        service = AdminService(
            database=self.database, users=UserRepository(self.database),
            notifications=NotificationRepository(self.database), analytics=AnalyticsRepository(self.database),
            config=config,
        )

        stats = service.get_stats()

        self.assertEqual(stats.records_30d["Сборов яиц"], 1)
        self.assertEqual(stats.records_30d["Кормлений"], 1)
        self.assertEqual(stats.last_backup, "нет")


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class ExclusionCheckRunnerTest(RefinementsTest):
    def test_stale_exclusion_question_once_a_week(self) -> None:
        from app.services.incubation import IncubationService
        from app.services.reminders import ReminderRunner
        from app.storage.repositories.batches import BatchRepository
        from app.storage.repositories.notifications import NotificationRepository
        from app.storage.repositories.users import UserRepository

        self.feed_service.create_bird_group(user_id=1, name="Несушки", bird_count=10, role="hens")
        now_day = date.today()
        self.eggs.create_exclusion(
            user_id=1, hens_count=2, reason="molting", started_at=now_day - timedelta(days=20),
            expected_until=now_day - timedelta(days=1),
        )
        users = UserRepository(self.database)
        users.upsert(user_id=1, first_name="Никита")

        class Bot:
            def __init__(self) -> None:
                self.sent = []

            async def send_message(self, user_id, text, reply_markup=None) -> None:
                self.sent.append((text, reply_markup))

        bot = Bot()
        runner = ReminderRunner(
            bot=bot,
            incubation_service=IncubationService(BatchRepository(self.database)),
            egg_service=self.eggs,
            users=users,
            notifications=NotificationRepository(self.database),
            timezone="Europe/Moscow",
        )
        evening = datetime.combine(now_day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
        asyncio.run(runner._send_exclusion_checks(evening))
        asyncio.run(runner._send_exclusion_checks(evening + timedelta(hours=1)))

        self.assertEqual(len(bot.sent), 1)
        self.assertIn("снова несутся", bot.sent[0][0].lower())
        callbacks = [b.callback_data for row in bot.sent[0][1].inline_keyboard for b in row]
        self.assertTrue(any(c.startswith("eggs:exclude_extend:") for c in callbacks))


if __name__ == "__main__":
    unittest.main()
