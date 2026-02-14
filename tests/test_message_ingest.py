import unittest

from message_ingest import (
    build_twitter_audit_payload,
    build_output_path,
    ensure_root_tweet_present,
    IngestedMessage,
    normalize_twitch_oauth_token,
    parse_twitch_privmsg,
)


class MessageIngestTests(unittest.TestCase):
    def test_normalize_twitch_oauth_token(self):
        self.assertEqual(normalize_twitch_oauth_token("oauth:abc"), "oauth:abc")
        self.assertEqual(normalize_twitch_oauth_token("abc"), "oauth:abc")

    def test_parse_twitch_privmsg_extracts_required_fields(self):
        line = (
            "@badge-info=;badges=;color=;display-name=SomeUser;emotes=;id=msg-123;"
            "mod=0;room-id=1;subscriber=0;tmi-sent-ts=1700000000000;user-id=42 :someuser!"
            "someuser@someuser.tmi.twitch.tv PRIVMSG #mychannel :hello world"
        )
        msg = parse_twitch_privmsg(line, "mychannel")
        self.assertIsNotNone(msg)
        assert msg is not None

        self.assertEqual(msg.platform, "twitch")
        self.assertEqual(msg.scope, "channel:mychannel")
        self.assertEqual(msg.message_id, "msg-123")
        self.assertEqual(msg.username, "SomeUser")
        self.assertEqual(msg.user_id, "42")
        self.assertEqual(msg.text, "hello world")
        self.assertTrue(msg.sent_at_utc.endswith("Z"))
        self.assertTrue(msg.captured_at_utc.endswith("Z"))

    def test_build_output_path_sanitizes_scope(self):
        path = build_output_path("twitter", "conversation_id:123/456")
        self.assertEqual(str(path), "logs\\ingest\\twitter_conversation_id_123_456.jsonl")

    def test_ensure_root_tweet_present_adds_missing_root(self):
        reply = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="101",
            username="reply_user",
            user_id="2",
            sent_at_utc="2026-02-13T12:00:01Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="reply",
        )
        root = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="100",
            username="root_user",
            user_id="1",
            sent_at_utc="2026-02-13T12:00:00Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="root",
        )

        merged = ensure_root_tweet_present([reply], root)
        self.assertEqual([m.message_id for m in merged], ["100", "101"])

    def test_ensure_root_tweet_present_no_duplicate(self):
        root = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="100",
            username="root_user",
            user_id="1",
            sent_at_utc="2026-02-13T12:00:00Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="root",
        )

        merged = ensure_root_tweet_present([root], root)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].message_id, "100")

    def test_build_twitter_audit_payload_main_and_replies(self):
        main = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="100",
            username="root_user",
            user_id="1",
            sent_at_utc="2026-02-13T12:00:00Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="root",
        )
        reply = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="101",
            username="reply_user",
            user_id="2",
            sent_at_utc="2026-02-13T12:00:01Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="reply",
        )

        payload = build_twitter_audit_payload("100", [reply, main], None, 1, 100)
        self.assertEqual(payload["Main"]["message_id"], "100")
        self.assertIsNotNone(payload["Main"]["replies"])
        self.assertEqual(payload["Main"]["replies"][0]["message_id"], "101")
        self.assertEqual(payload["meta"]["reply_count"], 1)

    def test_build_twitter_audit_payload_replies_null_when_none(self):
        main = IngestedMessage(
            platform="twitter",
            scope="conversation_id:100",
            message_id="100",
            username="root_user",
            user_id="1",
            sent_at_utc="2026-02-13T12:00:00Z",
            captured_at_utc="2026-02-13T12:00:02Z",
            text="root",
        )

        payload = build_twitter_audit_payload("100", [main], None, 1, 100)
        self.assertEqual(payload["Main"]["message_id"], "100")
        self.assertIsNone(payload["Main"]["replies"])
        self.assertEqual(payload["meta"]["reply_count"], 0)


if __name__ == "__main__":
    unittest.main()
