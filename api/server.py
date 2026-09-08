#!/usr/bin/env python3
"""freight.chrislawrence.ca data updater and read-only status API.

One narrow question: is freight moving, and what did it mean when it stopped?
Freight is the economy you can weigh, and it contracts roughly twice as often
as the economy does; the scored table's "false positives" are goods
recessions the service economy shrugged off, which is the site's story, not
a defect.

Everything live on the page comes from series.json, machine-owned and
rewritten wholesale each run. data/meta.json and the vendored recessions.json
are never touched by automation. No curated figure, no hand ritual.

Guardrails, inherited from jobs: stale or shrunken upstreams are kept rather
than written, a failed fetch carries the previous series forward and records
the error, and revisions to already-published observations land in
changelog.jsonl. BTS revises the TSI and tonnage indexes routinely, so this
revision log is expected to be busy; that is the data behaving normally.

Two upstream limits this file knows about so nobody rediscovers them:

  * the Cass Freight series serve only a sliding ~10-year window on FRED
    (2016 onward as probed 2026-09-07), the same licensing pattern as the
    ICE BofA spreads on the credit site; the window rolling forward coexists
    fine with the guardrails, and the notes say so;
  * AAR's weekly rail carloads have no keyless machine-readable feed, so
    monthly BTS carloads and intermodal carry rail here.

HTTP here is read-only. Runs happen via host cron calling
`docker exec freight-updater python /app/server.py --refresh`.
"""

import json
import os
import sys
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import econcore

FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")

SERIES_FILE = os.path.join(DATA_DIR, "series.json")
CHANGELOG = os.path.join(DATA_DIR, "changelog.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "updater-state.json")
RECESSIONS_FILE = os.path.join(DATA_DIR, "recessions.json")

CURATED = ["meta", "recessions"]
SHRINK_TOLERANCE = 0.9
CHANGELOG_IN_PAYLOAD = 100

# The freight-recession rule: housing's crest-and-alarm engine on truck
# tonnage. Ships in the payload so the page prints the rule that produced
# the table; frozen after the dry-run gate.
EPISODE_RULE = {
    "series": "us_truck_tonnage",
    "basis": "3-month average, percent change from a year earlier",
    "threshold_yoy_pct": 0.0,
    "sustain_months": 3,
    "merge_gap_months": 12,
    "window_before_months": 6,
    "window_after_months": 18,
    "crest_lookback_months": 24,
    "statement": ("A freight recession is a stretch of months with the "
                  "3-month average of truck tonnage below its level a year "
                  "earlier, at least three such months in a row; stretches "
                  "separated by fewer than twelve clear months merge into "
                  "one, because a freight depression can contain a dead-cat "
                  "bounce (2008 proved it). Each episode is dated two ways: "
                  "the CREST, where the 3-month average peaked in the two "
                  "years before the alarm, and the ALARM, the first month "
                  "below a year earlier. An NBER peak from six months before "
                  "the alarm to 18 months after the last signal month is "
                  "assigned to the nearest episode; lead time runs from the "
                  "crest."),
}

_payload_cache = {"stamp": None, "body": None}
_state = {"last_run": None, "results": []}
_lock = threading.Lock()


# --------------------------------------------------------------------------
# the series list
# --------------------------------------------------------------------------

def _fred(series_id):
    return lambda: econcore.fred_series(series_id, FRED_KEY)


def _wds(vector_id, expect_title):
    return lambda: econcore.wds_vector(vector_id, expect_title=expect_title)


CASS_NOTE = ("Cass licenses FRED to redistribute only a sliding window of "
             "roughly ten years (2016 onward as probed 2026-09-07), although "
             "the index reaches 1990. Shown as the recent tape; the scored "
             "table rides the BTS tonnage index, which nobody has truncated.")
RAIL_TABLE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2310021601"

FETCHED = [
    {
        "id": "us_tsi_freight",
        "fetch": _fred("TSIFRGHT"),
        "label": "US Freight Transportation Services Index",
        "source": "Bureau of Transportation Statistics, via FRED TSIFRGHT",
        "source_url": "https://fred.stlouisfed.org/series/TSIFRGHT",
        "units": "index_2000_100", "freq": "monthly",
        "note": "The composite BTS actually publishes: trucking, rail, inland waterways, pipeline and air freight in one seasonally adjusted index, monthly since 2000. Revised routinely as source data settle.",
    },
    {
        "id": "us_truck_tonnage",
        "fetch": _fred("TRUCKD11"),
        "label": "US truck tonnage index",
        "source": "Bureau of Transportation Statistics, via FRED TRUCKD11",
        "source_url": "https://fred.stlouisfed.org/series/TRUCKD11",
        "units": "index_2000_100", "freq": "monthly",
        "note": "Seasonally adjusted, monthly since 2000. Trucking moves the large majority of US freight tonnage, which is why the freight-recession table computes from this series.",
    },
    {
        "id": "us_rail_carloads",
        "fetch": _fred("RAILFRTCARLOADSD11"),
        "label": "US rail freight carloads",
        "source": "Bureau of Transportation Statistics, via FRED RAILFRTCARLOADSD11",
        "source_url": "https://fred.stlouisfed.org/series/RAILFRTCARLOADSD11",
        "units": "carloads", "freq": "monthly",
        "note": "Monthly since 2000, seasonally adjusted. AAR's weekly carload reports have no keyless machine-readable feed, so monthly BTS carries rail here; the weekly gap is stated, not scraped around.",
    },
    {
        "id": "us_rail_intermodal",
        "fetch": _fred("RAILFRTINTERMODALD11"),
        "label": "US rail intermodal units",
        "source": "Bureau of Transportation Statistics, via FRED RAILFRTINTERMODALD11",
        "source_url": "https://fred.stlouisfed.org/series/RAILFRTINTERMODALD11",
        "units": "units", "freq": "monthly",
        "note": "Containers and trailers on flatcars, monthly since 2000, seasonally adjusted. The consumer-goods half of rail.",
    },
    {
        "id": "us_vmt",
        "fetch": _fred("TRFVOLUSM227NFWA"),
        "label": "US vehicle miles traveled",
        "source": "Federal Highway Administration, via FRED TRFVOLUSM227NFWA",
        "source_url": "https://fred.stlouisfed.org/series/TRFVOLUSM227NFWA",
        "units": "millions_of_miles", "freq": "monthly",
        "note": "Everything on wheels, not just freight, monthly since 1970. Unadjusted; drawn as year-over-year, which removes the seasonality honestly.",
    },
    {
        "id": "us_heavy_truck_sales",
        "fetch": _fred("HTRUCKSSAAR"),
        "label": "US heavy truck sales",
        "source": "BEA motor vehicle retail sales, heavy weight trucks, via FRED HTRUCKSSAAR",
        "source_url": "https://fred.stlouisfed.org/series/HTRUCKSSAAR",
        "units": "millions_of_units_annualized", "freq": "monthly",
        "note": "SAAR, monthly since 1967: the capex canary. Fleets stop ordering trucks before freight turns, and the series has crashed into or through every recession of its era.",
    },
    {
        "id": "us_cass_shipments",
        "fetch": _fred("FRGSHPUSM649NCIS"),
        "label": "Cass Freight Index, shipments",
        "source": "Cass Information Systems, via FRED FRGSHPUSM649NCIS",
        "source_url": "https://fred.stlouisfed.org/series/FRGSHPUSM649NCIS",
        "units": "index", "freq": "monthly",
        "note": CASS_NOTE,
    },
    {
        "id": "us_cass_expenditures",
        "fetch": _fred("FRGEXPUSM649NCIS"),
        "label": "Cass Freight Index, expenditures",
        "source": "Cass Information Systems, via FRED FRGEXPUSM649NCIS",
        "source_url": "https://fred.stlouisfed.org/series/FRGEXPUSM649NCIS",
        "units": "index", "freq": "monthly",
        "note": "What shippers paid rather than how much moved; the gap between the two lines is freight rates. " + CASS_NOTE,
    },
    {
        "id": "ca_rail_tonnes",
        "fetch": _wds(74869, "Total traffic carried"),
        "label": "Canada railway traffic, tonnes",
        "source": "Statistics Canada railway carloadings, table 23-10-0216-01, vector v74869",
        "source_url": RAIL_TABLE,
        "units": "tonnes", "freq": "monthly",
        "note": "Total traffic carried, monthly since 1999, unadjusted; drawn as year-over-year, which removes the seasonality honestly. Canada's freight economy is disproportionately rail.",
    },
]


# --------------------------------------------------------------------------
# derived series
# --------------------------------------------------------------------------

def build_derived(series):
    """Year-over-year variants, computed here with the construction stated;
    levels ship in the same payload. YoY is also what makes differently-based
    indexes comparable on one chart."""
    out = {}
    for src_id, new_id, label in [
        ("us_truck_tonnage", "us_truck_tonnage_yoy", "US truck tonnage, year over year"),
        ("us_rail_carloads", "us_rail_carloads_yoy", "US rail carloads, year over year"),
        ("us_rail_intermodal", "us_rail_intermodal_yoy", "US rail intermodal, year over year"),
        ("us_vmt", "us_vmt_yoy", "US vehicle miles, year over year"),
        ("ca_rail_tonnes", "ca_rail_tonnes_yoy", "Canada rail tonnes, year over year"),
    ]:
        src = series.get(src_id)
        if not src:
            continue
        out[new_id] = econcore.make_series(
            new_id, label,
            "Derived: 12-month percent change of " + src["source"],
            src["source_url"], "percent", "monthly",
            [[d, round(v, 2)] for d, v in
             econcore.yoy_percent(src["obs"], 12)],
            confidence="estimate",
            note="Computed here from the level series in this payload.")
    return out


# --------------------------------------------------------------------------
# analysis: status and the freight-recession table
# --------------------------------------------------------------------------

def _mi(year_month):
    year, month = year_month.split("-")[:2]
    return int(year) * 12 + int(month) - 1


def _three_month_avg(obs):
    return [[obs[i][0], (obs[i][1] + obs[i - 1][1] + obs[i - 2][1]) / 3.0]
            for i in range(2, len(obs))]


def _yoy(avgs, periods=12):
    out = []
    for i in range(periods, len(avgs)):
        prev = avgs[i - periods][1]
        if prev:
            out.append([avgs[i][0], (avgs[i][1] / prev - 1.0) * 100.0])
    return out


# The chip's own rule: EPISODE_RULE's threshold without the sustain and merge
# conditions, which date completed episodes rather than describe today.
CHIP_RULE = ("The freight-contraction signal is on when the 3-month average "
             "of truck tonnage sits below its level a year earlier.")


def _signed(value, places=1):
    """The page's sign convention: U+2212 for negatives, never a hyphen."""
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return "%s%.*f%%" % (sign, places, abs(value))


def build_status(series):
    status = {}
    tonnage = series.get("us_truck_tonnage")
    if tonnage and len(tonnage["obs"]) > 15:
        avgs = _three_month_avg(tonnage["obs"])
        yoy = _yoy(avgs)
        status["us_truck_tonnage"] = {
            "latest": [tonnage["obs"][-1][0], tonnage["obs"][-1][1]],
            "yoy_3mma_pct": round(yoy[-1][1], 1) if yoy else None,
        }
        if yoy:
            status["signal_active"] = yoy[-1][1] < EPISODE_RULE["threshold_yoy_pct"]
    for sid in ("us_rail_carloads_yoy", "us_tsi_freight", "us_heavy_truck_sales"):
        entry = series.get(sid)
        if entry:
            status[sid] = {"latest": [entry["obs"][-1][0], entry["obs"][-1][1]]}

    ton = status.get("us_truck_tonnage")
    if ton and ton.get("yoy_3mma_pct") is not None:
        signal = bool(status.get("signal_active"))
        detail = "tonnage %s year over year (3-month average)" % _signed(
            ton["yoy_3mma_pct"])
        rail = status.get("us_rail_carloads_yoy")
        if rail:
            detail += " · rail carloads %s" % _signed(rail["latest"][1])
        status["headline"] = {
            "state": "signal" if signal else "normal",
            "label": "Freight contracting" if signal else "Freight moving",
            "detail": detail,
            "as_of": ton["latest"][0],
            "rule": CHIP_RULE,
        }
    return status


def build_episodes(tonnage_entry, recessions):
    """The freight-recession table: housing's two clocks on truck tonnage.
    The crest is the tonnage peak before the decline; the alarm is the first
    month below a year earlier. Nearest-episode peak assignment, as
    everywhere in the family."""
    avgs = _three_month_avg(tonnage_entry["obs"])
    level = {d[:7]: v for d, v in avgs}
    yoy = _yoy(avgs)
    months = [[d[:7], v] for d, v in yoy]
    threshold = EPISODE_RULE["threshold_yoy_pct"]
    qualifying = [i for i, (_, v) in enumerate(months) if v < threshold]
    if not qualifying:
        return {"rule": EPISODE_RULE, "episodes": [], "stats": {}}

    runs = [[qualifying[0], qualifying[0]]]
    for i in qualifying[1:]:
        if i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    groups = [runs[0][:]]
    for start_i, end_i in runs[1:]:
        gap = _mi(months[start_i][0]) - _mi(months[groups[-1][1]][0]) - 1
        if gap < EPISODE_RULE["merge_gap_months"]:
            groups[-1][1] = end_i
        else:
            groups.append([start_i, end_i])

    def longest_run(lo, hi):
        best = run = 0
        for i in range(lo, hi + 1):
            run = run + 1 if months[i][1] < threshold else 0
            best = max(best, run)
        return best

    groups = [g for g in groups
              if longest_run(g[0], g[1]) >= EPISODE_RULE["sustain_months"]]

    def month_at(mi_value):
        return "%04d-%02d" % (mi_value // 12, mi_value % 12 + 1)

    shells = []
    for lo, hi in groups:
        span = months[lo:hi + 1]
        start, end = span[0][0], span[-1][0]
        look = [month_at(m) for m in
                range(_mi(start) - EPISODE_RULE["crest_lookback_months"],
                      _mi(start) + 1)]
        crest = max((m for m in look if m in level), key=lambda m: level[m])
        after = [month_at(m) for m in range(_mi(start), _mi(end) + 7)]
        bottom = min((m for m in after if m in level), key=lambda m: level[m])
        shells.append({
            "start": start, "end": end, "span": span,
            "crest": crest, "bottom": bottom,
            "window_lo": _mi(start) - EPISODE_RULE["window_before_months"],
            "window_hi": _mi(end) + EPISODE_RULE["window_after_months"],
            "peaks": [],
        })

    bands = recessions["us"]["bands"]
    data_through = _mi(recessions["us"]["as_of"][:7])
    assigned = set()
    for band in bands:
        peak = band["peak"]
        candidates = [s for s in shells
                      if s["window_lo"] <= _mi(peak) <= s["window_hi"]]
        if not candidates:
            continue
        best = max(candidates, key=lambda s: _mi(s["start"]))
        best["peaks"].append(peak)
        assigned.add(peak)

    episodes = []
    for s in shells:
        led = [p for p in s["peaks"] if _mi(p) >= _mi(s["start"])]
        if led:
            outcome = "recession"
        elif s["peaks"]:
            outcome = "coincident"
        elif s["window_hi"] > data_through:
            outcome = "pending"
        else:
            outcome = "none_in_window"
        first_peak = s["peaks"][0] if s["peaks"] else None
        episodes.append({
            "start": s["start"],
            "end": s["end"],
            "crest": {"month": s["crest"],
                      "value": round(level[s["crest"]], 1)},
            "bottom": {"month": s["bottom"],
                       "value": round(level[s["bottom"]], 1)},
            "depth_pct": round((level[s["bottom"]] / level[s["crest"]] - 1.0)
                               * 100.0, 1),
            "months_signalling": len([1 for _, v in s["span"]
                                      if v < threshold]),
            "recessions": s["peaks"],
            "lead_from_crest_months": (_mi(first_peak) - _mi(s["crest"])
                                       if first_peak else None),
            "lead_from_alarm_months": (_mi(first_peak) - _mi(s["start"])
                                       if first_peak else None),
            "outcome": outcome,
        })

    leads = sorted(e["lead_from_crest_months"] for e in episodes
                   if e["recessions"])
    stats = {}
    if episodes:
        stats = {"episodes": len(episodes),
                 "credited_episodes": len(leads),
                 "alarm_led": len([e for e in episodes
                                   if e["outcome"] == "recession"]),
                 "coincident": len([e for e in episodes
                                    if e["outcome"] == "coincident"]),
                 "false_positives": len([e for e in episodes
                                         if e["outcome"] == "none_in_window"]),
                 "pending": len([e for e in episodes
                                 if e["outcome"] == "pending"]),
                 "uncredited_recessions": [
                     b["peak"] for b in bands
                     if _mi(b["peak"]) >= _mi(months[0][0])
                     and b["peak"] not in assigned]}
        if leads:
            mid = len(leads) // 2
            stats["median_lead_from_crest_months"] = (
                leads[mid] if len(leads) % 2
                else (leads[mid - 1] + leads[mid]) / 2.0)
    return {"rule": EPISODE_RULE, "episodes": episodes, "stats": stats}


def build_analysis(series):
    analysis = {"status": build_status(series)}
    tonnage = series.get("us_truck_tonnage")
    if tonnage:
        try:
            recessions = econcore.load_recessions(RECESSIONS_FILE)
            analysis["episodes"] = build_episodes(tonnage, recessions)
        except Exception as exc:  # noqa: BLE001 - the table degrades, the page renders
            analysis["episodes_error"] = "%s: %s" % (type(exc).__name__, exc)
    return analysis


# --------------------------------------------------------------------------
# refresh
# --------------------------------------------------------------------------

def load_old_series():
    try:
        with open(SERIES_FILE) as fh:
            return json.load(fh).get("series", {})
    except Exception:  # noqa: BLE001 - first run, or corrupt file: start clean
        return {}


def _diff_revisions(series_id, old_obs, new_obs):
    old_map = dict(map(tuple, old_obs))
    changed = [(d, old_map[d], v) for d, v in new_obs
               if d in old_map and abs(old_map[d] - v) > 1e-9]
    if not changed:
        return None
    deltas = [abs(after - before) for _, before, after in changed]
    return {
        "series": series_id, "action": "revised",
        "changed": len(changed),
        "span": [changed[0][0], changed[-1][0]],
        "max_delta": round(max(deltas), 4),
        "sample": [{"date": d, "before": b, "after": a}
                   for d, b, a in changed[:3]],
    }


def refresh_series(dry=False):
    old = load_old_series()
    series, errors, results = {}, {}, []

    for spec in FETCHED:
        sid = spec["id"]
        prev = old.get(sid)
        rec = {"series": sid, "action": "fetched"}
        try:
            obs = spec["fetch"]()
            doc = econcore.make_series(
                sid, spec["label"], spec["source"], spec["source_url"],
                spec["units"], spec["freq"], obs, note=spec.get("note"))
            if prev and prev.get("obs"):
                if doc["as_of"] < prev["as_of"]:
                    rec.update(action="stale-upstream",
                               reason="upstream at %s, behind stored %s; kept"
                                      % (doc["as_of"], prev["as_of"]))
                    doc = prev
                elif len(obs) < len(prev["obs"]) * SHRINK_TOLERANCE:
                    rec.update(action="shrunk",
                               reason="%d obs against %d stored; kept"
                                      % (len(obs), len(prev["obs"])))
                    doc = prev
                else:
                    revision = _diff_revisions(sid, prev["obs"], obs)
                    if revision and prev.get("source") == doc.get("source"):
                        if not dry:
                            econcore.log_revision(CHANGELOG, revision)
                        rec.update(action="revised",
                                   changed=revision["changed"])
                    added = len(obs) - len(prev["obs"])
                    if added > 0:
                        rec["added"] = added
            series[sid] = doc
        except Exception as exc:  # noqa: BLE001 - one dead endpoint, one chart
            errors[sid] = "%s: %s" % (type(exc).__name__, exc)
            rec.update(action="error", reason=errors[sid])
            if prev:
                series[sid] = prev
                rec["carried_forward"] = True
        results.append(rec)
        print("%-24s %-14s %s" % (sid, rec["action"], rec.get("reason", "")),
              flush=True)

    if not series:
        raise ValueError("nothing fetched and nothing stored; refusing to write")

    series.update(build_derived(series))
    analysis = build_analysis(series)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "note": "Machine-fetched. Never hand-edited; the updater rewrites this file wholesale.",
        "econcore": econcore.VERSION,
        "fred_key_used": bool(FRED_KEY),
        "errors": errors,
        "series": series,
        "analysis": analysis,
    }

    if dry:
        total = sum(len(s["obs"]) for s in series.values())
        print("dry run: %d series, %d observations, %d errors -- not written"
              % (len(series), total, len(errors)), flush=True)
        return payload

    tmp = SERIES_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, SERIES_FILE)

    with _lock:
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        _state["results"] = results
    _save_state()

    total = sum(len(s["obs"]) for s in series.values())
    print("series refreshed: %d series, %d observations, %d errors"
          % (len(series), total, len(errors)), flush=True)
    return payload


def _save_state():
    try:
        with _lock:
            snapshot = dict(_state)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        os.chmod(tmp, 0o644)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------
# read-only HTTP
# --------------------------------------------------------------------------

def _load(name):
    with open(os.path.join(DATA_DIR, name)) as fh:
        return json.load(fh)


def data_stamp():
    newest = 0.0
    names = [n + ".json" for n in CURATED] + ["series.json", "changelog.jsonl"]
    for name in names:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(DATA_DIR, name)))
        except OSError:
            continue
    return newest


def build_data_payload():
    stamp = data_stamp()
    if _payload_cache["stamp"] == stamp and _payload_cache["body"] is not None:
        return _payload_cache["body"]

    payload = {"generated_at": datetime.now(timezone.utc).isoformat()}
    for name in CURATED:
        try:
            payload[name] = _load(name + ".json")
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            payload[name] = None
            payload.setdefault("errors", {})[name] = str(exc)
    try:
        doc = _load("series.json")
        payload["series"] = doc.get("series", {})
        # The stored block is written by the refresh, which runs out of
        # process; one written before the status contract existed has no
        # headline, and the chip would stay hidden until the next scheduled
        # run. Recomputing the cheap half here makes a deploy take effect now.
        analysis = dict(doc.get("analysis", {}))
        if "headline" not in (analysis.get("status") or {}):
            analysis["status"] = build_status(payload["series"])
        payload["analysis"] = analysis
        payload["series_fetched_at"] = doc.get("fetched_at")
        payload["series_errors"] = doc.get("errors", {})
    except Exception as exc:  # noqa: BLE001 - charts degrade, page renders
        payload["series"] = {}
        payload["analysis"] = {}
        payload.setdefault("errors", {})["series"] = str(exc)

    recent, total = econcore.read_revisions(CHANGELOG, CHANGELOG_IN_PAYLOAD)
    payload["changelog"] = {"total": total, "recent": recent}

    _payload_cache["stamp"] = stamp
    _payload_cache["body"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, cache="no-cache"):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            # Probe the dependency, not the process: no data, not healthy.
            try:
                doc = _load("series.json")
                tonnage = doc.get("series", {}).get("us_truck_tonnage", {})
                st = doc.get("analysis", {}).get("status", {})
                self._send(200, {
                    "status": "ok",
                    "series": len(doc.get("series", {})),
                    "latest": tonnage.get("as_of"),
                    "headline": st.get("headline"),
                    "signal_active": st.get("signal_active"),
                    "errors": len(doc.get("errors", {})),
                    "fetched_at": doc.get("fetched_at"),
                })
            except Exception as exc:  # noqa: BLE001 - absent data IS the unhealthy case
                self._send(503, {"status": "no data", "error": str(exc)})
        elif path == "/api/data":
            self._send(200, build_data_payload(),
                       cache="public, max-age=300, must-revalidate")
        elif path == "/api/status":
            with _lock:
                snapshot = dict(_state)
            snapshot["fred_key"] = bool(FRED_KEY)
            snapshot["econcore"] = econcore.VERSION
            self._send(200, snapshot)
        elif path == "/api/changelog":
            recent, total = econcore.read_revisions(CHANGELOG, CHANGELOG_IN_PAYLOAD)
            self._send(200, {"total": total, "recent": recent})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return


def main():
    if "--refresh" in sys.argv:
        refresh_series()
        return
    if "--once" in sys.argv:
        refresh_series(dry=True)
        return

    print("updater starting: fred_key=%s (schedule: host cron)"
          % bool(FRED_KEY), flush=True)

    def warm():
        try:
            refresh_series()
        except Exception as exc:  # noqa: BLE001 - server must come up regardless
            print("initial fetch failed: %s" % exc, flush=True)

    threading.Thread(target=warm, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
