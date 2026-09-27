# vps-deals

Official VPS offers with source links, billing terms, and last-checked timestamps. Built for people comparing the actual cost of a server.

Repository: [aweiht/vps-deals-promo-radar](https://github.com/aweiht/vps-deals-promo-radar)

Live site: [vps-deals-promo-radar-69v.pages.dev](https://vps-deals-promo-radar-69v.pages.dev/) — production browser checked after the RackNerd repair on 2026-09-27 UTC.

Defaults: VPS hosting, `vps-deals`, `en-US`, USD. The provider list and extraction rules live in [.ilang/site.ilang](.ilang/site.ilang).

## Run

Python 3.11+; no pip install, paid inference, or manually supplied API keys.

```sh
python3 scraper.py
python3 build.py
python3 -m unittest discover -s tests
python3 verify.py
python3 -m http.server 8765 --directory site
```

## Deployment and automation

The public `aweiht/vps-deals-promo-radar` GitHub repository is connected to Cloudflare Pages project `vps-deals-promo-radar`, with automatic production deployments enabled. Build command: `python build.py`. Output: `site`. Production branch: `main`. Framework preset: none. No environment secrets are configured.

Cloudflare assigned the `-69v` hostname suffix. The actual HTTPS origin is recorded in `.ilang/site.ilang` and used for every canonical URL, social URL and sitemap entry. To reproduce the deployment, use **Cloudflare → Workers & Pages → Create → Pages → Import an existing Git repository** with the settings above.

The workflow runs at `00:17`, `06:17`, `12:17` and `18:17` UTC, plus relevant code pushes and manual **Run workflow** requests. It checks the sources, builds and validates the site, then commits real observations in `data/offers.json`. Cloudflare builds from that data on repository updates. `site/` is derived output and is not committed.

The workflow uses GitHub's temporary, repository-scoped `GITHUB_TOKEN` via checkout. There are **no manually supplied API keys**, LLM calls, pip dependencies or persistent servers in the update/build pipeline. GitHub authentication and the Cloudflare GitHub App connection are still required at setup time.

If a source fails, only that source's previous observations are retained, with their original timestamps and an explicit failure state. The site is rebuilt without those offers in its current list, the state is committed, and the Action reports failure. There are no blind retries or fabricated empty commits. An interrupted build retains the last published deployment.

## Current repair status — 2026-09-27 UTC

The pre-repair [GitHub Actions run](https://github.com/aweiht/vps-deals-promo-radar/actions/runs/36296728050) failed RackNerd collection because the official page replaced `.plans-section .plan-card` with `.sn-plans .sn-plan`; the promotion was still present. The I-Lang selectors now follow the current cards and extract their titles, USD annual prices, billing period and official checkout links. The push-triggered [repair run](https://github.com/aweiht/vps-deals-promo-radar/actions/runs/36313946530) succeeded for repair commit `9278891627f8e66427bb1dba7fb0731777c7d081`.

The robots-aware local collection at 2026-09-27 10:47 UTC succeeded for RackNerd (5 offers), Hostinger (4) and OVHcloud (4). RackNerd's observed annual prices are $21.99, $35.99, $59.99, $89.99 and $119.99; no expiry was present. All 16 local tests, the 19-page build and artifact verification passed. Source hashes and the selector observation are recorded in the generated data and ignored `evidence/repair-racknerd/` directory.

The successful Action generated bot data commit [`34dd36bf627d585b69be0b2103d9d0bcb339c31f`](https://github.com/aweiht/vps-deals-promo-radar/commit/34dd36bf627d585b69be0b2103d9d0bcb339c31f). The [Cloudflare Pages check](https://github.com/aweiht/vps-deals-promo-radar/runs/108605058864) succeeded on that exact commit. A production browser check on 2026-09-27 showed 13 current offers across 3 providers, including all five RackNerd plans; the page's latest source timestamp was 10:53 UTC. The 1 GB detail showed $21.99/year and the official PID 952 checkout link, with no expiry claim.

## Current acceptance

| Layer | Evidence |
| --- | --- |
| Real local collection | RackNerd 5 promotions, Hostinger 4 promotions, OVHcloud 4 standard-price plans; all three robots checks and HTML requests succeeded on 2026-09-27 10:47 UTC |
| Local generated site | 19 pages; HTML, internal links, canonical URLs, sitemap and JSON-LD consistency checked |
| Deterministic tests | 16 passing tests, including the current five-card RackNerd markup, missing price, wrong currency, stale/expired data, conflicting duplicates, unsafe links and HTML escaping |
| I-Lang is active | Test changes a provider in `site.ilang`, then verifies both collection and rendered routes use the new provider; removal also removes its current listings |
| Browser | Current production home and 1 GB RackNerd detail checked on 2026-09-27: 13 offers across 3 providers, 5 RackNerd plans, $21.99/year, official PID 952 link, no inferred expiry; latest source timestamp shown was 10:53 UTC. The desktop/mobile comparison checks below are historical. |
| GitHub automation | [Repair run passed](https://github.com/aweiht/vps-deals-promo-radar/actions/runs/36313946530): 16 tests, all 3 sources, build, artifact verification and automatic data commit. The preceding [pre-repair run](https://github.com/aweiht/vps-deals-promo-radar/actions/runs/36296728050) exposed the selector failure. |
| Google rich-results code test | Historical 2026-09-11 [code test](https://search.google.com/test/rich-results/result?id=wNh9W1npfRURztVQAwdwmA): two valid items, Product snippet and BreadcrumbList; no critical errors, optional-field recommendations remain. This is not live URL/indexing validation. |
| Cloudflare publication | Production browser verified after the repair on 2026-09-27; the latest page source timestamp was 10:53 UTC. Earlier verification of 19 HTML pages, 6 supporting resources, canonical URLs, sitemap, JSON-LD, source lineage and desktop/mobile navigation dates from 2026-09-11. |
| Automatic publication | The Action generated [`34dd36b`](https://github.com/aweiht/vps-deals-promo-radar/commit/34dd36bf627d585b69be0b2103d9d0bcb339c31f); its exact-commit [Cloudflare Pages check passed](https://github.com/aweiht/vps-deals-promo-radar/runs/108605058864). Earlier [deployment `d8b0cece`](https://d8b0cece.vps-deals-promo-radar-69v.pages.dev/) remains historical evidence. |
| Commercial | No affiliate account approved or tracking link configured; no revenue claim |

Collection-to-publication is verified after the RackNerd repair through the push-triggered Action, exact-commit Pages check, and production browser checks of the home and RackNerd detail page. Affiliate enrollment and commercial results remain unverified. The scheduler is configured every six hours; the prior canary was manually triggered, so it proves the update and deployment path rather than guaranteeing future scheduled execution.

## Sources and billing

| Provider | Official source | Treatment |
| --- | --- | --- |
| RackNerd | [VPS Specials](https://www.racknerd.com/specials/) | Annual promotion prices, official checkout links; no inferred expiry from a countdown |
| Hostinger | [English VPS page](https://www.hostinger.com/vps-hosting?lang=en) | Published monthly equivalents and extracted renewal text; initial prepaid total is not extracted; page-level official links because checkout links are generated in JavaScript |
| OVHcloud | [US VPS page](https://us.ovhcloud.com/vps/) | Standard starting prices, excluding tax, with official configuration links; not labeled as discounts |

Each record preserves the official URL, observation time, source response SHA-256, price evidence, billing period and source excerpt. Missing expiry dates and unknown availability are omitted. Failed sources, known expired offers, and observations older than 48 hours at build time are excluded from the current list. The last-checked date stays visible because a static page cannot guarantee its own scheduler keeps running.

Sources are fetched sequentially with a descriptive bot User-Agent, HTTPS host allowlists, `robots.txt`, a per-request timeout, response-size/request-count caps and a pause between same-host requests. Challenges and robots failures are not bypassed. Only the explicitly configured official pages are fetched; this v1 is not an unrestricted crawler.

## Change the I-Lang configuration

`.ilang/site.ilang` is the single source for the brand, locale, origin, providers, source URLs, affiliate destinations, extraction rules, freshness threshold and rendering text. Both Python entrypoints read it on every run. No provider list is copied into Python.

Provider rows use `name | website | source | affiliate`. The final column stays blank until the corresponding affiliate account and this promotional method are approved. `SOURCE:<provider-slug>` describes the actual HTML card or JSON-LD extraction, using JSON values after each property name. The reader deliberately implements this documented I-Lang configuration subset; it does not execute arbitrary protocol verbs or site text.

To add or rename a provider, update the row and its matching source module, check its robots/terms and actual selectors, then run the four validation commands above. Removing a row immediately removes its listings from the rendered site. A source returning no cards fails closed. Do not add invented prices to make a selector pass.

Only `en-US` / USD is accepted in v1. Another locale requires its own verified regional pages, language templates and mutual `hreflang`; changing a language label alone is rejected. The workflow schedule is checked against I-Lang in tests, so cadence changes require updating both the scheduler and that validation.

## Monetization, once approved

1. Apply using the real published site. [RackNerd affiliate terms](https://www.racknerd.com/affiliates-terms-of-service) restrict coupon/cashback promotion and may exclude special products. [Hostinger's affiliate agreement](https://www.hostinger.com/legal/affiliate-program-agreement) requires approval for coupon, discount and incentive promotion. Obtain approval for this offer-directory format before enabling tracking links.
2. Put the **approved** tracking URL in the provider row. The build automatically switches that provider's offer CTA, adds `rel="sponsored"`, and updates the visible affiliate disclosure. No cookie insertion, automatic redirects, brand bidding, self-referrals or fabricated commission rates.
3. OVHcloud's [US Partner Program](https://us.ovhcloud.com/partner-program/) is a business partner program; no consumer affiliate commission is assumed. It remains an ordinary source link.
4. Keep any actual affiliate statements and costs in the owner's private records. If the asset is later sold, transfer the repository, domain and permitted accounts with verifiable traffic/revenue history; revenue and resale value are not guaranteed.

X and Facebook are intentionally not connected or auto-posted in v1. The public repository, site brand and reusable social card are ready for manual use. `assets/og.png` was generated once with the built-in image tool using the site's brand and billing headline; it is a committed static asset, never regenerated by the pipeline.

## Free-tier and search expectations

- [GitHub standard hosted runners are free for public repositories](https://docs.github.com/en/billing/concepts/product-billing/github-actions). Larger runners and other billable products are not used. No workflow artifacts/cache are uploaded.
- [Cloudflare Pages Free](https://developers.cloudflare.com/pages/platform/limits/) currently allows 500 builds/month. This schedule is about 112–124 builds/month before extra code pushes. Free-tier policies can change.
- [GitHub schedules can be delayed or dropped](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), and public-repository schedules can be disabled after 60 days without activity. Check failed Actions and preserve an owner who can repair source changes. This is not a promise of permanent unattended operation.
- Domain registration age and commit frequency do not guarantee search ranking. A custom domain is useful for ownership, portability and brand continuity; it is not required to start, and no domain purchase is made by this project. [Google's domain-age explanation](https://developers.google.com/search/blog/2009/09/domainalter-und-ranking?hl=de).
- Structured data describes what is visible. It does not guarantee rich results or indexing. [Google's Product guidance](https://developers.google.com/search/docs/appearance/structured-data/product-snippet) applies to individual product pages; individual plan pages use the documented shopping-aggregator `Product` + `AggregateOffer` model with exactly one observed source Offer (equal low/high prices and offerCount 1); provider pages use `Service`, lists use `ItemList`, and no unsupported FAQ promise is made. No product image, reviews or stock status are fabricated.

When a custom domain is ready, add it in Pages, update the I-Lang `domain`, rebuild, and verify canonical/sitemap URLs. Configure and verify redirects from the old hostname as part of that migration; changing canonical text alone is not a redirect.

站点规则用 I-Lang 协议描述，见 `.ilang/site.ilang`；协议说明：[ilang.ai](https://ilang.ai)。
