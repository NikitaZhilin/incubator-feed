"""Egg storage: places, auto placement, oldest first, recount, move, undo."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from app.services.egg_storage import EggStorage, storage_lines
from app.services.eggs import EggService
from app.services.feeds import FeedService
from app.services.ledger import LedgerService
from app.storage.database import Database
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository


class EggStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "t.db")
        self.database.initialize()
        feeds = FeedRepository(self.database)
        FeedService(feeds).create_bird_group(user_id=1, name="Несушки", bird_count=14, role="hens")
        self.eggs = EggService(EggRepository(self.database), feeds, timezone_name="Europe/Moscow")
        self.ledger = LedgerService(self.database, FeedService(feeds))
        self.storage: EggStorage = self.eggs.storage
        self.today = self.eggs.current_date()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _totals(self) -> dict[str, int]:
        return {s.place.name: s.total for s in self.storage.contents(1)}

    def test_nothing_happens_until_storage_is_set_up(self) -> None:
        self.eggs.record_today(1, 10)
        self.assertEqual(self.storage.contents(1), [])
        self.assertEqual(storage_lines(self.storage, 1, today=self.today), [])

    def test_owner_scenario_door_first_then_trays(self) -> None:
        door, trays = self.storage.setup_default(1)
        # Today: 20 on the door shelves, 30 in trays (a bit older).
        self.storage.recount(1, door.id, 20, today=self.today, age="fresh")
        self.storage.recount(1, trays.id, 30, today=self.today, age="week2")

        self.eggs.record_today(1, 10)  # door has room for 4, the rest goes to trays

        self.assertEqual(self._totals(), {"Дверца холодильника": 24, "Лотки": 36})

        # A tray is sold from the trays: the oldest eggs leave first.
        sold = self.ledger.record_outflow(
            user_id=1, kind="sold", eggs_count=30, amount_rub=450, occurred_on=self.today, place_id=trays.id
        )
        self.assertEqual(self._totals()["Лотки"], 6)
        remaining = [lot.laid_on for lot in self.storage.contents(1)[1].lots]
        self.assertEqual(remaining, [self.today])  # only today's overflow is left

        self.ledger.undo_outflow(1, sold.id)
        self.assertEqual(self._totals()["Лотки"], 36)
        self.assertEqual(self.ledger.egg_balance(1, today=self.today).at_home, 60)

    def test_eaten_without_place_takes_oldest_anywhere(self) -> None:
        door, trays = self.storage.setup_default(1)
        self.storage.recount(1, trays.id, 5, today=self.today, age="old")
        self.storage.recount(1, door.id, 5, today=self.today, age="fresh")

        self.ledger.record_outflow(user_id=1, kind="eaten", eggs_count=6, amount_rub=None, occurred_on=self.today)

        self.assertEqual(self._totals(), {"Дверца холодильника": 4, "Лотки": 0})

    def test_entry_edit_and_delete_follow_storage(self) -> None:
        self.storage.setup_default(1)
        entry = self.eggs.record_today(1, 10)
        self.eggs.update_entry(user_id=1, entry_id=entry.id, eggs_count=12)
        self.assertEqual(self.storage.total(1), 12)
        self.eggs.update_entry(user_id=1, entry_id=entry.id, eggs_count=7)
        self.assertEqual(self.storage.total(1), 7)
        self.eggs.delete_entry(user_id=1, entry_id=entry.id)
        self.assertEqual(self.storage.total(1), 0)

    def test_recount_move_and_old_warning(self) -> None:
        door, trays = self.storage.setup_default(1)
        self.storage.recount(1, trays.id, 30, today=self.today, age="old")
        self.assertIn("Старше 3 недель", "\n".join(storage_lines(self.storage, 1, today=self.today + timedelta(days=5))))

        self.assertEqual(self.storage.recount(1, trays.id, 25, today=self.today), -5)
        moved = self.storage.move(1, trays.id, door.id, 10)
        self.assertEqual(moved, 10)
        self.assertEqual(self._totals(), {"Дверца холодильника": 10, "Лотки": 15})
        with self.assertRaises(ValueError):
            self.storage.move(1, door.id, door.id, 1)
        with self.assertRaises(ValueError):
            self.storage.remove_place(1, trays.id)

    def test_places_validation_and_user_isolation(self) -> None:
        self.storage.setup_default(1)
        shelf = self.storage.add_place(1, "Полка в кладовке", None)
        with self.assertRaises(ValueError):
            self.storage.add_place(1, "полка в кладовке", 10)
        with self.assertRaises(ValueError):
            self.storage.add_place(1, "x", 10)
        self.assertTrue(self.storage.remove_place(1, shelf.id))
        self.assertEqual(self.storage.contents(2), [])
        self.assertIsNone(self.storage.get_place(2, shelf.id))


if __name__ == "__main__":
    unittest.main()
