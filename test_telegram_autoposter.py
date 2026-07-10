import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from telethon import types
from telethon import utils

from telegram_autoposter import (
    MessagePayload,
    PostResult,
    PreparedPost,
    SequencedPayload,
    Target,
    batch_channel_records,
    build_scheduled_posts,
    load_owned_posts_state,
    list_media_pool_files,
    prepare_posts,
    save_owned_post,
    split_channel_sequence,
)


class MultiPostParserTests(unittest.TestCase):
    def test_win_files_are_not_used_for_ordinary_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            media_pool = Path(temporary_directory)
            (media_pool / "20260710_ordinary_01.png").touch()
            (media_pool / "20260710_win_01.png").touch()

            available = list_media_pool_files(media_pool)

        self.assertEqual([path.name for path in available], ["20260710_ordinary_01.png"])

    def test_parses_relative_followup_and_win_placeholder(self) -> None:
        lines = [
            "**Пост 1:** first post",
            "",
            "https://twitch.tv/yourlink",
            "",
            "**[Через 12 минут] Пост 2:** second post",
            "",
            "[СЮДА КИДАЕМ СКРИНШОТ ЗАНОСА]",
        ]

        sequence = split_channel_sequence(lines, Path("."), "example")

        self.assertEqual(len(sequence), 2)
        self.assertEqual(sequence[0].sequence_index, 1)
        self.assertEqual(sequence[1].sequence_index, 2)
        self.assertEqual(sequence[1].delay_after_previous, 12 * 60)
        self.assertEqual(sequence[1].payload.media_role, "win")
        self.assertNotIn("СЮДА КИДАЕМ", sequence[1].payload.body)

    def test_win_placeholder_cannot_receive_ordinary_rotation_image(self) -> None:
        target = Target("Channel", types.PeerChannel(100))
        sequence = (
            SequencedPayload(
                payload=MessagePayload("first"),
                sequence_index=1,
            ),
            SequencedPayload(
                payload=MessagePayload("win", media_role="win"),
                sequence_index=2,
                delay_after_previous=60,
            ),
        )

        with self.assertRaisesRegex(SystemExit, "requires a win screenshot"):
            prepare_posts(
                [target],
                None,
                [sequence],
                {},
                {"channel": Path("ordinary.png")},
            )


class SchedulingAndOwnershipTests(unittest.TestCase):
    def make_post(
        self,
        target: Target,
        index: int,
        count: int,
        delay: float = 0,
    ) -> PreparedPost:
        return PreparedPost(
            target=target,
            body=f"post {index}",
            original_body=f"post {index}",
            media_paths=(),
            auto_media_path=None,
            managed_media_paths=(),
            rotation_key=str(target.entity.channel_id),
            sequence_index=index,
            sequence_count=count,
            delay_after_previous=delay,
        )

    def test_followup_is_scheduled_after_its_own_first_post(self) -> None:
        first_target = Target("One", types.PeerChannel(1))
        second_target = Target("Two", types.PeerChannel(2))
        posts = [
            self.make_post(first_target, 1, 2),
            self.make_post(first_target, 2, 2, 12 * 60),
            self.make_post(second_target, 1, 1),
        ]
        args = SimpleNamespace(
            delay_every=2,
            delay_profile="uniform",
            delay_min=5 * 60,
            delay_max=5 * 60,
        )

        scheduled = build_scheduled_posts(args, posts)

        self.assertEqual(
            [(item.post.target.title, item.post.sequence_index) for item in scheduled],
            [("One", 1), ("Two", 1), ("One", 2)],
        )
        self.assertEqual(scheduled[-1].offset_seconds, 12 * 60)

    def test_sent_post_is_persisted_as_owned_for_the_same_batch(self) -> None:
        target = Target("One", types.PeerChannel(1))
        post = self.make_post(target, 1, 2)
        result = PostResult(
            channel="One",
            message_id=55,
            link="https://t.me/c/1/55",
            views=0,
            static_id=1806,
            reaction_id=343,
            random_views=2200,
            random_reactions=30,
            status="posted",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "owned.json"
            state = load_owned_posts_state(path)
            save_owned_post(path, state, "batch-a", "Europe/Moscow", post, result)
            reloaded = load_owned_posts_state(path)

        records = batch_channel_records(reloaded, "batch-a")
        peer_id = utils.get_peer_id(target.entity)
        self.assertEqual(records[peer_id][1]["message_id"], 55)
        self.assertIn("sent_at", records[peer_id][1])

    def test_resumed_followup_uses_remaining_delay_from_owned_first_post(self) -> None:
        target = Target("One", types.PeerChannel(1))
        followup = self.make_post(target, 2, 2, 12 * 60)
        args = SimpleNamespace(
            delay_every=2,
            delay_profile="uniform",
            delay_min=5 * 60,
            delay_max=5 * 60,
        )
        peer_id = utils.get_peer_id(target.entity)
        owned = {
            peer_id: {
                1: {
                    "message_id": 55,
                    "sent_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=6)
                    ).isoformat(),
                }
            }
        }

        scheduled = build_scheduled_posts(args, [followup], owned)

        self.assertAlmostEqual(scheduled[0].offset_seconds, 6 * 60, delta=2)


if __name__ == "__main__":
    unittest.main()
