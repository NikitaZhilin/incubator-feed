from datetime import datetime, time, timedelta, timezone
from math import floor, isfinite

from app.domain import BirdGroup, FeedEstimate, FeedStock, FeedTransaction
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.analytics import AnalyticsRepository


class FeedService:
    def __init__(self, feeds: FeedRepository, analytics: AnalyticsRepository | None = None) -> None:
        self.feeds = feeds
        self.analytics = analytics

    def create_feed(
        self,
        *,
        user_id: int,
        name: str,
        amount_kg: float,
        bird_count: int,
        daily_per_bird_g: float,
        low_threshold_kg: float,
        bird_group_id: int | None = None,
        hen_count: int | None = None,
        rooster_count: int | None = None,
        hen_daily_g: float | None = None,
        rooster_daily_g: float | None = None,
    ) -> FeedStock:
        clean_name = name.strip()[:255]
        if not clean_name:
            raise ValueError("Название корма не может быть пустым.")
        if not isfinite(amount_kg) or amount_kg <= 0:
            raise ValueError("Количество корма должно быть больше нуля.")
        if bird_count <= 0:
            raise ValueError("Количество птиц должно быть больше нуля.")
        if not isfinite(daily_per_bird_g) or daily_per_bird_g <= 0:
            raise ValueError("Расход на птицу должен быть больше нуля.")
        hen_count = bird_count if hen_count is None and rooster_count is None else int(hen_count or 0)
        rooster_count = int(rooster_count or 0)
        if hen_count < 0 or rooster_count < 0 or hen_count + rooster_count <= 0:
            raise ValueError("Укажите количество кур и петухов: хотя бы одна птица должна быть больше нуля.")
        bird_count = hen_count + rooster_count
        hen_daily_g = daily_per_bird_g if hen_daily_g is None else hen_daily_g
        rooster_daily_g = daily_per_bird_g if rooster_daily_g is None else rooster_daily_g
        if not isfinite(hen_daily_g) or hen_daily_g <= 0:
            raise ValueError("Расход на курицу должен быть больше нуля.")
        if rooster_count > 0 and (not isfinite(rooster_daily_g) or rooster_daily_g <= 0):
            raise ValueError("Расход на петуха должен быть больше нуля.")
        if not isfinite(low_threshold_kg) or low_threshold_kg < 0:
            raise ValueError("Порог покупки не может быть отрицательным.")
        if bird_group_id is not None:
            group = self.feeds.get_bird_group(bird_group_id, user_id)
            if group is None:
                raise ValueError("Группа птицы не найдена.")
            if bird_count != group.bird_count:
                raise ValueError(
                    f"В выбранной группе {group.bird_count} птиц. "
                    "Сумма кур и петухов должна совпадать с группой."
                )
        feed = self.feeds.create(
            user_id=user_id,
            name=clean_name,
            amount_kg=amount_kg,
            bird_count=bird_count,
            daily_per_bird_g=daily_per_bird_g,
            low_threshold_kg=low_threshold_kg,
            bird_group_id=bird_group_id,
            hen_count=hen_count,
            rooster_count=rooster_count,
            hen_daily_g=hen_daily_g,
            rooster_daily_g=rooster_daily_g,
        )
        self._track("feed_created", user_id=user_id, feed_id=feed.id)
        return feed

    def list_user_estimates(
        self,
        user_id: int,
        *,
        now: datetime | None = None,
        reminder_time: time | None = None,
    ) -> list[FeedEstimate]:
        return [
            self.estimate(feed, now=now, reminder_time=reminder_time)
            for feed in self.feeds.list_for_user(user_id)
        ]

    def get_estimate(
        self,
        feed_id: int,
        user_id: int,
        *,
        now: datetime | None = None,
        reminder_time: time | None = None,
    ) -> FeedEstimate | None:
        feed = self.feeds.get(feed_id, user_id)
        if feed is None:
            return None
        return self.estimate(feed, now=now, reminder_time=reminder_time)

    def delete_feed(self, feed_id: int, user_id: int) -> bool:
        archived = self.feeds.archive(feed_id, user_id)
        if archived:
            self._track("feed_archived", user_id=user_id, feed_id=feed_id)
        return archived

    def update_feed(
        self,
        *,
        feed_id: int,
        user_id: int,
        name: str | None = None,
        bird_count: int | None = None,
        daily_per_bird_g: float | None = None,
        low_threshold_kg: float | None = None,
        bird_group_id: int | None = None,
        hen_count: int | None = None,
        rooster_count: int | None = None,
        hen_daily_g: float | None = None,
        rooster_daily_g: float | None = None,
        clear_bird_group: bool = False,
    ) -> FeedStock | None:
        current = self.feeds.get(feed_id, user_id)
        if current is None:
            return None
        if name is not None:
            name = name.strip()[:255]
            if not name:
                raise ValueError("Название корма не может быть пустым.")
        if bird_count is not None and bird_count <= 0:
            raise ValueError("Количество птиц должно быть больше нуля.")
        if daily_per_bird_g is not None and (
            not isfinite(daily_per_bird_g) or daily_per_bird_g <= 0
        ):
            raise ValueError("Расход на птицу должен быть больше нуля.")
        if hen_count is not None and hen_count < 0:
            raise ValueError("Количество кур не может быть отрицательным.")
        if rooster_count is not None and rooster_count < 0:
            raise ValueError("Количество петухов не может быть отрицательным.")
        next_hen_count = current.hen_count if hen_count is None else hen_count
        next_rooster_count = current.rooster_count if rooster_count is None else rooster_count
        if next_hen_count + next_rooster_count <= 0:
            raise ValueError("Укажите хотя бы одну курицу или одного петуха.")
        if hen_daily_g is not None and (not isfinite(hen_daily_g) or hen_daily_g <= 0):
            raise ValueError("Расход на курицу должен быть больше нуля.")
        if rooster_daily_g is not None and (
            not isfinite(rooster_daily_g) or rooster_daily_g <= 0
        ):
            raise ValueError("Расход на петуха должен быть больше нуля.")
        if low_threshold_kg is not None and (
            not isfinite(low_threshold_kg) or low_threshold_kg < 0
        ):
            raise ValueError("Порог покупки не может быть отрицательным.")
        sync_gender_counts = False
        if bird_group_id is not None:
            group = self.feeds.get_bird_group(bird_group_id, user_id)
            if group is None:
                raise ValueError("Группа птицы не найдена.")
            if next_hen_count + next_rooster_count != group.bird_count:
                next_hen_count = group.bird_count
                next_rooster_count = 0
                sync_gender_counts = True
            bird_count = next_hen_count + next_rooster_count
        elif hen_count is not None or rooster_count is not None:
            bird_count = next_hen_count + next_rooster_count
        if daily_per_bird_g is not None:
            hen_daily_g = daily_per_bird_g if hen_daily_g is None else hen_daily_g
            rooster_daily_g = daily_per_bird_g if rooster_daily_g is None else rooster_daily_g
        feed = self.feeds.update(
            feed_id=feed_id,
            user_id=user_id,
            name=name,
            bird_count=bird_count,
            daily_per_bird_g=daily_per_bird_g,
            low_threshold_kg=low_threshold_kg,
            bird_group_id=bird_group_id,
            hen_count=(
                next_hen_count
                if sync_gender_counts or hen_count is not None or rooster_count is not None
                else None
            ),
            rooster_count=(
                next_rooster_count
                if sync_gender_counts or hen_count is not None or rooster_count is not None
                else None
            ),
            hen_daily_g=hen_daily_g,
            rooster_daily_g=rooster_daily_g,
            clear_bird_group=clear_bird_group,
        )
        if feed is not None:
            self._track("feed_updated", user_id=user_id, feed_id=feed_id)
        return feed

    def restock_feed(
        self,
        *,
        feed_id: int,
        user_id: int,
        amount_kg: float,
        updated_at: datetime | None = None,
    ) -> FeedStock | None:
        if not isfinite(amount_kg) or amount_kg <= 0:
            raise ValueError("Количество корма должно быть больше нуля.")
        feed = self.feeds.update_stock(
            feed_id=feed_id,
            user_id=user_id,
            amount_kg=amount_kg,
            updated_at=updated_at or datetime.now(timezone.utc),
        )
        if feed is not None:
            self._track("feed_adjusted", user_id=user_id, feed_id=feed_id)
        return feed

    def add_feed_amount(
        self,
        *,
        feed_id: int,
        user_id: int,
        amount_kg: float,
        note: str = "",
    ) -> FeedStock | None:
        if not isfinite(amount_kg) or amount_kg <= 0:
            raise ValueError("Пополнение должно быть больше нуля.")
        feed = self.feeds.change_stock(
            feed_id=feed_id,
            user_id=user_id,
            delta_kg=amount_kg,
            transaction_type="restock",
            note=note,
        )
        if feed is not None:
            self._track("feed_restocked", user_id=user_id, feed_id=feed_id)
        return feed

    def write_off_feed(
        self,
        *,
        feed_id: int,
        user_id: int,
        amount_kg: float,
        note: str = "",
    ) -> FeedStock | None:
        if not isfinite(amount_kg) or amount_kg <= 0:
            raise ValueError("Списание должно быть больше нуля.")
        feed = self.feeds.change_stock(
            feed_id=feed_id,
            user_id=user_id,
            delta_kg=-amount_kg,
            transaction_type="write_off",
            note=note,
        )
        if feed is not None:
            self._track("feed_written_off", user_id=user_id, feed_id=feed_id)
        return feed

    def list_transactions(self, feed_id: int, user_id: int) -> list[FeedTransaction]:
        return self.feeds.list_transactions(feed_id, user_id)

    def create_bird_group(
        self,
        *,
        user_id: int,
        name: str,
        bird_count: int,
        species: str | None = None,
    ) -> BirdGroup:
        clean_name = name.strip()[:255]
        if not clean_name:
            raise ValueError("Название группы не может быть пустым.")
        if bird_count <= 0:
            raise ValueError("Количество птиц должно быть больше нуля.")
        return self.feeds.create_bird_group(
            user_id=user_id,
            name=clean_name,
            bird_count=bird_count,
            species=species,
        )

    def list_bird_groups(self, user_id: int) -> list[BirdGroup]:
        return self.feeds.list_bird_groups(user_id)

    def get_bird_group(self, group_id: int, user_id: int) -> BirdGroup | None:
        return self.feeds.get_bird_group(group_id, user_id)

    def _track(self, event_name: str, *, user_id: int, feed_id: int) -> None:
        if self.analytics is not None:
            self.analytics.track(
                event_name,
                user_id=user_id,
                entity_type="feed",
                entity_id=feed_id,
            )

    def list_due_purchase_reminders(self, now: datetime) -> list[FeedEstimate]:
        due: list[FeedEstimate] = []
        for feed in self.feeds.list_all():
            if feed.purchase_reminded_at is not None:
                continue
            estimate = self.estimate(feed, now=now)
            if estimate.remaining_kg <= feed.low_threshold_kg:
                due.append(estimate)
        return due

    def mark_purchase_reminded(self, feed_id: int, reminded_at: datetime) -> None:
        self.feeds.mark_purchase_reminded(feed_id, reminded_at)

    @staticmethod
    def estimate(
        feed: FeedStock,
        *,
        now: datetime | None = None,
        reminder_time: time | None = None,
    ) -> FeedEstimate:
        current = now or datetime.now(timezone.utc)
        baseline = feed.updated_at or feed.created_at
        current, baseline = FeedService._align_datetimes(current, baseline)
        elapsed_days = max((current - baseline).total_seconds() / 86400, 0)
        hen_count = feed.hen_count if feed.hen_count or feed.rooster_count else feed.bird_count
        rooster_count = feed.rooster_count
        hen_daily_g = feed.hen_daily_g if feed.hen_daily_g is not None else feed.daily_per_bird_g
        rooster_daily_g = (
            feed.rooster_daily_g if feed.rooster_daily_g is not None else feed.daily_per_bird_g
        )
        daily_usage_kg = (hen_count * hen_daily_g + rooster_count * rooster_daily_g) / 1000
        if daily_usage_kg <= 0:
            return FeedEstimate(feed, feed.amount_kg, 0, None, None, None)

        remaining_kg = max(feed.amount_kg - elapsed_days * daily_usage_kg, 0)
        days_left = floor(remaining_kg / daily_usage_kg)
        threshold_days_left = floor(max(remaining_kg - feed.low_threshold_kg, 0) / daily_usage_kg)

        buy_remind_at = None
        if reminder_time is not None:
            buy_date = current.date() + timedelta(days=threshold_days_left)
            buy_remind_at = datetime.combine(buy_date, reminder_time)
            if buy_remind_at <= current:
                buy_remind_at = current + timedelta(minutes=5)

        return FeedEstimate(
            feed=feed,
            remaining_kg=remaining_kg,
            daily_usage_kg=daily_usage_kg,
            days_left=days_left,
            threshold_days_left=threshold_days_left,
            buy_remind_at=buy_remind_at,
        )

    @staticmethod
    def _align_datetimes(current: datetime, created_at: datetime) -> tuple[datetime, datetime]:
        if current.tzinfo is None and created_at.tzinfo is not None:
            current = current.replace(tzinfo=created_at.tzinfo)
        elif current.tzinfo is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=current.tzinfo)
        return current, created_at
