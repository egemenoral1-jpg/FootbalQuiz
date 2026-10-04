"""Claude + Egemen botu: hizli ve isabetli.

Hiz icin:
  - Her takimin oyuncu listesi onceden unlu_luge gore siralanir.
  - Soru gelince kucuk takimin listesinde yurunur, diger takimda oynamis
    ilk (yani en unlu) oyuncu bulunur bulunmaz cevap verilir.
  - Takim isimlerinin cozumu onbellekte tutulur.
  - Veri yuklendikten sonra gc.freeze(): 200 bin nesneyi tarayan cop toplayici
    tam cevap verirken araya girip milisaniyeler kaybettirmesin.
  - `Bot.handle` sayesinde bagla.py bu botu ayri surec acmadan, kendi icinde
    calistirir (iki boru atlamasi daha az).
"""
import gc
import json
import random
import sys

from quiz.db import FootballDB


class Bot:
    def __init__(self, db=None):
        db = self.db = db or FootballDB()
        self.by_fame = {t: sorted(ps, key=db.fame, reverse=True) for t, ps in db.links.items()}
        self.size = {t: len(ps) for t, ps in db.links.items()}

        # Takim secimi: buyuk, unlu ve baska buyuk takimlarla bol ortak oyuncusu olan
        # kulupler. Bol ortak oyuncu = cevabin hep var olmasi = puan bizde kalir.
        big = sorted(db.teams, key=lambda t: self.size.get(t, 0) * db.teams[t][1],
                     reverse=True)[:60]
        conn = {t: sum(1 for u in big if u != t and db.links[t] & db.links[u]) for t in big}
        self.pick_pool = [db.team_name(t) for t in sorted(big, key=conn.get, reverse=True)[:20]]

        self.resolve_cache = {}
        self.used = set()
        self.name_to_pids = None
        gc.collect()
        gc.freeze()

    def resolve(self, text):
        tid = self.resolve_cache.get(text, 0)
        if tid == 0:
            tid = self.resolve_cache[text] = self.db.resolve_team(text)
        return tid

    def answer(self, teams):
        t1, t2 = self.resolve(teams[0]), self.resolve(teams[1])
        if not t1 or not t2:
            return None
        used = self.used
        if t1 == t2:
            for p in self.by_fame[t1]:
                if p not in used:
                    return p
            return None
        small, other = (t1, t2) if self.size[t1] <= self.size[t2] else (t2, t1)
        other_set = self.db.links[other]
        for p in self.by_fame[small]:
            if p in other_set and p not in used:
                return p
        return None

    def handle(self, msg):
        """Bir hakem mesajina cevap (dict) ya da None dondurur."""
        typ = msg.get("type")
        if typ == "question":
            pid = self.answer(msg["teams"])
            return {"player": self.db.players[pid][0] if pid else None}
        if typ == "pick":
            return {"team": random.choice(self.pick_pool)}
        if typ == "result":
            name = msg.get("player")
            if name:  # kullanilan oyuncuyu bir daha soyleme
                if self.name_to_pids is None:
                    self.name_to_pids = {}
                    for p, v in self.db.players.items():
                        self.name_to_pids.setdefault(v[0], []).append(p)
                self.used.update(self.name_to_pids.get(name, ()))
            return None
        if typ == "hello":
            self.used.clear()
            return {"ready": True}
        return None


def main():
    bot = Bot()
    out = sys.stdout
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("type") == "end":
            break
        reply = bot.handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
