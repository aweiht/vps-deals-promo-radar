# ::ILANG
# [TYPE:code][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:按 I-Lang 配置抓取官方公开报价并保存来源证据}
# ::BOUNDARY{never:绕过 robots 反爬或登录 推断缺失价格 日期或佣金}
"""Bounded, robots-aware HTTPS collection using only the Python standard library."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from config import ROOT, https_url, read_config

AGENT = "VPSDealsBot"
USER_AGENT = "VPSDealsBot/1.0 (+https://github.com/aweiht/vps-deals-promo-radar)"
MAX_BYTES = 4_000_000
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self, visible: bool = True) -> str:
        if visible and self.tag in {"script", "style", "noscript"}:
            return ""
        return " ".join(child.text(visible) if isinstance(child, Node) else child for child in self.children)

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def select(self, selector: str) -> list:
        if not selector or selector == ":scope":
            return [self]
        found = []
        for alternative in selector.split(","):
            current = [self]
            for part in alternative.strip().split():
                current = [candidate for node in current for candidate in node.descendants() if matches(candidate, part)]
            for node in current:
                if all(node is not previous for previous in found):
                    found.append(node)
        return found


def matches(node: Node, selector: str) -> bool:
    attribute = re.search(r'\[([\w-]+)(?:=[\"\x27]?([^\]\"\x27]+)[\"\x27]?)?\]', selector)
    if attribute:
        key, value = attribute.groups()
        if key not in node.attrs or (value is not None and node.attrs[key] != value):
            return False
        selector = selector[:attribute.start()] + selector[attribute.end():]
    tag = re.match(r"^[\w*-]+", selector)
    if tag and tag[0] not in {"*", node.tag}:
        return False
    ident = re.search(r"#([\w-]+)", selector)
    if ident and node.attrs.get("id") != ident[1]:
        return False
    return all(value in node.attrs.get("class", "").split() for value in re.findall(r"\.([\w-]+)", selector))


class Document(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(value: str) -> str:
    return " ".join(value.split())


def extract(node: Node, rule: dict | None) -> str | None:
    if not rule:
        return None
    selected = node.select(rule.get("selector", ":scope"))
    values = [item.attrs.get(rule["attr"], "") if "attr" in rule else clean(item.text()) for item in selected]
    for value in values:
        if "regex" in rule:
            match = re.search(rule["regex"], value, re.I)
            if match:
                return clean(match.group(1) if match.lastindex else match.group(0))
        elif value:
            return clean(value)
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicFetcher:
    def __init__(self, timeout: int):
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())
        self.robots: dict = {}
        self.last_request: dict = {}
        self.requests = 0

    def raw(self, url: str) -> tuple[int, dict, bytes]:
        https_url(url)
        host = urlsplit(url).hostname
        # Destinations come only from the owner's HTTPS host allowlist. Leave DNS
        # resolution to urllib/the configured proxy (some proxies use fake-IP DNS).
        # Literal private IPs and local hostnames are rejected by https_url.
        if self.requests >= 40:
            raise ValueError("Per-run request budget exhausted")
        remaining = 1.0 - (time.monotonic() - self.last_request.get(host, 0))
        if remaining > 0:
            time.sleep(remaining)
        self.last_request[host] = time.monotonic()
        self.requests += 1
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Response exceeds size budget")
                return response.status, dict(response.headers), body
        except HTTPError as error:
            return error.code, dict(error.headers), b""

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            status, headers, body = self.raw(robots_url)
            # Resolve robots redirects only within the same origin, with a hard cap.
            for _ in range(3):
                if status not in {301, 302, 303, 307, 308}:
                    break
                redirect = urljoin(robots_url, headers.get("Location", headers.get("location", "")))
                if urlsplit(redirect).netloc != parts.netloc:
                    raise ValueError("robots.txt redirected outside the source host")
                robots_url = redirect
                status, headers, body = self.raw(robots_url)
            parser = RobotFileParser(robots_url)
            if status == 404:
                parser.parse(["User-agent: *", "Allow: /"])
            elif status == 200 and not body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                parser.parse(body.decode("utf-8", "replace").splitlines())
            else:
                raise ValueError(f"robots.txt unavailable (HTTP {status}); source skipped")
            self.robots[origin] = parser
        parser = self.robots[origin]
        delay = parser.crawl_delay(AGENT) or parser.crawl_delay("*") or 1
        if delay > 30:
            raise ValueError("Requested crawl delay exceeds this bounded run")
        host = parts.hostname
        remaining = delay - (time.monotonic() - self.last_request.get(host, 0))
        if remaining > 0:
            time.sleep(remaining)
        return parser.can_fetch(AGENT, url)

    def fetch(self, url: str, allowed_hosts: set[str]) -> tuple[str, str, str]:
        for _ in range(5):
            if urlsplit(url).hostname not in allowed_hosts:
                raise ValueError("Source redirected outside configured official hosts")
            if not self.allowed(url):
                raise ValueError("robots.txt disallows this source")
            status, headers, body = self.raw(url)
            if status in {301, 302, 303, 307, 308}:
                url = urljoin(url, headers.get("Location", headers.get("location", "")))
                continue
            if status != 200:
                raise ValueError(f"Official source returned HTTP {status}")
            content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
            if not any(value in content_type for value in ("text/html", "application/xhtml+xml")):
                raise ValueError("Source is not an HTML page")
            html = body.decode("utf-8", "replace")
            if any(marker in html.lower() for marker in ("cf-chl-widget", "cf-chl-bypass", "verify you are human")):
                raise ValueError("Source requires a browser challenge; not bypassed")
            return html, url, hashlib.sha256(body).hexdigest()
        raise ValueError("Too many redirects")


def official_hosts(provider: dict) -> set[str]:
    return {urlsplit(provider[key]).hostname for key in ("website", "source_url")} | set(provider["rules"].get("allowed_hosts", []))


def offer_link(raw: str | None, source_url: str, provider: dict) -> str:
    target = urljoin(source_url, raw or source_url)
    https_url(target)
    hosts = official_hosts(provider) | set(provider["rules"].get("offer_hosts", []))
    if urlsplit(target).hostname not in hosts:
        raise ValueError("Offer link is not on a configured official host")
    parts = urlsplit(target)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def normalize_price(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.fullmatch(r"(?:US\s*\$|USD\s*|\$)?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)\s*(?:USD)?", raw, re.I)
    if not match:
        raise ValueError(f"Ambiguous price text: {raw[:60]}")
    try:
        value = Decimal(match[1].replace(",", ""))
        if value < 0:
            raise ValueError("Negative price")
        decimals = max(2, len(match[1].partition(".")[2]))
        return format(value, f".{decimals}f")
    except InvalidOperation as error:
        raise ValueError("Invalid price") from error


def parse_offers(html: str, provider: dict, fetched_at: str, source_url: str, digest: str) -> list[dict]:
    document = Document(html).root
    rules = provider["rules"]
    rows = []
    if rules["mode"] == "cards":
        for card in document.select(rules["container"]):
            title = extract(card, rules.get("title"))
            if not title:
                continue
            include = rules.get("include_pattern")
            if include and not re.search(include, clean(card.text()), re.I):
                continue
            if rules.get("currency_check") and not extract(card, rules["currency_check"]):
                raise ValueError("Source currency does not match the configured USD market")
            extracted_terms = extract(card, rules.get("terms"))
            rows.append({"title": title, "raw_price": extract(card, rules.get("price")),
                         "billing_period": extract(card, rules.get("billing")),
                         "raw_url": extract(card, rules.get("offer")),
                         "valid_until": extract(card, rules.get("valid_until")),
                         "discount_text": extract(card, rules.get("discount")),
                         "evidence": clean(card.text())[:1800],
                         "terms": " ".join(value for value in (extracted_terms, rules.get("terms_note", "")) if value),
                         "details": extract(card, rules.get("details")) or ""})
    else:
        def walk(value):
            if isinstance(value, list):
                for item in value:
                    yield from walk(item)
            elif isinstance(value, dict):
                if value.get("@type") in {"Product", "Service"}:
                    yield value
                for child in value.values():
                    yield from walk(child)
        for script in document.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.text(visible=False))
            except json.JSONDecodeError:
                continue
            for product in walk(payload):
                offers = product.get("offers", [])
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers:
                    if offer.get("@type") != "Offer" or offer.get("priceCurrency") != "USD":
                        continue
                    rows.append({"title": product.get("name", ""), "raw_price": str(offer["price"]) if "price" in offer else None,
                                 "raw_url": offer.get("url"), "valid_until": offer.get("priceValidUntil"),
                                 "billing_period": None, "evidence": json.dumps(product, ensure_ascii=False)[:1800],
                                 "details": "", "terms": rules.get("terms_note", "")})
    output = []
    for row in rows:
        if not row["title"]:
            continue
        url = offer_link(row.pop("raw_url"), source_url, provider)
        identity = f"{provider['id']}|{url}|{row['title']}"
        offer = {"id": hashlib.sha256(identity.encode()).hexdigest()[:16], "provider_id": provider["id"],
                 "title": row["title"], "kind": rules["kind"], "offer_url": url, "source_url": source_url,
                 "fetched_at": fetched_at, "source_sha256": digest, "source_status": "ok",
                 "evidence": row["evidence"], "terms": row["terms"], "details": row["details"]}
        price = normalize_price(row["raw_price"])
        if price is not None:
            offer.update(price=price, currency="USD", price_evidence=row["raw_price"])
        if row.get("billing_period"):
            offer["billing_period"] = row["billing_period"]
        if row.get("discount_text"):
            offer["discount_text"] = row["discount_text"]
        if row.get("valid_until"):
            # Only dates explicitly extracted from the source; no synthetic expiration.
            value = row["valid_until"]
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            offer["valid_until"] = value
        output.append(offer)
    unique = {}
    for item in output:
        if item["id"] in unique:
            previous = unique[item["id"]]
            fields = ("title", "price", "currency", "billing_period", "offer_url", "valid_until", "terms")
            if not rules.get("deduplicate_identical") or any(previous.get(key) != item.get(key) for key in fields):
                raise ValueError("Duplicate offers contain ambiguous or conflicting prices/terms")
        else:
            unique[item["id"]] = item
    output = list(unique.values())
    if not output:
        raise ValueError("No offers matched; source markup may have changed")
    return output


def collect(config: dict, previous: dict, fetcher: PublicFetcher | None = None) -> dict:
    fetcher = fetcher or PublicFetcher(config["runtime"]["request_timeout_seconds"])
    result = {"schema_version": 1, "checked_at": utcnow(), "locale": config["site"]["locale"], "providers": [], "offers": []}
    for provider in config["providers"]:
        status = {"id": provider["id"], "name": provider["name"], "source_url": provider["source_url"], "checked_at": utcnow()}
        try:
            html, final_url, digest = fetcher.fetch(provider["source_url"], official_hosts(provider))
            now = utcnow()
            offers = parse_offers(html, provider, now, final_url, digest)
            cap = config["runtime"]["max_offers_per_provider"]
            if len(offers) > cap:
                raise ValueError(f"Offer count exceeds configured limit of {cap}")
            status.update(status="ok", offer_count=len(offers), fetched_at=now, source_sha256=digest)
            result["offers"].extend(offers)
        except (ValueError, OSError, URLError, TimeoutError) as error:
            status.update(status="error", offer_count=0, error=str(error)[:240])
            # Preserve evidence only for this exact source, with a visible failure marker.
            for old in previous.get("offers", []):
                if old.get("provider_id") == provider["id"] and urlsplit(old.get("source_url", "")).hostname in official_hosts(provider):
                    result["offers"].append({**old, "source_status": "error"})
        result["providers"].append(status)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".ilang/site.ilang")
    parser.add_argument("--output", type=Path, default=ROOT / "data/offers.json")
    args = parser.parse_args()
    config = read_config(args.config)
    previous = json.loads(args.output.read_text()) if args.output.exists() else {}
    result = collect(config, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for provider in result["providers"]:
        print(f"{provider['id']}: {provider['status']} ({provider['offer_count']} offers)" + (f" — {provider['error']}" if provider.get("error") else ""))
    return 0 if all(provider["status"] == "ok" for provider in result["providers"]) else 1


if __name__ == "__main__":
    sys.exit(main())
