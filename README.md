# Is Freight Moving?

Freight is the economy you can weigh, and the physical twin of the diesel crack.
Live at [freight.chrislawrence.ca](https://freight.chrislawrence.ca).

No framework, no build step, no package manager. Plain HTML, CSS and vanilla JS on an
nginx front, with a stdlib-Python updater sidecar. Part of the economic tracker
collection (diesel, debt, jobs, yield, housing, credit, lending) on the shared
[`econ-core`](../econ-core/CONTRACT.md) series contract.

## Layout

```
src/index.html    markup, styling, the TimeChart canvas engine, every render function
data/series.json  machine-fetched, rewritten wholesale each run, never hand-edited
data/meta.json    curated; deliberately near-empty (no hand-entered figure exists here)
data/recessions.json  vendored from econ-core; never edited here
api/server.py     updater, the freight-recession engine, read-only status API
api/econcore.py   vendored, stamped copy of the shared fetchers
```

## The series

Fourteen series on the econ-core contract. The BTS quartet monthly since 2000: the
freight TSI composite, truck tonnage (the scored series), rail carloads and intermodal.
The deep flankers: heavy-truck sales since 1967 (the capex canary) and vehicle miles
since 1970. Canada: total railway traffic in tonnes since 1999, via title-verified
StatCan vector v74869, unadjusted and drawn year-over-year. Year-over-year variants are
computed here with levels shipped alongside.

Two upstream limits recorded so nobody rediscovers them: **Cass serves only a sliding
~10-year window on FRED** (2016 onward as probed, the ICE BofA licensing pattern again),
so it ships as the recent tape with the truncation stated; and **AAR's weekly carloads
have no keyless machine-readable feed**, so monthly BTS rail carries that story with the
weekly gap named.

## The freight-recession table

Housing's crest-and-alarm engine on truck tonnage: episodes of the 3-month average
below its year-earlier level for three straight months, merging across gaps under
twelve months because a freight depression can contain a dead-cat bounce (2008 proved
it; with a six-month merge the GFC split in two and its deepest half scored as a false
positive, which is why the gap was widened once at the dry-run gate and then frozen).

On current data: three episodes. The 2006 alarm led the Great Recession by 22 months
(freight's famous early call), the merged 2006-09 episode bottomed 13.4% under its
crest, 2020 was coincident, and the 2023-25 episode is the longest in the series with
its bottom in December 2025 and its window still open. The absences are content: the
2015-16 and 2019 freight busts lived in rail and rates and never sustained three months
in tonnage, and 2001 is left-censored because the series' first measurable year is that
recession.

## The updater

```bash
docker exec freight-updater python /app/server.py --once      # dry run
docker exec freight-updater python /app/server.py --refresh   # what cron runs
```

Host crontab, daily at 07:20 Pacific, log bounded monthly. Family guardrails: stale or
shrunken upstreams kept, failures carry forward with the error recorded, revisions
logged. BTS revises its indexes routinely as carrier data settle, so the revision card
is expected to be busy and says so. Fetch policy is econ-core's: keyless first (FRED
CSV, StatCan WDS), keyed FRED as fallback (`FRED_API_KEY` in `.env`, gitignored).

## Provenance

Assembled with Claude, made by Anthropic. Measured volumes and computed history with
the rule printed; no forecasts.
