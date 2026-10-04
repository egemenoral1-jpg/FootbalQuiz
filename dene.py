"""Bir botu elle sectigin takimlarla dene.

  python dene.py bots/claude_bot.py Galatasaray Fenerbahçe
  python dene.py bots/claude_bot.py            (etkilesimli: takimlari sen yaz)

Botun cevabini, suresini ve hakemin dogru sayip saymayacagini gosterir.
"""
import asyncio
import sys
import time

from arena import B, G, R, DIM, X
from quiz.db import FootballDB
from quiz.mac import drain
from quiz.yerel import LocalBot


async def ask(db, bot, t1, t2):
    drain(bot)
    t0 = time.perf_counter()
    await bot.send({"type": "question", "round": 1, "teams": [t1, t2], "used": []})
    try:
        t, msg = await asyncio.wait_for(bot.inbox.get(), 10)
    except asyncio.TimeoutError:
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


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    db = FootballDB()
    bot = await LocalBot(sys.argv[1]).start()
    await bot.send({"type": "hello", "you": bot.name, "opponent": "dene", "rounds": 1})
    await asyncio.wait_for(bot.inbox.get(), 120)

    if len(sys.argv) >= 4:
        await ask(db, bot, sys.argv[2], sys.argv[3])
    else:
        print("Iki takimi virgulle yaz (orn: gs, fb). Cikmak icin bos birak.")
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                break
            if "," not in line:
                print("  virgulle ayir: Galatasaray, Real Madrid")
                continue
            t1, t2 = (s.strip() for s in line.split(",", 1))
            await ask(db, bot, t1, t2)
    await bot.send({"type": "end"})
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
