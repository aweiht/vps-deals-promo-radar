# ::ILANG
# [TYPE:test][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:验证 OVH 官方四计划规格提取与缺失数据处理}
# ::BOUNDARY{never:将离线来源样例当成当前报价 编造缺失硬件规格}
"""Regression coverage for the observed OVHcloud US plan specifications."""
from pathlib import Path
import re
import unittest

from config import read_config
from scraper import parse_offers


FIXTURE = (Path(__file__).parent / "fixtures/ovhcloud-vps-current.html").read_text(encoding="utf-8")
FETCHED = "2026-11-06T17:42:39Z"
SOURCE_DIGEST = "f7691fa79cc4f0d66a38041999a81df87bd6c55d4afa180a492d74068fcb8718"


class OVHSpecificationsTests(unittest.TestCase):
    def setUp(self):
        self.provider = next(p for p in read_config()["providers"] if p["id"] == "ovhcloud")

    def parse(self, html=FIXTURE):
        return parse_offers(html, self.provider, FETCHED, self.provider["source_url"], SOURCE_DIGEST)

    def test_all_four_plans_keep_their_own_source_specs_and_price(self):
        offers = self.parse()
        self.assertEqual(len(offers), 4)
        expected = {
            "VPS-1": ("4.54", "2 vCores 4 GB RAM 40 GB SSD NVMe Daily backup of the previous 24 hours Unlimited traffic 500 Mbps public bandwidth"),
            "VPS-2": ("8.50", "4 vCores 8 GB RAM 75 GB SSD NVMe Daily backup of the previous 24 hours Unlimited traffic 1 Gbps public bandwidth"),
            "VPS-3": ("12.32", "6 vCores 12 GB RAM 100 GB SSD NVMe Daily backup of the previous 24 hours Unlimited traffic 2 Gbps public bandwidth"),
            "VPS-4": ("23.37", "8 vCore 24 GB RAM 200 GB SSD NVMe Daily backup of the previous 24 hours Unlimited traffic 3 Gbps public bandwidth"),
        }
        for offer in offers:
            price, details = expected[offer["title"]]
            self.assertEqual(offer["price"], price)
            self.assertEqual(offer["details"], details)
            self.assertIn(details, offer["evidence"])
            self.assertEqual(offer["billing_period"], "/month")
            self.assertEqual(offer["currency"], "USD")
            self.assertEqual(offer["kind"], "standard_price")
            self.assertEqual(offer["source_sha256"], SOURCE_DIGEST)
            self.assertEqual(offer["source_url"], "https://us.ovhcloud.com/vps/")
            self.assertIn("Starting price, excluding tax", offer["terms"])
            self.assertNotIn("valid_until", offer)
            self.assertTrue(offer["offer_url"].startswith("https://us.ovhcloud.com/vps/configurator/"))

    def test_missing_spec_wrapper_does_not_fall_back_to_entire_card(self):
        # Source still contains the words RAM/NVMe, but the configured container is
        # absent. Keep details empty rather than guessing a new source structure.
        changed = FIXTURE.replace("card-specs__wrapper", "fixture-unrecognized-specs")
        offers = self.parse(changed)
        self.assertEqual(len(offers), 4)
        self.assertTrue(all(offer["details"] == "" for offer in offers))
        self.assertTrue(all("GB RAM" in offer["evidence"] for offer in offers))

    def test_missing_single_hardware_value_stays_missing(self):
        # VPS-1's RAM text is removed only in this isolated fixture. Other plans'
        # RAM values must never be copied into it.
        changed = re.sub(r'<p\b[^>]*>(?:(?!</p>).)*\bRAM</p>', "", FIXTURE, count=1, flags=re.S)
        offers = {offer["title"]: offer for offer in self.parse(changed)}
        self.assertNotIn("RAM", offers["VPS-1"]["details"])
        self.assertIn("40 GB SSD NVMe", offers["VPS-1"]["details"])
        self.assertIn("8 GB RAM", offers["VPS-2"]["details"])


if __name__ == "__main__":
    unittest.main()
