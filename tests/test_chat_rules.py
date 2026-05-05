import unittest

from chat_rules import sanitize_chat_count_config, should_count_channel_message, should_count_voice_time


class TestChatRules(unittest.TestCase):
    def test_sanitize_config_normalizes_and_deduplicates(self):
        raw = {
            "exclude_name_keywords": [" Call ", "", "VOZ", "voz"],
            "exclude_channel_ids_by_guild": {
                "123": [1, "2", "x", 1, None],
                "": [99],
            },
        }
        cfg = sanitize_chat_count_config(raw)
        self.assertEqual(cfg["exclude_name_keywords"], ["call", "voz"])
        self.assertEqual(cfg["exclude_channel_ids_by_guild"]["123"], [1, 2])
        self.assertNotIn("", cfg["exclude_channel_ids_by_guild"])

    def test_should_exclude_by_channel_id(self):
        cfg = sanitize_chat_count_config(
            {
                "exclude_name_keywords": [],
                "exclude_channel_ids_by_guild": {"10": [999]},
            }
        )
        self.assertFalse(
            should_count_channel_message(
                channel_id=999,
                channel_name="geral",
                category_name="texto",
                guild_id=10,
                cfg=cfg,
            )
        )

    def test_should_exclude_by_keyword(self):
        cfg = sanitize_chat_count_config(
            {
                "exclude_name_keywords": ["call", "voz"],
                "exclude_channel_ids_by_guild": {},
            }
        )
        self.assertFalse(
            should_count_channel_message(
                channel_id=1,
                channel_name="chat-call",
                category_name="geral",
                guild_id=10,
                cfg=cfg,
            )
        )

    def test_should_count_when_no_match(self):
        cfg = sanitize_chat_count_config(
            {
                "exclude_name_keywords": ["call", "voz"],
                "exclude_channel_ids_by_guild": {"10": [888]},
            }
        )
        self.assertTrue(
            should_count_channel_message(
                channel_id=1,
                channel_name="bate-papo",
                category_name="texto",
                guild_id=10,
                cfg=cfg,
            )
        )

    def test_voice_time_keywords_only_channel_name_not_category(self):
        cfg = sanitize_chat_count_config(
            {
                "exclude_name_keywords": ["voz"],
                "exclude_channel_ids_by_guild": {},
            }
        )
        # Categoria "Canais de Voz" nao deve bloquear tempo de voz (so o nome do canal importa)
        self.assertTrue(
            should_count_voice_time(
                channel_id=1,
                channel_name="Sala 1",
                guild_id=10,
                cfg=cfg,
            )
        )
        self.assertFalse(
            should_count_voice_time(
                channel_id=2,
                channel_name="sala-voz",
                guild_id=10,
                cfg=cfg,
            )
        )

    def test_voice_time_respects_excluded_id(self):
        cfg = sanitize_chat_count_config(
            {
                "exclude_name_keywords": [],
                "exclude_channel_ids_by_guild": {"10": [999]},
            }
        )
        self.assertFalse(
            should_count_voice_time(
                channel_id=999,
                channel_name="Geral",
                guild_id=10,
                cfg=cfg,
            )
        )

    def test_voice_whitelist_only_listed(self):
        cfg = sanitize_chat_count_config(
            {
                "include_voice_channel_ids_by_guild": {"10": [100, 200]},
                "exclude_name_keywords": ["call"],
                "exclude_channel_ids_by_guild": {"10": [100]},
            }
        )
        self.assertTrue(should_count_voice_time(100, "qualquer", 10, cfg))
        self.assertTrue(should_count_voice_time(200, "qualquer", 10, cfg))
        self.assertFalse(should_count_voice_time(300, "geral", 10, cfg))

    def test_voice_without_whitelist_uses_exclude(self):
        cfg = sanitize_chat_count_config(
            {
                "include_voice_channel_ids_by_guild": {"10": []},
                "exclude_name_keywords": ["afk"],
                "exclude_channel_ids_by_guild": {"10": [9]},
            }
        )
        self.assertFalse(should_count_voice_time(9, "x", 10, cfg))
        self.assertFalse(should_count_voice_time(1, "sala-afk", 10, cfg))
        self.assertTrue(should_count_voice_time(1, "Geral", 10, cfg))


if __name__ == "__main__":
    unittest.main()
