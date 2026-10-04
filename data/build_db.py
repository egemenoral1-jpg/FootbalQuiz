"""Wikidata'dan futbolcu -> takim veritabanini indirir.

Kullanim:  python data/build_db.py [--min-sitelinks 3]
Cikti:     data/football.json.gz

Yapi:
  players: {pid: [isim, unlu_lik(sitelink), [diger isimler...]]}
  teams:   {tid: [isim, unlu_lik, [diger isimler...]]}
  links:   {tid: [pid, pid, ...]}   (o takimda oynamis oyuncular)
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://query.wikidata.org/sparql"
UA = {"User-Agent": "FootbalQuizBot/0.1 (hobby project; github.com/egemenoral1-jpg/FootbalQuiz)"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "football.json.gz")

# Sitelink bantlari: buyuk sorgular zaman asimina ugramasin diye parcali cekiyoruz.
BANDS = [(60, 10_000), (30, 59), (20, 29), (15, 19), (12, 14), (10, 11),
         (9, 9), (8, 8), (7, 7), (6, 6), (5, 5), (4, 4), (3, 3), (2, 2), (1, 1)]


def sparql(query, retries=4):
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(ENDPOINT, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:  # zaman asimi / 429
            wait = 5 * (i + 1)
            print(f"  hata: {e} -> {wait}s sonra tekrar", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("sorgu basarisiz")


def qid(uri):
    return uri.rsplit("/", 1)[1]


def fetch_links(lo, hi):
    q = f"""
    SELECT ?p ?t ?s WHERE {{
      ?p wdt:P106 wd:Q937857 ; wikibase:sitelinks ?s .
      FILTER(?s >= {lo} && ?s <= {hi})
      # wdt:P54 sadece "tercih edilen" (guncel) kulubu dondurebilir; tum kariyer icin p:/ps:
      ?p p:P54 ?st . ?st ps:P54 ?t ; wikibase:rank ?r .
      FILTER(?r != wikibase:DeprecatedRank)
    }}"""
    return sparql(q)


def fetch_labels(ids, with_sitelinks):
    """tr/en etiketleri + takma adlari (aliases) toplu ceker."""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 2000):
        chunk = " ".join(f"wd:{x}" for x in ids[i:i + 2000])
        sl = "OPTIONAL { ?x wikibase:sitelinks ?s . }" if with_sitelinks else ""
        q = f"""
        SELECT ?x ?l ?lang ?kind ?s WHERE {{
          VALUES ?x {{ {chunk} }}
          {sl}
          {{ ?x rdfs:label ?l . BIND("label" AS ?kind) }}
          UNION {{ ?x skos:altLabel ?l . BIND("alias" AS ?kind) }}
          BIND(LANG(?l) AS ?lang)
          FILTER(?lang IN ("tr", "en"))
        }}"""
        for b in sparql(q):
            x = qid(b["x"]["value"])
            e = out.setdefault(x, {"tr": None, "en": None, "alias": set(), "s": 0})
            if "s" in b:
                e["s"] = int(b["s"]["value"])
            name, lang = b["l"]["value"], b["lang"]["value"]
            if b["kind"]["value"] == "label":
                e[lang] = name
            e["alias"].add(name)
        print(f"  etiket {min(i + 2000, len(ids))}/{len(ids)}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sitelinks", type=int, default=3)
    args = ap.parse_args()

    links, pfame = {}, {}
    for lo, hi in BANDS:
        if hi < args.min_sitelinks:
            continue
        lo = max(lo, args.min_sitelinks)
        t = time.time()
        rows = fetch_links(lo, hi)
        for b in rows:
            p, tm = qid(b["p"]["value"]), qid(b["t"]["value"])
            pfame[p] = int(b["s"]["value"])
            links.setdefault(tm, set()).add(p)
        print(f"bant {lo}-{hi}: {len(rows)} satir ({time.time() - t:.1f}s), "
              f"toplam oyuncu {len(pfame)}", file=sys.stderr)

    # Tek oyunculu takimlar soruya hic cevap uretmez ama yine de taninmalari icin tutuyoruz
    print("oyuncu isimleri...", file=sys.stderr)
    plab = fetch_labels(pfame.keys(), with_sitelinks=False)
    print("takim isimleri...", file=sys.stderr)
    tlab = fetch_labels(links.keys(), with_sitelinks=True)

    def pack(lab, fame):
        name = lab["tr"] or lab["en"] or min(lab["alias"])
        aliases = sorted(a for a in lab["alias"] if a != name)
        return [name, fame, aliases]

    # tr/en ismi hic olmayanlari at
    players = {p: pack(plab[p], pfame[p]) for p in pfame if plab.get(p, {}).get("alias")}
    teams = {t: pack(tlab[t], tlab[t]["s"]) for t in links if tlab.get(t, {}).get("alias")}
    db = {
        "built": time.strftime("%Y-%m-%d"),
        "players": players,
        "teams": teams,
        "links": {t: sorted(ps & players.keys()) for t, ps in links.items() if t in teams},
    }
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    print(f"yazildi: {OUT}  oyuncu={len(players)} takim={len(teams)}", file=sys.stderr)


if __name__ == "__main__":
    main()
