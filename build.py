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


def price_text(offer: dict) -> str:
    if "price" not in offer:
        return "See source"
    decimals = max(2, len(str(offer["price"]).partition(".")[2]))
    return "$" + format(Decimal(str(offer["price"])), f",.{decimals}f")


def billing_text(offer: dict) -> str:
    return offer.get("billing_period") or "Billing period not extracted — check source"


def offer_schema(offer: dict) -> dict:
    result = {"@type": "Offer", "url": offer["offer_url"]}
    if "price" in offer:
        result.update(price=offer["price"], priceCurrency=offer["currency"])
    if offer.get("valid_until"):
        result["priceValidUntil"] = offer["valid_until"]
    return result


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


def build(config: dict, data: dict, output: Path, now: datetime | None = None) -> dict:
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

    def render_page(path: str, title: str, description: str, content: str, schemas: list, lastmod: str, indexable: bool = True):
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
        pages[filename] = lastmod if indexable else ""

    def card(offer: dict) -> str:
        provider = provider_map[offer["provider_id"]]
        kind = e(offer.get("discount_text") or ("Official promotion" if offer["kind"] == "promotion" else "Standard price"))
        terms = offer.get("terms") or "Check the provider for renewal, location and tax details."
        return f'''<article class="offer-card"><div class="card-top"><div class="card-meta"><a class="provider-link" href="/providers/{e(provider['id'])}/">{e(provider['name'])}</a><span class="badge">{kind}</span></div><h3><a href="/deals/{offer['id']}/">{e(offer['title'])}</a></h3><div class="price">{e(price_text(offer))}<span class="currency">{'USD' if 'price' in offer else ''}</span></div><p class="billing">{e(billing_text(offer))}</p><p class="card-terms">{e(terms[:220])}</p></div><div class="card-bottom"><span class="meta">{e(timestamp(offer['fetched_at']).strftime('%b %d · %H:%M UTC'))}</span><a href="/deals/{offer['id']}/">Offer details ↗</a></div></article>'''

    empty = '<div class="empty"><h2>No current offers to show</h2><p>The official sources need a fresh check. Use the provider links below to verify pricing directly.</p></div>'
    failed = [p for p in data.get("providers", []) if p["id"] in provider_map and p.get("status") != "ok"]
    not_current = len(offers) - len(current)
    notice = f'<div class="notice">{not_current} previously observed offer(s) need rechecking or have expired. They are excluded from this list.</div>' if not_current else ""
    if failed:
        notice += '<div class="notice">The latest check could not read ' + e(", ".join(provider_map[p["id"]]["name"] for p in failed)) + '. Check their official pages for current pricing.</div>'
    tiles = "".join(f'<a class="provider-tile" href="/providers/{e(p["id"])}/"><span><strong>{e(p["name"])}</strong><span class="meta">{sum(o["provider_id"] == p["id"] for o in current)} current listings</span></span><span aria-hidden="true">↗</span></a>' for p in config["providers"])
    content = templates["index"].substitute(headline=e(config["render"]["headline"]), intro=e(config["render"]["intro"]), offer_count=len(current), provider_count=len(provider_map), checked_at=e(display_time(data["checked_at"])), notice=notice, cards="".join(card(o) for o in current) or empty, providers=tiles)
    render_page("/", f"VPS offers & transparent billing — {month} | {site['brand']}", f"Compare {len(current)} official VPS offers from {len(provider_map)} providers. Source links, published billing terms, and last-checked dates for {month}.", content, [list_schema(current, origin)], data["checked_at"])

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
                service["offers"] = {"@type": "AggregateOffer", "priceCurrency": "USD", "offerCount": len(priced), "lowPrice": min(priced, key=lambda o: Decimal(o["price"]))["price"], "highPrice": max(priced, key=lambda o: Decimal(o["price"]))["price"], "offers": [offer_schema(o) for o in priced]}
            else:
                service["offers"] = [offer_schema(o) for o in priced]
        render_page(path, f"{provider['name']} VPS offers — {month} | {site['brand']}", summary + f" Checked in {month}.", content, [service, breadcrumb_schema(crumbs, origin)], max((o["fetched_at"] for o in provider_offers), default=data["checked_at"]))

    for offer in offers:
        provider = provider_map[offer["provider_id"]]
        status = observed_status(offer, config, now)
        path = f"/deals/{offer['id']}/"
        crumbs = [("Offers", "/"), (provider["name"], f"/providers/{provider['id']}/"), (offer["title"], path)]
        url = provider["affiliate_url"] or offer["offer_url"]
        rel = "sponsored noopener noreferrer" if provider["affiliate_url"] else "noopener noreferrer"
        facts = [("Provider", provider["name"]), ("Offer type", "Official promotion" if offer["kind"] == "promotion" else "Standard published price"), ("Billing", billing_text(offer)), ("Currency", offer.get("currency", "Not extracted")), ("Expiry", offer.get("valid_until", "Not stated in the extracted source")), ("Last checked", display_time(offer["fetched_at"]))]
        content = templates["deal"].substitute(breadcrumbs=breadcrumbs(crumbs), provider_name=e(provider["name"]), kind=e("OFFICIAL PROMOTION" if offer["kind"] == "promotion" else "STANDARD PRICE"), offer_title=e(offer["title"]), details=e(offer.get("details") or "Published on the provider's official website."), facts="".join(f"<div><dt>{e(key)}</dt><dd>{e(value)}</dd></div>" for key, value in facts), evidence=e(offer["evidence"]), source_url=e(offer["source_url"]), fetched_at=e(display_time(offer["fetched_at"])), price=e(price_text(offer)), billing=e(billing_text(offer)), status=status, status_label=STATUS_LABELS[status], cta=f'<a class="button" href="{e(url)}" rel="{rel}">View official offer ↗</a>' if status == "observed" else f'<p>This listing is {"expired" if status == "expired" else "not currently verified"}. <a href="{e(provider["source_url"])}">Check the provider directly.</a></p>', terms=e(offer.get("terms") or "No additional terms were extracted. Check the source before purchasing."))
        schemas = [breadcrumb_schema(crumbs, origin)]
        if status == "observed" and "price" in offer:
            schemas.append({"@type": "Product", "name": provider["name"] + " " + offer["title"], "description": offer.get("details") or offer["title"], "brand": {"@type": "Brand", "name": provider["name"]}, "url": origin + path, "offers": offer_schema(offer)})
        discount = " · " + offer["discount_text"] if offer.get("discount_text") else ""
        render_page(path, f"{provider['name']} {offer['title']} — {price_text(offer)}{discount} | {month}", f"{provider['name']} {offer['title']}: {price_text(offer)}{discount}. {billing_text(offer)}. Official source, terms and verification date.", content, schemas, offer["fetched_at"], indexable=status == "observed")

    compare_items = [("Offers", "/"), ("Compare", "/compare/")]
    rows = "".join(f'<tr><td><a class="provider-link" href="/providers/{e(o["provider_id"])}/">{e(provider_map[o["provider_id"]]["name"])}</a><a href="/deals/{o["id"]}/">{e(o["title"])}</a></td><td class="price-cell">{e(price_text(o))}</td><td>{e(billing_text(o))}<p class="fine-print">{e(o.get("terms", ""))}</p></td><td>{e(display_time(o["fetched_at"]))}</td><td><span class="status observed">Source checked</span></td></tr>' for o in current)
    content = templates["compare"].substitute(breadcrumbs=breadcrumbs(compare_items), rows=rows or '<tr><td colspan="5">No current offers. Check the provider pages directly.</td></tr>')
    render_page("/compare/", f"Compare VPS prices & billing — {month} | {site['brand']}", "Compare official VPS offers with their original billing period, verification date and source. No estimated discounts or invented coupon codes.", content, [list_schema(current, origin), breadcrumb_schema(compare_items, origin)], data["checked_at"])

    source_links = "".join(f'<li><a href="{e(p["source_url"])}">{e(p["name"])} official source</a></li>' for p in config["providers"])
    about = f'''<article class="prose"><p class="eyebrow">SOURCES &amp; DISCLOSURE</p><h1>Know what the price means.</h1><p>We list offers and published prices from official VPS providers. Each listing keeps its source, original billing period and last-checked timestamp so you can verify the terms yourself.</p><h2>How we check</h2><p>We request the listed public pages about every six hours, following their robots.txt rules. We do not bypass challenges or sign in to collect offers. Automated schedules can be delayed or stopped.</p><p>A successful check means the price appeared on that source page. It is not a purchase test, stock guarantee, performance review or endorsement. Unless explicitly shown, renewal price, tax and eligibility were not extracted. Prices are shown in USD; we do not convert currencies.</p><p>When a source fails or an observation is more than {config['runtime']['stale_after_hours']} hours old at build time, the listing is excluded from the current offers. Known expiry dates are checked at each build. Always check the displayed observation date if the site has stopped updating.</p><h2>Official sources</h2><ul>{source_links}</ul><h2>Affiliate disclosure</h2><p>{e(disclosure)}</p><h2>Privacy</h2><p>This site does not add analytics or set its own cookies. Following a provider link takes you to a separate website with its own privacy policy and terms.</p><h2>Reuse and corrections</h2><p><a href="/data/offers.json">Download the current dataset</a> or <a href="{e(config['render']['repository'])}">inspect the public repository</a> to check the evidence or report an incorrect listing.</p></article>'''
    render_page("/about/", f"Sources, checks & affiliate disclosure | {site['brand']}", "How we collect official VPS prices, handle failed checks and expired offers, and disclose affiliate links.", about, [], data["checked_at"])

    public_data = {**data, "providers": [p for p in data.get("providers", []) if p["id"] in provider_map], "offers": [{**o, "display_status": observed_status(o, config, now)} for o in offers]}
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
    (output / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  X-Frame-Options: DENY\n  Content-Security-Policy: default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'\n  Cache-Control: public, max-age=0, must-revalidate\n/data/*\n  X-Robots-Tag: noindex\n/.generated.json\n  X-Robots-Tag: noindex\n", encoding="utf-8")
    return {"pages": len(pages), "current_offers": len(current), "providers": len(provider_map), "domain": origin}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / ".ilang/site.ilang")
    parser.add_argument("--data", type=Path, default=ROOT / "data/offers.json")
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    result = build(read_config(args.config), json.loads(args.data.read_text()), args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
