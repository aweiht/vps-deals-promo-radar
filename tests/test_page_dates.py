# ::ILANG
# [TYPE:test][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:验证内容更新日期与抓取日期分离和历史状态校验}
# ::BOUNDARY{never:改写真实页面状态 以样例代替公开上线验收}
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest

from page_dates import content_record


NOW = datetime(2026, 11, 7, 8, 30, tzinfo=timezone.utc)
HTML = ('<!doctype html><title>VPS index</title>\n<h1>A plan</h1>'
        '<p>$6.49 per month</p><p>Prepaid for 24 months.</p>'
        '<a href="https://example.com/plan">View plan</a>'
        '<time data-observation="2026-11-07T08:00:00Z">Nov 7 · 08:00 UTC</time>'
        '<span data-observation-month>November 2026</span>')


class PageDateTests(unittest.TestCase):
    def test_observation_only_check_keeps_lastmod(self):
        initial = content_record(HTML, None, NOW)
        rechecked = HTML.replace("08:00", "14:00")
        self.assertEqual(content_record(rechecked, initial, NOW + timedelta(hours=6)), initial)

    def test_observation_month_is_ignored_but_unmarked_dates_are_significant(self):
        initial = content_record(HTML, None, NOW)
        later = NOW + timedelta(days=30)
        self.assertEqual(content_record(HTML.replace("November 2026", "December 2026"), initial, later), initial)
        initial = content_record(HTML + "<p>Available until November 30</p>", None, NOW)
        changed = content_record(HTML + "<p>Available until December 30</p>", initial, later)
        self.assertNotEqual(changed["sha256"], initial["sha256"])
        self.assertNotEqual(changed["lastmod"], initial["lastmod"])

    def test_price_terms_link_status_and_template_changes_advance_lastmod(self):
        initial = content_record(HTML, None, NOW)
        for old, new in [("$6.49", "$7.49"), ("24 months", "12 months"),
                         ("/plan", "/new-plan"), ("View plan", "Expired"),
                         ("<h1>", '<h1 class="updated">')]:
            with self.subTest(change=new):
                changed = content_record(HTML.replace(old, new), initial, NOW + timedelta(hours=6))
                self.assertNotEqual(changed["sha256"], initial["sha256"])
                self.assertEqual(changed["lastmod"], "2026-11-07T14:30:00Z")

    def test_restored_route_can_reuse_its_retained_record(self):
        retained_record = content_record(HTML, None, NOW)
        self.assertEqual(content_record(HTML, retained_record, NOW + timedelta(days=3)), retained_record)

    def test_unmarked_markup_is_preserved_byte_for_byte(self):
        html = '<DIV class="a  b">\nPrice &amp; terms</DIV><!-- <time data-observation>text</time> -->'
        record = content_record(html, None, NOW)
        self.assertEqual(record["sha256"], sha256(html.encode()).hexdigest())
        changed = content_record(html.replace('class="a  b"', "class='a  b'"), record, NOW + timedelta(hours=1))
        self.assertNotEqual(changed["sha256"], record["sha256"])

    def test_nested_observation_markup_and_self_closing_element(self):
        expected = sha256(b"before\nafter").hexdigest()
        variants = [
            'before\n<time data-observation="a>b"><span>date</span></time>after',
            'before\n<span data-observation-month><span>date</span></span>after',
            'before\n<time data-observation="value"/>after',
        ]
        for html in variants:
            with self.subTest(html=html):
                self.assertEqual(content_record(html, None, NOW)["sha256"], expected)

    def test_invalid_and_future_records_rebuild_baseline(self):
        initial = content_record(HTML, None, NOW - timedelta(days=1))
        invalid = [None, {}, "invalid", {**initial, "sha256": "fake"},
                   {**initial, "lastmod": "not-a-date"}, {**initial, "lastmod": "2026-11-06T08:30:00"},
                   {**initial, "lastmod": "2026-11-08T00:00:00Z"}, {**initial, "lastmod": None}]
        for previous in invalid:
            with self.subTest(previous=previous):
                self.assertEqual(content_record(HTML, previous, NOW), content_record(HTML, None, NOW))

    def test_non_utc_history_is_validated_as_an_instant(self):
        previous = content_record(HTML, None, NOW)
        previous["lastmod"] = "2026-11-07T16:30:00+08:00"
        self.assertEqual(content_record(HTML, previous, NOW + timedelta(hours=1)), previous)
        self.assertEqual(content_record(HTML, None, NOW.astimezone(timezone(timedelta(hours=8))))["lastmod"],
                         "2026-11-07T08:30:00Z")

    def test_naive_current_time_and_unclosed_observation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            content_record(HTML, None, NOW.replace(tzinfo=None))
        with self.assertRaisesRegex(ValueError, "closing tag"):
            content_record('<time data-observation="value">not closed', None, NOW)


if __name__ == "__main__":
    unittest.main()
