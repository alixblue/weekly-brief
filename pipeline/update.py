#!/usr/bin/env python3
"""The Weekly Brief: daily update pipeline.

  python update.py fetch    # pull feeds -> rank -> (optional) AI summaries -> data/news.json
  python update.py render   # data/news.json + glossary -> site/index.html
  python update.py all      # both (what the daily GitHub Action runs)

Standard library only. If ANTHROPIC_API_KEY is set, Claude reads each original article
and writes the in-page brief (3 short paragraphs), a neutral card summary, notes on how
other outlets framed the story, and definitions for new jargon. Article text itself is
never stored or published, only the brief written from it.
"""
import json, os, re, sys, html, math, datetime as dt
import urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
NEWS = ROOT / "data" / "news.json"
OUT = ROOT / "site" / "index.html"

MAX_ITEMS = 30
WINDOW_DAYS = 7
TOPIC_BOOST = {"aerospace": 1.45, "business": 1.3, "markets": 1.25, "environment": 1.0, "science": 1.0, "world": 1.0, "culture": 0.7}
TOPIC_CAP = {"aerospace": 9, "business": 7, "markets": 5, "environment": 5, "science": 4, "world": 4, "culture": 3}
PER_SOURCE_CAP = 6
MODEL = "claude-haiku-5-5"

# Keyword fallback when no API key is set. First match wins, in this order.
TOPIC_WORDS = {
    "aerospace": r"airbus|boeing|embraer|airline|aircraft|aviation|airport|jet\b|engine maker|faa|easa|spacex|satellite|rocket|nasa|evtol|air taxi|mro|flight",
    "environment": r"climate|emission|net.zero|carbon|renewable|solar|wind power|biodiversity|wildfire|drought|flood|pollution|cop\d",
    "markets": r"stocks?\b|shares|s&p|dow jones|nasdaq|ftse|bond|treasury|yield|interest rate|central bank|federal reserve|\bfed\b|inflation|currency|dollar|investor|ipo|earnings season",
    "business": r"econom|market|stock|shares|profit|earnings|inflation|interest rate|central bank|federal reserve|tariff|trade|merger|acquisition|ipo|bank|gdp|jobs",
    "culture": r"\bfilm|movie|music|album|museum|\bart\b|artist|festival|book|novel|world cup|league|olympic|tournament|football|soccer|rugby|tennis|nba|nfl|mlb|formula 1|\bf1\b",
    "science": r"study|research|scientist|vaccine|disease|\bai\b|artificial intelligence|quantum|genome|physics|nobel",
}

NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/",
      "content": "http://purl.org/rss/1.0/modules/content/"}


def log(*a): print(*a, file=sys.stderr)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "WeeklyBrief/1.0 (personal news reader)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s):
    if not s: return None
    try: d = parsedate_to_datetime(s)
    except Exception:
        try: d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def parse_feed(raw, source):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):  # RSS 2.0
        out.append(dict(title=clean(it.findtext("title")), url=(it.findtext("link") or "").strip(),
                        summary=clean(it.findtext("description")),
                        author=clean(it.findtext("dc:creator", namespaces=NS) or it.findtext("author")),
                        date=parse_date(it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS))))
    for e in root.iter("{%s}entry" % NS["atom"]):  # Atom
        link = e.find("atom:link[@rel='alternate']", NS)
        if link is None: link = e.find("atom:link", NS)
        out.append(dict(title=clean(e.findtext("atom:title", namespaces=NS)), url=link.get("href") if link is not None else "",
                        summary=clean(e.findtext("atom:summary", namespaces=NS) or e.findtext("atom:content", namespaces=NS)),
                        author=clean(e.findtext("atom:author/atom:name", namespaces=NS)),
                        date=parse_date(e.findtext("atom:published", namespaces=NS) or e.findtext("atom:updated", namespaces=NS))))
    for o in out: o["source"] = source["name"]
    return out


def fetch_all(sources):
    now = dt.datetime.now(dt.timezone.utc)
    items, failed = [], []
    for s in sources:
        for f in s.get("feeds", []):
            try:
                got = parse_feed(get(f), s)
                items += [i for i in got if i["title"] and i["url"] and i["date"] and (now - i["date"]).days < WINDOW_DAYS]
            except Exception as e:
                failed.append(f"{s['name']}: {f} ({e.__class__.__name__})")
    for f in failed: log("feed failed:", f)
    log(f"{len(items)} candidate items from {len(sources)} outlets, {len(failed)} feeds failed")
    return items


def words(t): return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 3}


def cluster(items):
    """Group the same story told by different outlets. More outlets = more important."""
    clusters = []
    for it in sorted(items, key=lambda i: i["date"], reverse=True):
        w = words(it["title"])
        for c in clusters:
            cw = c["words"]
            if w and len(w & cw) / len(w | cw) >= 0.35:
                c["items"].append(it); c["words"] |= w; break
        else:
            clusters.append({"items": [it], "words": w})
    return clusters


def guess_topic(text):
    for t, pat in TOPIC_WORDS.items():
        if re.search(pat, text, re.I): return t
    return "world"


def rank(clusters, src_by_name):
    now = dt.datetime.now(dt.timezone.utc)
    scored = []
    for c in clusters:
        # lead with the most trusted outlet's version
        c["items"].sort(key=lambda i: src_by_name[i["source"]].get("weight", 1), reverse=True)
        lead = c["items"][0]
        outlets = {i["source"] for i in c["items"]}
        age = (now - max(i["date"] for i in c["items"])).total_seconds() / 86400
        topic = guess_topic(lead["title"] + " " + lead["summary"])
        score = (src_by_name[lead["source"]].get("weight", 1)
                 * (1 + 0.6 * (len(outlets) - 1))
                 * TOPIC_BOOST[topic]
                 * max(0.3, 1 - age / 10))
        scored.append((score, topic, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def select(scored, src_by_name):
    """Top stories under caps, then make sure both sides of the spectrum are present."""
    picked, per_src, per_topic = [], {}, {}
    side = lambda s: "left" if "left" in s else "right" if "right" in s else "center"
    for score, topic, c in scored:
        lead = c["items"][0]["source"]
        if per_src.get(lead, 0) >= PER_SOURCE_CAP or per_topic.get(topic, 0) >= TOPIC_CAP[topic]: continue
        picked.append((score, topic, c)); per_src[lead] = per_src.get(lead, 0) + 1; per_topic[topic] = per_topic.get(topic, 0) + 1
        if len(picked) == MAX_ITEMS: break
    # balance: the weaker side of the spectrum must have at least 3/4 as many stories as the stronger side
    sides = lambda: {s: sum(1 for _, _, c in picked if side(src_by_name[c["items"][0]["source"]]["lean"]) == s) for s in ("left", "right")}
    for weak in ("left", "right"):
        strong = "right" if weak == "left" else "left"
        spare = [x for x in scored if x not in picked and side(src_by_name[x[2]["items"][0]["source"]]["lean"]) == weak]
        while spare and sides()[weak] * 4 < sides()[strong] * 3:
            drop = min((x for x in picked if side(src_by_name[x[2]["items"][0]["source"]]["lean"]) == strong), key=lambda x: x[0])
            picked.remove(drop); picked.append(spare.pop(0))
    picked.sort(key=lambda x: x[0], reverse=True)
    out = []
    for n, (score, topic, c) in enumerate(picked):
        lead = c["items"][0]
        out.append({"topic": topic, "importance": 3 if n < 3 else 2 if n < 12 else 1,
                    "title": lead["title"], "source": lead["source"], "url": lead["url"],
                    "date": lead["date"].date().isoformat(), "author": lead["author"] or None,
                    "summary": (lead["summary"][:320].rsplit(" ", 1)[0] + "…") if len(lead["summary"]) > 320 else lead["summary"],
                    "also": [{"source": i["source"], "author": i["author"] or None, "date": i["date"].date().isoformat(),
                              "title": i["title"], "url": i["url"]} for i in c["items"][1:4] if i["source"] != lead["source"]]})
    return out


def article_text(url, limit=9000):
    """Paragraph text of the original article, used only as input for the brief (never stored or published)."""
    try:
        page = get(url).decode("utf-8", "ignore")
    except Exception:
        return ""
    page = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", page)
    paras = [clean(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)]
    return "\n".join(p for p in paras if len(p) > 60)[:limit]


def ask_claude(key, prompt, max_tokens=1500):
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    text = json.loads(urllib.request.urlopen(req, timeout=120).read())["content"][0]["text"]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


BRIEF_PROMPT = """You write one story for a neutral daily news digest. The reader works in aerospace and studied business.
Using ONLY the article text below (no outside facts), return JSON:
{{"topic": one of aerospace|business|markets|environment|science|world|culture (culture = arts, media, sport; markets = stocks, bonds, rates, central banks, currencies),
 "summary": one or two plain sentences for the story card,
 "brief": {{"what": what happened, 1-2 sentences with the key numbers,
           "who": the main actors and their role in the story,
           "context": the background a reader needs,
           "why": why it happened, as stated in the article (attribute claims and opinions to who made them),
           "next": what happens next, or "The article doesn't say." }},
 Each brief field 1-3 sentences, 150-220 words in total, no opinions of your own.
 "terms": {{term: one-sentence plain definition}} for up to 4 industry or jargon terms that appear verbatim in your summary or brief,
 "kind": "news", "opinion" (the writer argues a view: column, op-ed, review) or "analysis" (reporting mixed with the writer's interpretation),
 "notes": [for each other outlet listed, one short sentence on how its headline frames the story differently, or "" if it does not]}}

Outlet: {source}
Headline: {title}
Other outlets covering it: {others}
Article text (public part only):
{text}"""


def claude_polish(items, glossary):
    """Optional: in-page briefs, card summaries, topic check, new glossary terms. Needs ANTHROPIC_API_KEY."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return items, glossary
    for it in items:
        text = article_text(it["url"])
        if len(text) < 1500: text = (it["summary"] + "\n" + text).strip()  # paywalled: use only the public part
        others = "; ".join(f'{a["source"]}: "{a["title"]}"' for a in it.get("also", [])) or "none"
        try:
            r = ask_claude(key, BRIEF_PROMPT.format(source=it["source"], title=it["title"], others=others,
                                                    text=text))
        except Exception as e:
            log("brief skipped:", it["title"][:60], e); continue
        if r.get("topic") in TOPIC_BOOST: it["topic"] = r["topic"]
        if r.get("kind") in ("opinion", "analysis"): it["kind"] = r["kind"]
        it["summary"] = r.get("summary") or it["summary"]
        if r.get("brief"): it["brief"] = r["brief"]
        for a, note in zip(it.get("also", []), r.get("notes") or []):
            if note: a["note"] = note
        for t, d in (r.get("terms") or {}).items(): glossary.setdefault(t, d)
    return items, glossary


ARCHIVE = ROOT / "data" / "archive"


def follow_ups(items, days=21):
    """Link today's stories to earlier editions' coverage of the same story (shown as 'Update')."""
    today = dt.date.today()
    past = []
    for f in sorted(ARCHIVE.glob("*.json")):
        try: day = dt.date.fromisoformat(f.stem)
        except ValueError: continue
        if 0 < (today - day).days <= days: past += json.loads(f.read_text())
    for it in items:
        w = words(it["title"])
        hits = {p["url"]: p for p in past if p["url"] != it["url"] and w and len(w & words(p["title"])) / len(w | words(p["title"])) >= 0.3}
        if hits: it["earlier"] = sorted(hits.values(), key=lambda p: p["date"], reverse=True)[:3]
    return items


def save_archive(items):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    keep = [{k: it.get(k) for k in ("title", "url", "source", "date")} for it in items]
    (ARCHIVE / f"{dt.date.today().isoformat()}.json").write_text(json.dumps(keep, indent=1, ensure_ascii=False))


MARKETS = [("S&P 500", "^spx", "{:,.2f}"), ("Dow", "^dji", "{:,.2f}"), ("Nasdaq", "^ndq", "{:,.2f}"),
           ("Brent oil", "cb.f", "${:,.2f}"), ("US 10-yr yield", "10usy.b", "{:.2f}%"), ("EUR/USD", "eurusd", "{:.4f}")]


def markets():
    """Latest close and change over the past week, from Stooq's free daily CSV (no key needed)."""
    out, asof = [], None
    for name, sym, fmt in MARKETS:
        try:
            rows = [r.split(",") for r in get(f"https://stooq.com/q/d/l/?s={sym}&i=d").decode().strip().splitlines()[1:]]
            last, week_ago = rows[-1], rows[-6]
            v, v0 = float(last[4]), float(week_ago[4])
            ch = f"{v - v0:+.2f} pt" if sym.endswith("y.b") else f"{(v / v0 - 1) * 100:+.1f}%"
            out.append({"name": name, "value": fmt.format(v), "change": ch}); asof = max(asof or last[0], last[0])
        except Exception as e:
            log("market data skipped:", name, e.__class__.__name__)
    if not out: return None
    label = dt.date.fromisoformat(asof).strftime("%a %d %b close · change over 1 week")
    return {"asof": asof, "label": label, "source": "Stooq", "items": out}


WEEK_PROMPT = """From these story summaries of the past week, return JSON:
{{"week": [5 items {{"text": one or two plain sentences joining related stories into one takeaway, "urls": [urls of the stories it draws on]}}],
 "watch": [up to 6 items {{"date": "YYYY-MM-DD", "when": short label if the exact day is unknown (e.g. "Late Oct") else "", "label": what happens, "url": story url}}
           for future dates explicitly mentioned in the stories]}}
Only use facts in the summaries. Neutral tone. Today is {today}.

{stories}"""


def week_and_watch(items):
    key = os.environ.get("ANTHROPIC_API_KEY")
    top = sorted(items, key=lambda i: -i["importance"])
    fallback = {"week": [{"text": i["summary"], "urls": [i["url"]]} for i in top[:5]], "watch": []}
    if not key: return fallback
    stories = "\n\n".join(f'{i["url"]}\n{i["title"]}\n{i["summary"]}\nNext: {(i.get("brief") or {}).get("next", "") if isinstance(i.get("brief"), dict) else ""}' for i in items)
    try:
        r = ask_claude(key, WEEK_PROMPT.format(today=dt.date.today().isoformat(), stories=stories), max_tokens=2500)
        return {"week": r.get("week") or fallback["week"], "watch": r.get("watch") or []}
    except Exception as e:
        log("week summary skipped:", e); return fallback


def do_fetch():
    sources = json.loads((PIPE / "sources.json").read_text())["sources"]
    src_by_name = {s["name"]: s for s in sources}
    glossary = json.loads((PIPE / "glossary.json").read_text())
    items = select(rank(cluster(fetch_all(sources)), src_by_name), src_by_name)
    items, glossary = claude_polish(items, glossary)
    items = follow_ups(items)
    extra = week_and_watch(items)
    save_archive(items)
    (PIPE / "glossary.json").write_text(json.dumps(glossary, indent=2, ensure_ascii=False))
    today = dt.date.today()
    NEWS.write_text(json.dumps({"generated": today.isoformat(),
                                "window": f"{(today - dt.timedelta(days=WINDOW_DAYS)).isoformat()} to {today.isoformat()}",
                                "method": f"Pulled automatically from {len(sources)} whitelisted outlets; ranked by outlet trust, how many outlets covered the story, recency and your topic weights.",
                                "markets": markets(), **extra,
                                "items": items}, indent=2, ensure_ascii=False))
    log(f"wrote {len(items)} items to {NEWS}")


def do_render():
    data = json.loads(NEWS.read_text())
    data["glossary"] = json.loads((PIPE / "glossary.json").read_text())
    data["sources"] = {s["name"]: {"lean": s["lean"], "kind": s["kind"]} for s in json.loads((PIPE / "sources.json").read_text())["sources"]}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text((PIPE / "template.html").read_text().replace("/*__DATA__*/null", payload))
    log(f"rendered {OUT}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("fetch", "all"): do_fetch()
    if cmd in ("render", "all"): do_render()
