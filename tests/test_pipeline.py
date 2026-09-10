# ::ILANG
# [TYPE:test][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:确定性验证配置生效 来源失败 价格真实性和安全渲染}
# ::BOUNDARY{never:把测试样例写进生产数据 用离线测试冒充真实抓取}
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from build import build, observed_status
from config import ROOT, https_url, read_config
from scraper import collect, normalize_price, parse_offers, Document
from verify import verify

# Minimal factual excerpt from RackNerd's official specials page, checked
# 2026-09-10 UTC. Changes below are explicitly synthetic failure-path tests.
CARD = '''<section class="plans-section"><article class="plan-card">
<header class="plan-header"><h3>1 GB KVM VPS</h3></header>
<div class="price"><span class="currency">$</span> 21.99 <span class="period">/year</span></div>
<ul class="plan-features"><li>1 vCPU Core</li><li>20 GB SSD Storage</li><li>1 GB RAM</li></ul>
<footer class="plan-footer"><a class="btn-plan" href="https://my.racknerd.com/cart.php?a=add&amp;pid=952">Order Now</a></footer>
</article></section>'''
NOW = datetime(2026, 9, 10, 21, 0, tzinfo=timezone.utc)
FETCHED = "2026-09-10T21:00:00Z"


class FixtureFetcher:
    def __init__(self, fail=False):
        self.fail = fail
        self.urls = []

    def fetch(self, url, hosts):
        self.urls.append(url)
        if self.fail:
            raise ValueError("Fixture source unavailable")
        return CARD, url, hashlib.sha256(CARD.encode()).hexdigest()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = read_config()
        self.provider = self.config["providers"][0]
        self.config["providers"] = [self.provider]
        self.offer = parse_offers(CARD, self.provider, FETCHED, self.provider["source_url"], hashlib.sha256(CARD.encode()).hexdigest())[0]
        self.data = {"schema_version": 1, "locale": "en-US", "checked_at": FETCHED, "providers": [{"id": self.provider["id"], "name": self.provider["name"], "status": "ok"}], "offers": [self.offer]}
        # Every directory is test-owned; TemporaryDirectory only cleans its own
        # disposable fixtures, never the repository or generated production site.
        self.temp = tempfile.TemporaryDirectory(prefix="vps-deals-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def test_source_price_and_period_are_preserved(self):
        self.assertEqual(self.offer["price"], "21.99")
        self.assertEqual(self.offer["billing_period"], "/year")
        self.assertNotIn("valid_until", self.offer)

    def test_missing_price_is_not_invented(self):
        html = CARD.replace("21.99", "Contact us")
        offer = parse_offers(html, self.provider, FETCHED, self.provider["source_url"], "fixture-sha")[0]
        self.assertNotIn("price", offer)
        self.assertNotIn("currency", offer)

    def test_wrong_market_currency_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "currency"):
            parse_offers(CARD.replace("$", "€"), self.provider, FETCHED, self.provider["source_url"], "fixture-sha")

    def test_ambiguous_price_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_price("$5 or $10")

    def test_official_checkout_allowlist(self):
        with self.assertRaisesRegex(ValueError, "official host"):
            parse_offers(CARD.replace("my.racknerd.com", "unapproved.example"), self.provider, FETCHED, self.provider["source_url"], "fixture-sha")

    def test_duplicate_conflicting_cards_rejected(self):
        provider = copy.deepcopy(self.provider)
        provider["rules"]["deduplicate_identical"] = True
        with self.assertRaisesRegex(ValueError, "conflicting"):
            parse_offers(CARD + CARD.replace("21.99", "22.99"), provider, FETCHED, provider["source_url"], "fixture-sha")
        offers = parse_offers(CARD + CARD, provider, FETCHED, provider["source_url"], "fixture-sha")
        self.assertEqual(len(offers), 1)

    def test_failed_source_preserves_original_evidence_time(self):
        result = collect(self.config, self.data, FixtureFetcher(fail=True))
        self.assertEqual(result["providers"][0]["status"], "error")
        self.assertEqual(result["offers"][0]["source_status"], "error")
        self.assertEqual(result["offers"][0]["fetched_at"], FETCHED)
        self.assertEqual(observed_status(result["offers"][0], self.config, NOW), "stale")

    def test_expiry_and_stale_time(self):
        self.assertEqual(observed_status(self.offer, self.config, NOW), "observed")
        self.assertEqual(observed_status(self.offer, self.config, NOW + timedelta(hours=49)), "stale")
        self.offer["valid_until"] = "2026-09-09"
        self.assertEqual(observed_status(self.offer, self.config, NOW), "expired")

    def test_expired_offer_has_no_purchase_schema_or_current_card(self):
        self.offer["valid_until"] = "2026-09-09"
        build(self.config, self.data, self.work, NOW)
        detail = (self.work / "deals" / self.offer["id"] / "index.html").read_text()
        self.assertIn("Expired", detail)
        self.assertNotIn('"@type": "Product"', detail)
        self.assertNotIn('class="button"', detail)
        self.assertNotIn('class="offer-card"', (self.work / "index.html").read_text())
        verify(self.work, self.config)

    def test_external_text_is_escaped_in_html_and_jsonld(self):
        self.offer["title"] = '</script><script>alert("fixture")</script>'
        build(self.config, self.data, self.work, NOW)
        html = (self.work / "deals" / self.offer["id"] / "index.html").read_text()
        self.assertNotIn('<script>alert(', html)
        self.assertIn("&lt;script&gt;", html)
        json.loads(Document(html).root.select('script[type="application/ld+json"]')[0].text(False))

    def test_ilang_provider_change_controls_scrape_and_render(self):
        text = (ROOT / ".ilang/site.ilang").read_text()
        # Retain one source and change its identity in the only configuration file.
        text = re.sub(r"^  (Hostinger|OVHcloud) \|.*\n", "", text, flags=re.M)
        text = text.replace("RackNerd |", "Configured Name |", 1).replace("SOURCE:racknerd|", "SOURCE:configured-name|")
        path = self.work / "changed.ilang"
        path.write_text(text)
        changed = read_config(path)
        fetcher = FixtureFetcher()
        collected = collect(changed, {}, fetcher)
        self.assertEqual(len(fetcher.urls), 1)
        self.assertEqual(collected["offers"][0]["provider_id"], "configured-name")
        build(changed, collected, self.work / "site")
        index = (self.work / "site/index.html").read_text()
        self.assertIn("Configured Name", index)
        self.assertNotIn('/providers/racknerd/', index)
        self.assertTrue((self.work / "site/providers/configured-name/index.html").exists())

    def test_removed_provider_does_not_leave_live_output(self):
        full = read_config()
        build(full, self.data, self.work, NOW)
        reduced = copy.deepcopy(full)
        reduced["providers"] = reduced["providers"][1:]
        build(reduced, self.data, self.work, NOW)
        self.assertNotIn("RackNerd", (self.work / "index.html").read_text())
        self.assertIn("noindex", (self.work / "providers/racknerd/index.html").read_text())
        published = json.loads((self.work / "data/offers.json").read_text())
        self.assertEqual(published["offers"], [])

    def test_workflow_schedule_matches_ilang(self):
        workflow = (ROOT / ".github/workflows/update.yml").read_text()
        self.assertIn("cron: '" + self.config["runtime"]["schedule"] + "'", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("secrets.", workflow)

    def test_reject_unsafe_or_unimplemented_configuration(self):
        for url in ("http://example.com", "https://localhost", "https://192.168.1.1/", "https://user:password@example.com"):
            with self.assertRaises(ValueError):
                https_url(url)
        path = self.work / "invalid.ilang"
        path.write_text((ROOT / ".ilang/site.ilang").read_text().replace('locale:"en-US"', 'locale:"ja-JP"'))
        with self.assertRaisesRegex(ValueError, "regional sources"):
            read_config(path)

    def test_rendered_artifact_invariants(self):
        result = build(self.config, self.data, self.work, NOW)
        self.assertEqual(result["current_offers"], 1)
        self.assertEqual(verify(self.work, self.config)["offers"], 1)


if __name__ == "__main__":
    unittest.main()
