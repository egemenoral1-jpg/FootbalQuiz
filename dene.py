"""Bir botu elle sectigin takimlarla dene.

  python dene.py bots/claude_bot.py Galatasaray Fenerbahçe
  python dene.py bots/claude_bot.py            (etkilesimli: takimlari sen yaz)

Botun cevabini, suresini ve hakemin dogru sayip saymayacagini gosterir.
"""
import sys
import time

from arena import BotProcess, B, G, R, DIM, X
from quiz.db import FootballDB


def ask(db, bot, t1, t2):
    bot.drain()
    t0 = time.perf_counter()
    bot.send({"type": "question", "round": 1, "teams": [t1, t2], "used": []})
    t, msg = bot.recv(timeout=10)
    if msg is None:
        print(f"  {R}cevap gelmedi (10 sn){X}")
        return
    ans = msg.get("player")
    id1, id2 = db.resolve_team(t1), db.resolve_team(t2)
    if not id1 or not id2:
        bad = t1 if not id1 else t2
        print(f"  {R}hakem '{bad}' takimini tanimiyor{X}")
        return
    valid = db.common_players(id1, id2)
    pid = db.match_player(ans, valid) if ans else None
    mark = f"{G}DOGRU{X}" if pid else f"{R}YANLIS{X}"
    print(f"  {db.team_name(id1)} + {db.team_name(id2)}  ({len(valid)} ortak oyuncu)")
    print(f"  cevap: {B}{ans}{X}   {(t - t0) * 1000:.2f} ms   {mark}")
    if not pid and valid:
        ornek = sorted(valid, key=db.fame, reverse=True)[:5]
        print(f"  {DIM}dogrular: {', '.join(db.player_name(p) for p in ornek)}{X}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    db = FootballDB()
    bot = BotProcess(sys.argv[1])
    bot.send({"type": "hello", "you": bot.name, "opponent": "dene", "rounds": 1})
    bot.recv(timeout=120)

    if len(sys.argv) >= 4:
        ask(db, bot, sys.argv[2], sys.argv[3])
    else:
        print("Iki takimi virgulle yaz (orn: gs, fb). Cikmak icin bos birak.")
        while True:
            line = input("> ").strip()
            if not line:
                break
            if "," not in line:
                print("  virgulle ayir: Galatasaray, Real Madrid")
                continue
            t1, t2 = (s.strip() for s in line.split(",", 1))
            ask(db, bot, t1, t2)
    bot.close()


if __name__ == "__main__":
    main()
