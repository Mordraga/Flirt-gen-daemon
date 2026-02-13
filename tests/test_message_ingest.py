import unittest

from message_ingest import (
    build_output_path,
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


if __name__ == "__main__":
    unittest.main()
