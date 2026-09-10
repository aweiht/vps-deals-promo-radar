# ::ILANG
# [TYPE:code][PROJECT:vps-deals-promo-radar][LANG:zh]
# ::STATE{@SELF, role:读取并验证唯一 I-Lang 配置}
# ::BOUNDARY{never:执行配置中的代码 静默忽略未知指令 硬编码厂商清单}
"""Strict, deliberately small I-Lang configuration reader; data, never code."""
from __future__ import annotations

import json
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError("A non-empty ASCII identifier is required")
    return result


def https_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"Expected a public HTTPS URL: {value!r}")
    if parsed.port not in (None, 443) or parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local/private endpoints are not allowed")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if "." not in parsed.hostname or parsed.hostname.endswith((".local", ".localhost", ".internal")):
            raise ValueError("Expected a public hostname")
    else:
        if not address.is_global:
            raise ValueError("Private IP endpoints are not allowed")
    return value


def read_config(path: Path | str = ROOT / ".ilang/site.ilang") -> dict:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 2 or lines[0].strip() != "::ILANG" or "[TYPE:config]" not in lines[1]:
        raise ValueError("Expected ::ILANG followed by [TYPE:config]")
    modules: dict[str, list[str]] = {}
    site = None
    current = None
    for number, raw in enumerate(lines[2:], 3):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("::STATE{@SITE,") and line.endswith("}"):
            if site is not None:
                raise ValueError("Duplicate @SITE")
            body = line[len("::STATE{@SITE,"):-1].strip()
            body = re.sub(r'(^|,\s*)([a-z_]+)\s*:', r'\1"\2":', body)
            site = json.loads("{" + body + "}")
        elif line.startswith("::MODULE{") and line.endswith("}"):
            current = line[9:-1].split("|", 1)[0]
            if current in modules:
                raise ValueError(f"Duplicate module: {current}")
            modules[current] = []
        elif line.startswith(("::RULE{", "::BOUNDARY{")) and line.endswith("}"):
            current = None  # Human-readable constraints; implemented and tested in code.
        elif line.startswith("::") or current is None:
            raise ValueError(f"Unsupported I-Lang syntax at line {number}")
        else:
            modules[current].append(line)
    if not site or set(site) != {"brand", "niche", "domain", "locale", "currency"}:
        raise ValueError("@SITE must define brand, niche, domain, locale and currency")
    site["domain"] = https_url(site["domain"]).rstrip("/")
    if urlsplit(site["domain"]).path or urlsplit(site["domain"]).query:
        raise ValueError("Site domain must be an HTTPS origin")
    if site["locale"] != "en-US" or site["currency"] != "USD":
        raise ValueError("v1 supports en-US/USD only; add regional sources and templates before expanding")
    providers = []
    for line in modules.pop("PROVIDERS", []):
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4:
            raise ValueError("Provider rows require name | website | source | affiliate")
        name, website, source, affiliate = parts
        provider = {"id": slug(name), "name": name, "website": https_url(website),
                    "source_url": https_url(source), "affiliate_url": https_url(affiliate) if affiliate else ""}
        providers.append(provider)
    if not providers or len({p["id"] for p in providers}) != len(providers):
        raise ValueError("At least one unique provider is required")
    fields = " ".join(modules.pop("FIELDS", [])).split()
    required = {"title", "price", "currency", "offer_url", "valid_until", "source_url", "fetched_at"}
    if not required.issubset(fields):
        raise ValueError("FIELDS is missing a required extraction field")
    parsed_modules = {}
    for name, contents in modules.items():
        if name not in {"RUNTIME", "RENDER"} and not name.startswith("SOURCE:"):
            raise ValueError(f"Unknown module: {name}")
        values = {}
        for line in contents:
            key, separator, value = line.partition(":")
            if not separator or key in values:
                raise ValueError(f"Invalid or repeated property in {name}: {key}")
            values[key] = json.loads(value.strip())
        parsed_modules[name] = values
    runtime = parsed_modules.get("RUNTIME", {})
    if not 1 <= runtime.get("stale_after_hours", 0) <= 168:
        raise ValueError("stale_after_hours must be 1..168")
    if not 1 <= runtime.get("request_timeout_seconds", 0) <= 30:
        raise ValueError("request_timeout_seconds must be 1..30")
    if not 1 <= runtime.get("max_offers_per_provider", 0) <= 100:
        raise ValueError("max_offers_per_provider must be 1..100")
    if runtime.get("schedule") != "17 */6 * * *":
        raise ValueError("v1 scheduler must remain six-hourly; update and validate workflow for a cadence change")
    for provider in providers:
        rules = parsed_modules.get("SOURCE:" + provider["id"])
        if not rules:
            raise ValueError(f"Missing SOURCE:{provider['id']}")
        if rules.get("kind") not in {"promotion", "standard_price"}:
            raise ValueError("Source kind must be promotion or standard_price")
        if rules.get("mode") not in {"cards", "jsonld"}:
            raise ValueError("Source mode must be cards or jsonld")
        provider["rules"] = rules
    return {"site": site, "providers": providers, "fields": fields, "runtime": runtime,
            "render": parsed_modules.get("RENDER", {})}
