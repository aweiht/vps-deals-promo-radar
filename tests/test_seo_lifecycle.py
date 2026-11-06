# ::ILANG
# [TYPE:test][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:验证失败恢复索引 页面实质更新时间和真实硬件展示}
# ::BOUNDARY{never:用模拟来源替代真实线上验收 把旧价格冒充当前优惠}
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from build import build, hardware_specs
from config import ROOT, read_config
from scraper import collect, parse_offers, Document
from test_pipeline import CARD, FixtureFetcher
from verify import verify


class SeoLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.config = read_config()
        self.provider = self.config['providers'][0]
        self.config['providers'] = [self.provider]
        self.now = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
        self.when = self.now.isoformat()
        self.offer = parse_offers(CARD, self.provider, self.when, self.provider['source_url'], hashlib.sha256(CARD.encode()).hexdigest())[0]
        self.data = {'schema_version': 1, 'locale': 'en-US', 'checked_at': self.when,
                     'providers': [{'id': self.provider['id'], 'status': 'ok'}], 'offers': [self.offer]}
        self.temp = tempfile.TemporaryDirectory(prefix='vps-seo-test-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.state = self.work / 'data/page-state.json'
        self.url = self.config['site']['domain'] + '/deals/' + self.offer['id'] + '/'

    def render(self, data=None, now=None, directory='site'):
        output = self.work / directory
        build(self.config, data or self.data, output, now or self.now, self.state)
        verify(output, self.config)
        return output

    def dates(self, output):
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        return {u.find('s:loc', ns).text: u.find('s:lastmod', ns).text
                for u in ElementTree.parse(output / 'sitemap.xml').findall('s:url', ns)}

    def test_failed_source_preserves_detail_index_but_removes_current_offer(self):
        self.render()
        failed = collect(self.config, self.data, FixtureFetcher(fail=True))
        failed['checked_at'] = (self.now + timedelta(hours=6)).isoformat()
        output = self.render(failed, self.now + timedelta(hours=6))
        detail = (output / 'deals' / self.offer['id'] / 'index.html').read_text()
        self.assertIn('content="index,follow"', detail)
        self.assertIn('LAST RECORDED PRICE', detail)
        self.assertIn('not currently verified', detail)
        self.assertIn(self.when, detail)
        self.assertNotIn('"@type": "Product"', detail)
        self.assertNotIn('class="button"', detail)
        self.assertNotIn('class="offer-card"', (output / 'index.html').read_text())
        self.assertNotIn(self.offer['title'], (output / 'compare/index.html').read_text())
        self.assertIn(self.url, self.dates(output))
        recovered = copy.deepcopy(self.data)
        recovered['checked_at'] = recovered['offers'][0]['fetched_at'] = (self.now + timedelta(hours=12)).isoformat()
        output = self.render(recovered, self.now + timedelta(hours=12))
        detail = (output / 'deals' / self.offer['id'] / 'index.html').read_text()
        self.assertIn('content="index,follow"', detail)
        self.assertIn('"@type": "Product"', detail)
        self.assertIn('class="button"', detail)
        self.assertIn('class="offer-card"', (output / 'index.html').read_text())

    def test_aged_and_expired_history_leaves_index_without_disappearing(self):
        output = self.render(now=self.now + timedelta(days=30))
        self.assertIn(self.url, self.dates(output))
        output = self.render(now=self.now + timedelta(days=30, seconds=1))
        self.assertNotIn(self.url, self.dates(output))
        self.assertIn('noindex,follow', (output / 'deals' / self.offer['id'] / 'index.html').read_text())
        expired = copy.deepcopy(self.data)
        expired['offers'][0]['valid_until'] = '2026-11-06'
        output = self.render(expired)
        self.assertNotIn(self.url, self.dates(output))

    def test_fresh_checkout_and_repeated_observation_keeps_all_dates(self):
        before = self.dates(self.render())
        checked = copy.deepcopy(self.data)
        checked['checked_at'] = checked['offers'][0]['fetched_at'] = (self.now + timedelta(hours=6)).isoformat()
        checked['offers'][0]['source_sha256'] = 'another-response-hash'
        output = self.render(checked, self.now + timedelta(hours=6), 'fresh-checkout')
        self.assertEqual(self.dates(output), before)
        self.assertIn(checked['checked_at'], (output / 'index.html').read_text())
        # Cosmetic month labels in title/description are observation-only too.
        checked['checked_at'] = checked['offers'][0]['fetched_at'] = '2026-12-01T01:00:00Z'
        output = self.render(checked, datetime(2026, 12, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(self.dates(output), before)

    def test_price_terms_and_about_changes_update_only_affected_pages(self):
        before = self.dates(self.render())
        changed = copy.deepcopy(self.data)
        changed['offers'][0]['price'] = '22.99'
        changed['offers'][0]['price_evidence'] = '$22.99'
        changed['offers'][0]['terms'] = 'New published renewal terms.'
        after = self.dates(self.render(changed, self.now + timedelta(hours=1)))
        about = self.config['site']['domain'] + '/about/'
        self.assertEqual(after[about], before[about])
        for url in set(before) - {about}:
            self.assertNotEqual(after[url], before[url])
        self.config['runtime']['historical_index_days'] = 14
        latest = self.dates(self.render(changed, self.now + timedelta(hours=2)))
        self.assertNotEqual(latest[about], after[about])

    def test_ovh_hardware_is_visible_in_cards_details_and_comparison(self):
        self.config = read_config()
        provider = next(p for p in self.config['providers'] if p['id'] == 'ovhcloud')
        html = (ROOT / 'tests/fixtures/ovhcloud-vps-current.html').read_text()
        offers = parse_offers(html, provider, self.when, provider['source_url'], hashlib.sha256(html.encode()).hexdigest())
        self.data['offers'] = offers
        output = self.render()
        rows = Document((output / 'compare/index.html').read_text()).root.select('tbody tr')
        self.assertEqual(len(rows), 4)
        expected = [('2 vCores', '4 GB RAM', '40 GB SSD NVMe'), ('4 vCores', '8 GB RAM', '75 GB SSD NVMe'),
                    ('6 vCores', '12 GB RAM', '100 GB SSD NVMe'), ('8 vCore', '24 GB RAM', '200 GB SSD NVMe')]
        for row, offer, values in zip(rows, offers, expected):
            cells = row.select('td')
            self.assertEqual([cell.text() for cell in cells[1:4]], list(values))
            detail = (output / 'deals' / offer['id'] / 'index.html').read_text()
            for value in values:
                self.assertIn(value, detail)
            self.assertIn('class="spec-list"', (output / 'providers/ovhcloud/index.html').read_text())
        self.assertEqual(hardware_specs({'details': 'Contact us for hardware details'}), {})

    def test_conflicting_duplicate_hardware_is_rejected(self):
        provider = copy.deepcopy(self.provider)
        provider['rules']['deduplicate_identical'] = True
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            parse_offers(CARD + CARD.replace('20 GB SSD', '40 GB SSD'), provider, self.when, provider['source_url'], 'fixture-sha')


if __name__ == '__main__':
    unittest.main()
