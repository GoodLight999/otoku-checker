import unittest

from scrape_common import decode_bytes, is_useful_content, repair_mojibake


class ScrapeCommonTests(unittest.TestCase):
    def test_repairs_utf8_text_decoded_as_latin1(self):
        original = "対象店舗で最大20％ポイント還元｜三菱UFJカード セブン-イレブン"
        broken = original.encode("utf-8").decode("latin-1")

        self.assertEqual(repair_mojibake(broken), original)

    def test_decodes_utf8_without_charset(self):
        html = "<html><body>三菱UFJ 対象店舗 セブン-イレブン</body></html>"
        decoded = decode_bytes(html.encode("utf-8"), {"content-type": "text/html"})

        self.assertIn("三菱UFJ", decoded)
        self.assertIn("対象店舗", decoded)

    def test_rejects_non_official_content(self):
        self.assertFalse(is_useful_content("MUFG", "Access Denied" * 100))

    def test_accepts_expected_mufg_markers(self):
        html = "三菱UFJ 対象店舗 セブン " + ("説明文" * 300)

        self.assertTrue(is_useful_content("MUFG", html))


if __name__ == "__main__":
    unittest.main()
