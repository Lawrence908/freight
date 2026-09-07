# freight.chrislawrence.ca — build plan

One narrow question: **is freight moving, and what did it mean when it stopped?**
Freight is the economy you can weigh: tonnes on trucks and rails, the direct
demand-side twin of the diesel crack. Its signature quirk is the site's story: freight
contracts roughly twice as often as the economy does, so the scored table's "false
positives" are real goods recessions (2015-16, 2022-24) that the service economy
shrugged off. That reframing is the honest content, not a bug to tune away.

Site eight of the family, sixth econ-core consumer. Written 2026-09-07; every series
probed live from daedalus that day through econcore's fetchers.

## Verified sources

### United States (FRED, keyless, all probed)

| Series | What | Depth | Freq | Latest |
|---|---|---|---|---|
| `TSIFRGHT` | BTS Freight Transportation Services Index | 2000-01 → 2026-06 | monthly | 134.9 |
| `TRUCKD11` | BTS truck tonnage index | 2000-01 → | monthly | 113.3 |
| `RAILFRTCARLOADSD11` | Rail freight carloads | 2000-01 → | monthly | 991k |
| `RAILFRTINTERMODALD11` | Rail intermodal units | 2000-01 → | monthly | 1,240k |
| `TRFVOLUSM227NFWA` | Vehicle miles traveled, all vehicles | **1970-01 →** | monthly | 298B |
| `HTRUCKSSAAR` | Heavy truck sales, SAAR | **1967-01 →** | monthly | 426k |
| `FRGSHPUSM649NCIS` | Cass Freight shipments | **2016-01 → only** | monthly | 0.983 |
| `FRGEXPUSM649NCIS` | Cass Freight expenditures | 2016-01 → only | monthly | 3.518 |

### Canada (StatCan WDS, vector resolved and title-verified)

| Vector | What | Depth | Latest |
|---|---|---|---|
| `v74869` | Railway carloadings, total traffic carried, tonnes (table 23-10-0216-01) | 1999-01 → live | 30.9M t |

Findings from the probe:

1. **Cass is the family's second licensing window.** The famous 1990-era Cass Freight
   Index serves only 2016 onward on FRED (the ICE BofA pattern again). It ships as a
   recent-tape pair with the truncation stated; the scored table rides the BTS truck
   tonnage index instead, which nobody has truncated.
2. **AAR's weekly rail carloads have no keyless machine-readable feed** (press-release
   HTML only). Monthly BTS carloads and intermodal carry rail; the weekly gap is stated
   in the sources, not scraped around.
3. Canada's rail tonnage is live, monthly, title-verified, and unadjusted; year-over-year
   rendering handles the seasonality honestly, the family's standard move.
4. Launch posture, computed at build from tokens: truck tonnage sits at roughly its
   2018 level and heavy-truck sales are soft, the long shadow of the 2022-24 freight
   recession.

## Construction rules

- **Levels as published, YoY computed here** for tonnage, carloads, intermodal, VMT and
  Canadian tonnes, with the construction stated and levels shipped alongside. YoY is
  also what makes the differently-based indexes comparable on one chart.
- **No composite, no house freight index.** TSI is the only composite shown and BTS
  built it, not this page.
- No splicing Cass onto anything, and no pretending it is deep.

## The feature: the freight-recession table

Housing's engine, nearly verbatim (crest clock plus alarm clock), on `TRUCKD11`:

- The CREST: the tonnage peak (3-month average) in the two years before the alarm.
- The ALARM: 3-month-average tonnage below its year-earlier level for three consecutive
  months; episodes merging within six clear months; NBER peaks assigned to the nearest
  episode inside [alarm - 6 months, last signal + 18 months]; outcomes recession /
  coincident / none_in_window / pending. Threshold at 0% YoY, tuned once at the dry-run
  gate if the computed table misreads, then frozen and printed.
- Expected canonical reading (verify computed, then believe the table): 2000-01 into
  the 2001 recession; the famous 2006-07 freight rollover leading 2007-12; 2008-09;
  **2015-16 with no recession**; 2019 into 2020; **2022-24 with no recession**; possibly
  a 2025 row still open. Roughly six to eight rows.
- The era is short and the plan says so: 25 years, three scoreable recessions. The
  footnotes carry the reframe: rows marked "none within window" are the goods
  recessions (2015-16 industrial bust, 2022-24 destocking) that never became
  service-economy recessions, and the diesel crack collapsed through the same episodes,
  cross-linked to <a>diesel.chrislawrence.ca</a> as the price-side twin.

Heavy-truck sales (1967 →) get their own chart card as the capex canary: fleets stop
ordering before freight turns. Chart only, no scoring; its depth invites a scored table
someday, but one scored series per site is the family's shape. VMT (1970 →) is the
all-vehicle context card.

## Architecture

Clone lending wholesale. nginx front `freight` (host port **8134**, verified free) +
stdlib sidecar `freight-updater`. Vendor econ-core; jobs guardrails; housing's episode
engine with the YoY-threshold alarm; host cron daily 07:20 PT (BTS revises TSI and
tonnage routinely, so the revision card will be busy and says so; StatCan monthly on
its own calendar); monthly log truncation. `data/meta.json` near-empty; no curated
figure, no hand ritual. Vintages reserved.

## Page

1. Header, the question, chip: freight-recession signal or not, tonnage YoY, rail YoY.
2. Tiles: truck tonnage YoY, rail carloads YoY, TSI level, heavy trucks SAAR, and the
   computed "freight recessions vs NBER recessions" count.
3. Main chart: YoY lines for tonnage, carloads, intermodal, 2001 →, zero line, bands.
4. The freight-recession table with rule printed and computed footnotes (newest row
   from data; the goods-versus-services reframe; the diesel cross-link).
5. TSI level chart, 2000 →, bands (the composite BTS actually publishes).
6. The recent tape: Cass shipments and expenditures, 2016 →, truncation stated.
7. Heavy trucks, 1967 →, bands: the capex canary, with its 2022-24 slump visible.
8. VMT year-over-year, 1971 →, bands: everything on wheels, not just freight.
9. Canada: rail tonnage YoY, 2000 →, C.D. Howe bands, unadjusted-source note.
10. Revisions card (BTS revises monthly indexes routinely; says so), sources card with
    the Cass window, the AAR weekly gap, the vector and title, fetch policy, econ-core
    note, provenance line.

## Deploy checklist (identical to lending's, values changed)

Port 8134; `sites/freight.caddy`; services.yml entry with dashy + kuma blocks;
`cf-access.sh create freight.chrislawrence.ca --policy public` + retry; cron +
truncation; screenshots (mobile fullPage, desktop, table) + layout audit + console
check; `ls -l data/`; commit; push private `Lawrence908/freight`.

## Anti-goals

- No house composite index, no seasonal adjustment performed here, no scraping AAR
  press releases, no extending Cass backward from other sources.
- No spinning the false positives away: the goods-recession reframe is stated once and
  the rows stay scored "none within window" under the printed rule.
- No forecasts, no emdashes in page copy.

## Acceptance

- All series land with zero errors on a cold start, contract-validated, including the
  Canadian vector with its live title check.
- The table reproduces the canonical narrative (2006-07 led 2007-12; 2015-16 and
  2022-24 scored none; 2020 coincident or led) or the discrepancy is investigated until
  the table is believed; the rule is then frozen and printed.
- Kill `FRED_API_KEY`: everything still refreshes (keyless CSV and WDS are primary).
- Both containers healthy, public 200, Kuma green, screenshots committed, zero console
  errors, no horizontal scroll, repo pushed, no machine-owned files in git.
