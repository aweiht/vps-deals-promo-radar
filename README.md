# vps-deals

Official VPS offers with source links, billing terms, and last-checked timestamps. Built for people comparing the actual cost of a server.

Repository: [aweiht/vps-deals-promo-radar](https://github.com/aweiht/vps-deals-promo-radar)

Live site: [vps-deals-promo-radar-69v.pages.dev](https://vps-deals-promo-radar-69v.pages.dev/) — published and verified on 2026-09-11 UTC.

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

## Current acceptance

| Layer | Evidence |
| --- | --- |
| Real local collection | RackNerd 5 promotions, Hostinger 4 promotions, OVHcloud 4 standard-price plans; all three robots checks and HTML requests succeeded on 2026-09-10 UTC |
| Local generated site | 19 pages; HTML, internal links, canonical URLs, sitemap and JSON-LD consistency checked |
| Deterministic failure tests | 15 passing tests, including missing price, wrong currency, stale/expired data, conflicting duplicates, unsafe links and HTML escaping |
| I-Lang is active | Test changes a provider in `site.ilang`, then verifies both collection and rendered routes use the new provider; removal also removes its current listings |
| Browser | Desktop home and 390px mobile home/detail/comparison checked in the real browser; 13 comparison rows, no document overflow; official Hostinger link opened and matched the observed price |
| GitHub automation | [Real end-to-end run passed](https://github.com/aweiht/vps-deals-promo-radar/actions/runs/34549546675): all 3 live sources, 15 tests, build, artifact checks and an automatic data commit |
| Google rich-results code test | [Two valid items](https://search.google.com/test/rich-results/result?id=wNh9W1npfRURztVQAwdwmA): Product snippet and BreadcrumbList; no critical errors, optional-field recommendations remain. This is a code test, not live URL/indexing validation. |
| Cloudflare publication | [Live site](https://vps-deals-promo-radar-69v.pages.dev/) verified: 19 HTML pages and 6 supporting resources returned HTTP 200; canonical, sitemap, JSON-LD and source lineage passed against the downloaded production output. Home, detail and comparison navigation also checked in the browser. |
| Automatic publication | Action-generated commit [`e5ae33f`](https://github.com/aweiht/vps-deals-promo-radar/commit/e5ae33ffd14c1c614580d32e916819f01ab4457f) automatically produced [successful Pages deployment `d8b0cece`](https://d8b0cece.vps-deals-promo-radar-69v.pages.dev/), with the exact same full SHA. Live data matched the local build from that commit byte for byte. |
| Commercial | No affiliate account approved or tracking link configured; no revenue claim |

The collection-to-publication integration is verified. The owner can now inspect the public site; affiliate enrollment and commercial results remain unverified. The scheduler is configured every six hours; the canary above was manually triggered, so it proves the update and deployment path rather than guaranteeing future scheduled execution.

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
