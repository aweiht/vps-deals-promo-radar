# ::ILANG
# [TYPE:code][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:从 I-Lang 与真实数据生成静态站和结构化数据}
# ::BOUNDARY{never:编造价格日期库存 把过期或抓取失败记录冒充当前优惠 执行外部内容}
"""Build a complete static site; no dependencies or network access required."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import re
import shutil
import struct
from string import Template
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

from config import ROOT, https_url, read_config
from page_dates import content_record


def e(value) -> str:
    return escape(str(value), quote=True)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Observation timestamps require an explicit timezone")
    return result


def observed_status(offer: dict, config: dict, now: datetime) -> str:
    expiry = offer.get("valid_until")
    if expiry:
        if len(expiry) == 10:
            if date.fromisoformat(expiry) < now.date():
                return "expired"
        elif timestamp(expiry) <= now:
            return "expired"
    if offer.get("source_status") != "ok" or now - timestamp(offer["fetched_at"]) > timedelta(hours=config["runtime"]["stale_after_hours"]):
        return "stale"
    return "observed"


def display_time(value: str) -> str:
    return timestamp(value).astimezone(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")


def observation_time(value: str, short: bool = False) -> str:
    label = timestamp(value).astimezone(timezone.utc).strftime("%b %d · %H:%M UTC") if short else display_time(value)
    return f'<time data-observation="true" datetime="{e(value)}">{e(label)}</time>'


def detail_indexable(offer: dict, config: dict, now: datetime) -> bool:
    status = observed_status(offer, config, now)
    return status == "observed" or (status == "stale" and
        now - timestamp(offer["fetched_at"]) <= timedelta(days=config["runtime"]["historical_index_days"]))


def price_text(offer: dict) -> str:
    if "price" not in offer:
        return "See source"
    decimals = max(2, len(str(offer["price"]).partition(".")[2]))
    return "$" + format(Decimal(str(offer["price"])), f",.{decimals}f")


def billing_text(offer: dict) -> str:
    return offer.get("billing_period") or "Billing period not extracted — check source"


def billing_group(offer: dict) -> str:
    period = offer.get("billing_period", "").lower().strip()
    if period in {"/year", "/yr", "per year", "annually"}:
        return "annual"
    if period in {"/mo", "/month", "per month", "monthly"}:
        return "monthly"
    return "other"


def hardware_specs(offer: dict) -> dict:
    """Keep hardware amounts and CPU/storage units as published by the source."""
    details = offer.get("details", "")
    specs = {}
    for label, pattern in [("CPU", r"(?<![\d.])(\d+(?:\.\d+)?)\s+(vCPU|vCores?)\b"),
                           ("RAM", r"(\d+(?:\.\d+)?\s*[GM]B)\s+(RAM)\b"),
                           ("Storage", r"(\d+(?:\.\d+)?\s*[GT]B)\s+(SSD\s+NVMe|NVMe|SSD)\b")]:
        match = re.search(pattern, details, re.I)
        if match:
            specs[label] = (match[1], match[2])
    return specs


def plan_specs(offer: dict) -> str:
    specs = [f'<span><strong>{e(amount)}</strong><small>{e(unit if label == "CPU" else label)}</small></span>'
             for label, (amount, unit) in hardware_specs(offer).items()]
    return '<div class="spec-list">' + ''.join(specs) + '</div>' if specs else ''


def hardware_text(offer: dict, label: str) -> str:
    spec = hardware_specs(offer).get(label)
    return " ".join(spec) if spec else "Not extracted"


def offer_schema(offer: dict) -> dict:
    result = {"@type": "Offer", "url": offer["offer_url"]}
    if "price" in offer:
        result.update(price=offer["price"], priceCurrency=offer["currency"])
    if offer.get("valid_until"):
        result["priceValidUntil"] = offer["valid_until"]
    return result


def aggregate_schema(offers: list) -> dict:
    """This publisher aggregates observed offers; it is not the selling merchant.

    Even a single-source plan has exactly one observed offer, never a fabricated
    range or seller count. Individual source Offers remain nested and auditable.
    """
    return {"@type": "AggregateOffer", "priceCurrency": offers[0]["currency"],
            "offerCount": len(offers), "lowPrice": min(offers, key=lambda o: Decimal(o["price"]))["price"],
            "highPrice": max(offers, key=lambda o: Decimal(o["price"]))["price"],
            "offers": [offer_schema(offer) for offer in offers]}


def list_schema(offers: list, origin: str) -> dict:
    return {"@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "position": position, "name": offer["title"], "url": origin + f"/deals/{offer['id']}/"}
        for position, offer in enumerate(offers, 1)]}


def breadcrumb_schema(items: list, origin: str) -> dict:
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": index, "name": name, "item": origin + path}
        for index, (name, path) in enumerate(items, 1)]}


def breadcrumbs(items: list) -> str:
    entries = []
    for index, (name, path) in enumerate(items):
        entries.append(f'<li><a href="{e(path)}">{e(name)}</a></li>' if index < len(items)-1 else f'<li aria-current="page">{e(name)}</li>')
    return '<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>' + "".join(entries) + "</ol></nav>"


STATUS_LABELS = {"observed": "Source checked", "stale": "Needs rechecking", "expired": "Expired"}


def validate_data(data: dict, config: dict) -> list:
    if data.get("schema_version") != 1 or data.get("locale") != config["site"]["locale"]:
        raise ValueError("Dataset schema or locale does not match configuration")
    timestamp(data["checked_at"])
    providers = {p["id"]: p for p in config["providers"]}
    output = []
    seen = set()
    for offer in data.get("offers", []):
        if offer.get("provider_id") not in providers:
            continue  # Removing a provider from I-Lang removes its records from the site.
        if not re.fullmatch(r"[a-f0-9]{16}", offer.get("id", "")) or offer["id"] in seen:
            raise ValueError("Invalid or duplicate offer ID")
        seen.add(offer["id"])
        if not offer.get("title") or not offer.get("evidence") or not offer.get("source_sha256"):
            raise ValueError("Offer is missing source evidence")
        timestamp(offer["fetched_at"])
        https_url(offer["offer_url"])
        https_url(offer["source_url"])
        provider = providers[offer["provider_id"]]
        hosts = {urlsplit(provider[k]).hostname for k in ("website", "source_url")} | set(provider["rules"].get("allowed_hosts", []))
        if urlsplit(offer["source_url"]).hostname not in hosts:
            continue  # A source-host change must be fetched before its old data can appear.
        if urlsplit(offer["offer_url"]).hostname not in hosts | set(provider["rules"].get("offer_hosts", [])):
            raise ValueError("Unapproved outbound offer host")
        if "price" in offer:
            if not re.fullmatch(r"[0-9]+\.[0-9]{2,4}", str(offer["price"])) or offer.get("currency") != "USD" or not offer.get("price_evidence"):
                raise ValueError("Price requires an exact USD amount and source evidence")
        if offer.get("kind") not in {"promotion", "standard_price"}:
            raise ValueError("Unknown offer kind")
        output.append(offer)
    return output


def build(config: dict, data: dict, output: Path, now: datetime | None = None, state_path: Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    offers = validate_data(data, config)
    site = config["site"]
    origin = site["domain"]
    provider_map = {p["id"]: p for p in config["providers"]}
    current = [o for o in offers if observed_status(o, config, now) == "observed"]
    current.sort(key=lambda o: (o["kind"] != "promotion", o["provider_id"], o["title"]))
    month = timestamp(data["checked_at"]).strftime("%B %Y")
    templates = {p.stem: Template(p.read_text(encoding="utf-8")) for p in (ROOT / "templates").glob("*.html")}
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    for path in (ROOT / "assets").iterdir():
        if path.is_file():
            shutil.copyfile(path, output / "assets" / path.name)
    affiliate = any(p["affiliate_url"] for p in config["providers"])
    disclosure = ("Some outbound links are affiliate links. We may earn a commission if you buy through them. Provider terms apply. Listing order is not based on commission."
                  if affiliate else "No affiliate links are configured. Outbound links go to the official provider. Published prices can change; confirm the final amount and renewal terms with the provider.")
    graph_site = {"@type": "WebSite", "@id": origin + "/#website", "url": origin + "/", "name": site["brand"], "inLanguage": site["locale"]}
    pages: dict[str, str] = {}
    manifest_path = output / ".generated.json"
    old_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    state_path = state_path or output / ".page-state.json"
    previous_state = json.loads(state_path.read_text()) if state_path.exists() else {}
    page_state = {}

    def render_page(path: str, title: str, description: str, content: str, schemas: list, indexable: bool = True):
        filename = "index.html" if path == "/" else path.strip("/") + "/index.html"
        target = output / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        jsonld = json.dumps({"@context": "https://schema.org", "@graph": [graph_site, *schemas]}, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        image_url = origin + "/assets/og.png"
        image_path = output / "assets/og.png"
        social = ""
        if image_path.exists():
            image_width, image_height = struct.unpack(">II", image_path.read_bytes()[16:24])
            social = f'<meta property="og:image" content="{e(image_url)}"><meta property="og:image:width" content="{image_width}"><meta property="og:image:height" content="{image_height}"><meta name="twitter:image" content="{e(image_url)}"><meta property="og:image:alt" content="{e(site["brand"])} — Official VPS offers">'
        html = templates["base"].substitute(locale=e(site["locale"]), title=e(title), description=e(description),
            canonical=e(origin + path), brand=e(site["brand"]), robots="index,follow" if indexable else "noindex,follow",
            jsonld=jsonld, content=content, social_image=social, repository=e(config["render"]["repository"]), disclosure=e(disclosure))
        target.write_text(html, encoding="utf-8")
        # Month labels describe the observation window, not a substantive edit.
        fingerprint_html = re.sub(r'<title>.*?</title>|<meta\s[^>]*>',
            lambda match: match[0].replace(month, "OBSERVATION_MONTH"), html, flags=re.S)
        page_state[path] = content_record(fingerprint_html, previous_state.get(path), now)
        pages[filename] = page_state[path]["lastmod"] if indexable else ""

    def card(offer: dict) -> str:
        provider = provider_map[offer["provider_id"]]
        kind = e(offer.get("discount_text") or ("Official promotion" if offer["kind"] == "promotion" else "Standard price"))
        terms = offer.get("terms") or "Check the provider for renewal, location and tax details."
        group = billing_group(offer)
        billing_note = {"annual": "Annual total · USD", "monthly": "Published monthly rate · USD", "other": "Published billing period · USD"}[group]
        if "price" not in offer:
            billing_note = "Price not extracted · check the official source"
        return f'''<article class="offer-card" data-provider="{e(provider['id'])}" data-billing="{group}" data-price="{e(offer.get('price', ''))}" data-kind="{e(offer['kind'])}" data-title="{e(offer['title'])}" data-search-text="{e(provider['name'] + ' ' + offer['title'] + ' ' + offer.get('details', ''))}" data-order="{current.index(offer)}"><div class="card-top"><div class="card-meta"><a class="provider-link provider-identity" href="/providers/{e(provider['id'])}/"><span class="provider-monogram" aria-hidden="true">{e(provider['name'][:1])}</span>{e(provider['name'])}</a><span class="badge">{kind}</span></div><h3><a href="/deals/{offer['id']}/">{e(offer['title'])}</a></h3><div class="price">{e(price_text(offer))}<span class="period">{e(billing_text(offer))}</span></div><p class="billing">{billing_note}</p>{plan_specs(offer)}<p class="card-terms">{e(terms)}</p></div><div class="card-bottom"><span class="meta">Checked {observation_time(offer['fetched_at'], short=True)}</span><a href="/deals/{offer['id']}/">View plan <span aria-hidden="true">↗</span></a></div></article>'''

    empty = '<div class="empty"><h2>No current offers to show</h2><p>The official sources need a fresh check. Use the provider links below to verify pricing directly.</p></div>'
    failed = [p for p in data.get("providers", []) if p["id"] in provider_map and p.get("status") != "ok"]
    not_current = len(offers) - len(current)
    notice = f'<div class="notice">{not_current} previously observed offer(s) need rechecking or have expired. They are excluded from this list.</div>' if not_current else ""
    if failed:
        notice += '<div class="notice">The latest check could not read ' + e(", ".join(provider_map[p["id"]]["name"] for p in failed)) + '. Check their official pages for current pricing.</div>'
    tiles = "".join(f'<a class="provider-tile" href="/providers/{e(p["id"])}/"><span><strong>{e(p["name"])}</strong><span class="meta">{sum(o["provider_id"] == p["id"] for o in current)} current listings</span></span><span aria-hidden="true">↗</span></a>' for p in config["providers"])
    provider_options = ''.join(f'<option value="{e(p["id"])}">{e(p["name"])}</option>' for p in config['providers'])
    content = templates["index"].substitute(headline=e(config["render"]["headline"]), headline_accent=e(config["render"].get("headline_accent", "")), intro=e(config["render"]["intro"]), offer_count=len(current), provider_count=len(provider_map), checked_at=observation_time(data["checked_at"]), notice=notice, cards="".join(card(o) for o in current) or empty, providers=tiles, provider_options=provider_options, server_art=(ROOT / 'templates/server.svg').read_text())
    render_page("/", f"VPS Deals & Hosting Prices — {month} | {site['brand']}", f"Compare {len(current)} official VPS offers from {len(provider_map)} providers. Source links, published billing terms, and last-checked dates for {month}.", content, [list_schema(current, origin)])

    for provider in config["providers"]:
        provider_offers = [o for o in current if o["provider_id"] == provider["id"]]
        path = f"/providers/{provider['id']}/"
        crumbs = [("Offers", "/"), (provider["name"], path)]
        summary = f"{len(provider_offers)} listed offers from the official {provider['name']} page. Prices retain their published billing terms."
        content = templates["provider"].substitute(breadcrumbs=breadcrumbs(crumbs), provider_name=e(provider["name"]), summary=e(summary), source_url=e(provider["source_url"]), notice="", cards="".join(card(o) for o in provider_offers) or empty)
        service = {"@type": "Service", "name": provider["name"] + " VPS hosting", "provider": {"@type": "Organization", "name": provider["name"], "url": provider["website"]}, "url": origin + path}
        priced = [o for o in provider_offers if "price" in o]
        if priced:
            if len({billing_text(o) for o in priced}) == 1 and all(o.get("billing_period") for o in priced):
                service["offers"] = aggregate_schema(priced)
            else:
                service["offers"] = [offer_schema(o) for o in priced]
        render_page(path, f"{provider['name']} VPS offers — {month} | {site['brand']}", summary + f" Checked in {month}.", content, [service, breadcrumb_schema(crumbs, origin)])

    for offer in offers:
        provider = provider_map[offer["provider_id"]]
        status = observed_status(offer, config, now)
        path = f"/deals/{offer['id']}/"
        crumbs = [("Offers", "/"), (provider["name"], f"/providers/{provider['id']}/"), (offer["title"], path)]
        url = provider["affiliate_url"] or offer["offer_url"]
        rel = "sponsored noopener noreferrer" if provider["affiliate_url"] else "noopener noreferrer"
        facts = [("Provider", provider["name"]), ("Offer type", "Official promotion" if offer["kind"] == "promotion" else "Standard published price"), ("Coverage", "1 official offer recorded for this configuration"), ("Billing", billing_text(offer)), ("Currency", offer.get("currency", "Not extracted")), ("Expiry", offer.get("valid_until", "Not stated in the extracted source")), *( (label, hardware_text(offer, label)) for label in ("CPU", "RAM", "Storage") )]
        content = templates["deal"].substitute(breadcrumbs=breadcrumbs(crumbs), provider_name=e(provider["name"]), kind=e("OFFICIAL PROMOTION" if offer["kind"] == "promotion" else "STANDARD PRICE"), offer_title=e(offer["title"]), details=e(offer.get("details") or "Published on the provider's official website."), facts="".join(f"<div><dt>{e(key)}</dt><dd>{e(value)}</dd></div>" for key, value in facts), evidence=e(offer["evidence"]), source_url=e(offer["source_url"]), fetched_at=observation_time(offer["fetched_at"]), price_caption="OBSERVED PRICE" if status == "observed" else "LAST RECORDED PRICE", price=e(price_text(offer)), billing=e(billing_text(offer)), status=status, status_label=STATUS_LABELS[status], cta=f'<a class="button" href="{e(url)}" rel="{rel}">View official offer ↗</a>' if status == "observed" else f'<p>This listing is {"expired" if status == "expired" else "not currently verified"}. <a href="{e(provider["source_url"])}">Check the provider directly.</a></p>', terms=e(offer.get("terms") or "No additional terms were extracted. Check the source before purchasing."))
        schemas = [breadcrumb_schema(crumbs, origin)]
        if status == "observed" and "price" in offer:
            schemas.append({"@type": "Product", "name": provider["name"] + " " + offer["title"], "description": offer.get("details") or offer["title"], "brand": {"@type": "Brand", "name": provider["name"]}, "url": origin + path, "offers": aggregate_schema([offer])})
        discount = " · " + offer["discount_text"] if offer.get("discount_text") else ""
        price_prefix = "From " if "price" in offer and "starting price" in offer.get("terms", "").lower() else ""
        title = f"{provider['name']} {offer['title']} — {price_prefix}{price_text(offer)} {offer.get('billing_period', '')}{discount} | {month}"
        description = f"{provider['name']} {offer['title']}: {price_prefix}{price_text(offer)}{discount}. {billing_text(offer)}. Official source, terms and verification date."
        if status != "observed":
            title = f"{provider['name']} {offer['title']} — {STATUS_LABELS[status]} | {site['brand']}"
            description = f"Historical record of {provider['name']} {offer['title']}. {STATUS_LABELS[status]}. Current price is unverified; check the official source."
        render_page(path, title, description, content, schemas, indexable=detail_indexable(offer, config, now))

    compare_items = [("Offers", "/"), ("Compare", "/compare/")]
    rows = "".join(f'<tr><td><a class="provider-link" href="/providers/{e(o["provider_id"])}/">{e(provider_map[o["provider_id"]]["name"])}</a><a href="/deals/{o["id"]}/">{e(o["title"])}</a></td><td>{e(hardware_text(o, "CPU"))}</td><td>{e(hardware_text(o, "RAM"))}</td><td>{e(hardware_text(o, "Storage"))}</td><td class="price-cell">{e(price_text(o))}</td><td>{e(billing_text(o))}<p class="fine-print">{e(o.get("terms", ""))}</p></td><td>{observation_time(o["fetched_at"])}</td><td><span class="status observed">Source checked</span></td></tr>' for o in current)
    content = templates["compare"].substitute(breadcrumbs=breadcrumbs(compare_items), rows=rows or '<tr><td colspan="8">No current offers. Check the provider pages directly.</td></tr>')
    render_page("/compare/", f"Compare VPS prices & billing — {month} | {site['brand']}", "Compare official VPS offers with their original billing period, verification date and source. No estimated discounts or invented coupon codes.", content, [list_schema(current, origin), breadcrumb_schema(compare_items, origin)])

    source_links = "".join(f'<li><a href="{e(p["source_url"])}">{e(p["name"])} official source</a></li>' for p in config["providers"])
    about = f'''<article class="prose"><p class="eyebrow">SOURCES &amp; DISCLOSURE</p><h1>Sources and<br><em>price checks.</em></h1><p>This site compares prices from official VPS providers. Each listing includes the published amount, billing period, source link and time of the last check.</p><h2>Where prices come from</h2><p>We read public pricing pages from the providers listed below. Each observation includes its official source, capture time and the exact price text. Checks are scheduled every six hours; schedules can run late or stop. The date on each listing tells you when we last read it.</p><ul>{source_links}</ul><h2>How to read a price</h2><p>All prices are published USD amounts. An annual price is a yearly total; a monthly rate may be the equivalent of a longer prepaid commitment. We retain available renewal text and provider conditions. Missing tax, eligibility, stock or expiry information stays unspecified. The provider confirms the final payment at checkout.</p><p>A source check records what was on a page. It does not measure server performance, test a purchase or reserve availability. Promotions and ordinary starting prices are labelled separately.</p><h2>Failed checks and expired offers</h2><p>At each build, failed-source listings, known expired offers and observations older than {config['runtime']['stale_after_hours']} hours leave the current index. Their detail pages keep the original observation date and show the changed status. Temporarily unverified details remain discoverable for up to {config['runtime']['historical_index_days']} days after the last successful check, with no current purchase offer. Expired listings are excluded from search indexing. If updates stop, check the observation date and follow the official source before relying on a price.</p><h2>Links &amp; commissions</h2><p>{e(disclosure)}</p><h2>Privacy</h2><p>Search and filtering run in your browser. Cloudflare hosts this site and processes web requests. Provider websites apply their own privacy policies and terms.</p><h2>Data and corrections</h2><p><a href="/data/offers.json">Download the recorded observations</a> to inspect the source evidence, or <a href="{e(config['render']['repository'])}">open the repository</a> to report a correction. Every listing is traceable to a public provider page.</p></article>'''
    render_page("/about/", f"Sources, checks & affiliate disclosure | {site['brand']}", "How we collect official VPS prices, handle failed checks and expired offers, and disclose affiliate links.", about, [])

    public_data = {**data, "providers": [p for p in data.get("providers", []) if p["id"] in provider_map], "offers": [{**o, "display_status": observed_status(o, config, now), "detail_indexable": detail_indexable(o, config, now)} for o in offers]}
    (output / "data").mkdir(exist_ok=True)
    (output / "data/offers.json").write_text(json.dumps(public_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    sitemap = Element("urlset", xmlns=namespace)
    for filename, lastmod in pages.items():
        if lastmod:
            path = "/" + filename.removesuffix("index.html")
            entry = SubElement(sitemap, "url")
            SubElement(entry, "loc").text = origin + path
            SubElement(entry, "lastmod").text = lastmod
    (output / "sitemap.xml").write_bytes(tostring(sitemap, encoding="utf-8", xml_declaration=True))
    (output / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n", encoding="utf-8")
    unavailable = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="robots" content="noindex,follow"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Listing unavailable</title><h1>This listing is no longer available.</h1><p><a href="/">Browse current offers</a></p></html>'
    (output / "404.html").write_text(unavailable, encoding="utf-8")
    # Do not delete files in the user's checkout; replace obsolete generated routes
    # with noindex tombstones. Cloudflare builds from a fresh checkout each time.
    for filename in set(old_manifest) - set(pages):
        if re.fullmatch(r"(?:providers/[a-z0-9-]+|deals/[a-f0-9]{16})/index\.html", filename):
            (output / filename).write_text(unavailable, encoding="utf-8")
    manifest_path.write_text(json.dumps(list(pages), indent=2) + "\n")
    (output / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  X-Frame-Options: DENY\n  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'\n  Cache-Control: public, max-age=0, must-revalidate\n/data/*\n  X-Robots-Tag: noindex\n/.generated.json\n  X-Robots-Tag: noindex\n", encoding="utf-8")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(page_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"pages": len(pages), "current_offers": len(current), "providers": len(provider_map), "domain": origin}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".ilang/site.ilang")
    parser.add_argument("--data", type=Path, default=ROOT / "data/offers.json")
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    parser.add_argument("--state", type=Path, default=ROOT / "data/page-state.json")
    args = parser.parse_args()
    result = build(read_config(args.config), json.loads(args.data.read_text()), args.output, state_path=args.state)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
