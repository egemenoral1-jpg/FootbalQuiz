"""Claude + Egemen botu: hizli ve isabetli.

Hiz icin:
  - Her takimin oyuncu listesi onceden unlu_luge gore siralanir.
  - Soru gelince kucuk takimin listesinde yurunur, diger takimda oynamis
    ilk (yani en unlu) oyuncu bulunur bulunmaz cevap verilir.
  - Ayni takim cifti tekrar gelirse cevap onbellekten.
"""
import json
import random
import sys

from quiz.db import FootballDB

out = sys.stdout


def send(msg):
    out.write(json.dumps(msg, ensure_ascii=False) + "\n")
    out.flush()


def main():
    db = FootballDB()
    by_fame = {t: sorted(ps, key=db.fame, reverse=True) for t, ps in db.links.items()}

    # Takim secimi: buyuk, unlu ve baska buyuk takimlarla bol ortak oyuncusu olan
    # kulupler. Bol ortak oyuncu = cevabin hep var olmasi = puan bizde kalir.
    big = sorted(db.teams, key=lambda t: len(db.links.get(t, ())) * db.teams[t][1],
                 reverse=True)[:60]
    def connectivity(t):
        return sum(1 for u in big if u != t and db.links[t] & db.links[u])
    pick_pool = sorted(big, key=connectivity, reverse=True)[:20]

    resolve_cache = {}
    used = set()

    def resolve(text):
        if text not in resolve_cache:
            resolve_cache[text] = db.resolve_team(text)
        return resolve_cache[text]

    def answer(teams):
        t1, t2 = resolve(teams[0]), resolve(teams[1])
        if not t1 or not t2:
            return None
        if t1 == t2:
            for p in by_fame[t1]:
                if p not in used:
                    return p
            return None
        small, other = (t1, t2) if len(db.links[t1]) <= len(db.links[t2]) else (t2, t1)
        other_set = db.links[other]
        for p in by_fame[small]:
            if p in other_set and p not in used:
                return p
        return None

    for line in sys.stdin:
        msg = json.loads(line)
        typ = msg.get("type")
        if typ == "question":
            pid = answer(msg["teams"])
            send({"player": db.player_name(pid) if pid else None})
        elif typ == "pick":
            send({"team": db.team_name(random.choice(pick_pool))})
        elif typ == "result":
            # Kullanilan oyuncuyu bir daha soyleme
            name = msg.get("player")
            if name:
                used.update(p for p in db.players if db.players[p][0] == name)
        elif typ == "hello":
            used.clear()
            send({"ready": True})
        elif typ == "end":
            break


if __name__ == "__main__":
    main()
