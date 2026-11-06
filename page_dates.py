# ::ILANG
# [TYPE:code][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:按页面实质内容指纹记录最后修改时间}
# ::BOUNDARY{never:将抓取时间变化冒充内容更新 信任无时区或未来的历史时间}
"""Track content changes without advancing dates for observation-only checks."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re


class _ObservationRanges(HTMLParser):
    """Locate explicit observation elements without rewriting the remaining HTML."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lines = [0]
        self.lines.extend(match.end() for match in re.finditer("\n", html))
        self.ranges: list[tuple[int, int]] = []
        self.active: tuple[str, int] | None = None
        self.depth = 0

    def source_index(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    @staticmethod
    def observation(tag: str, attrs: list) -> bool:
        names = {name for name, _ in attrs}
        return ((tag == "time" and "data-observation" in names)
                or (tag == "span" and "data-observation-month" in names))

    def handle_starttag(self, tag: str, attrs: list):
        if self.active:
            if tag == self.active[0]:
                self.depth += 1
        elif self.observation(tag, attrs):
            self.active = (tag, self.source_index())
            self.depth = 1

    def handle_endtag(self, tag: str):
        if self.active and tag == self.active[0]:
            self.depth -= 1
            if not self.depth:
                self.ranges.append((self.active[1], self.html.index(">", self.source_index()) + 1))
                self.active = None

    def handle_startendtag(self, tag: str, attrs: list):
        if not self.active and self.observation(tag, attrs):
            start = self.source_index()
            self.ranges.append((start, start + len(self.get_starttag_text())))


def _content_html(html: str) -> str:
    parser = _ObservationRanges(html)
    parser.feed(html)
    parser.close()
    if parser.active:
        raise ValueError("Observation element is missing its closing tag")
    parts = []
    start = 0
    for left, right in parser.ranges:
        parts.append(html[start:left])
        start = right
    parts.append(html[start:])
    return "".join(parts)


def content_record(html: str, previous: dict | None, now: datetime) -> dict[str, str]:
    """Return a SHA-256 and UTC lastmod, reusing a valid unchanged record.

    Only explicitly marked observation elements are omitted from the fingerprint.
    All other markup, prices, terms, links and status changes remain significant.
    Invalid or future previous records establish a new baseline at ``now``; they
    cannot provide a trustworthy earlier modification date. Persistence and any
    normalization of title/meta calendar labels belong to the caller.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Content recording requires a timezone-aware current time")
    now = now.astimezone(timezone.utc)
    digest = sha256(_content_html(html).encode("utf-8")).hexdigest()
    lastmod = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(previous, dict):
        old_hash, old_date = previous.get("sha256"), previous.get("lastmod")
        if (isinstance(old_hash, str) and re.fullmatch(r"[a-f0-9]{64}", old_hash)
                and isinstance(old_date, str)):
            try:
                observed = datetime.fromisoformat(old_date.replace("Z", "+00:00"))
            except ValueError:
                observed = None
            if (observed is not None and observed.tzinfo is not None
                    and observed.utcoffset() is not None and observed <= now
                    and old_hash == digest):
                lastmod = old_date
    return {"sha256": digest, "lastmod": lastmod}
