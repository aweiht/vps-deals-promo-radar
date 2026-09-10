# ::ILANG
# [TYPE:code][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:验证生成页面 路由 数据与结构化标记的一致性}
# ::BOUNDARY{never:用本地结构检查冒充 Google 富媒体资格或公开上线验收}
"""Check the rendered artifact, its metadata, internal links, and source lineage."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from xml.etree import ElementTree

from config import ROOT, read_config
from scraper import Document


def verify(output: Path, config: dict) -> dict:
    origin = config["site"]["domain"]
    pages = json.loads((output / ".generated.json").read_text())
    data = json.loads((output / "data/offers.json").read_text())
    offers = {o["id"]: o for o in data["offers"]}
    titles = set()
    for filename in pages:
        html = (output / filename).read_text()
        doc = Document(html).root
        title = doc.select("title")
        assert len(title) == 1 and title[0].text().strip(), filename + " missing title"
        assert title[0].text() not in titles, filename + " duplicate title"
        titles.add(title[0].text())
        canonical = doc.select('link[rel="canonical"]')
        expected = origin + "/" + filename.removesuffix("index.html")
        assert len(canonical) == 1 and canonical[0].attrs["href"] == expected, filename + " invalid canonical"
        assert len(doc.select("h1")) == 1, filename + " must have one h1"
        assert doc.select('meta[name="description"]'), filename + " missing description"
        graph = json.loads(doc.select('script[type="application/ld+json"]')[0].text(False))["@graph"]
        if filename.startswith("deals/"):
            offer = offers[filename.split("/")[1]]
            products = [item for item in graph if item["@type"] == "Product"]
            if offer["display_status"] != "observed" or "price" not in offer:
                assert not products, filename + " must not advertise stale/unpriced Product"
            else:
                assert len(products) == 1, filename + " missing Product"
                aggregate = products[0]["offers"]
                assert aggregate["@type"] == "AggregateOffer" and aggregate["offerCount"] == 1
                assert aggregate["lowPrice"] == aggregate["highPrice"] == offer["price"]
                assert len(aggregate["offers"]) == 1
                embedded = aggregate["offers"][0]
                assert embedded["price"] == offer["price"] and embedded["priceCurrency"] == offer["currency"]
                assert embedded["url"] == offer["offer_url"]
                assert embedded.get("priceValidUntil") == offer.get("valid_until")
                assert "availability" not in embedded, "Availability was not extracted"
        for node in doc.select("a, img, link"):
            value = node.attrs.get("href") or node.attrs.get("src")
            if not value or value.startswith("#"):
                continue
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc:
                assert parsed.scheme == "https", filename + " insecure/invalid URL"
                continue
            target = output / unquote(parsed.path).lstrip("/")
            if parsed.path.endswith("/"):
                target /= "index.html"
            assert target.is_file(), filename + " broken internal link: " + value
    sitemap = ElementTree.parse(output / "sitemap.xml")
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    entries = sitemap.findall("s:url", namespace)
    for entry in entries:
        assert entry.find("s:loc", namespace).text.startswith(origin + "/")
        assert entry.find("s:lastmod", namespace).text
    assert f"Sitemap: {origin}/sitemap.xml" in (output / "robots.txt").read_text()
    return {"valid_pages": len(pages), "sitemap_urls": len(entries), "offers": len(offers), "checks": "metadata, canonical, source lineage, JSON-LD, local links"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    parser.add_argument("--config", type=Path, default=ROOT / ".ilang/site.ilang")
    args = parser.parse_args()
    print(json.dumps(verify(args.output, read_config(args.config))))
