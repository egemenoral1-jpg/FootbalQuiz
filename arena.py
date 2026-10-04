"""Iki botu bilgisayarinda kapistiran hakem (internet gerekmez).

Kullanim:
  python arena.py bots/claude_bot.py bots/ornek_bot.py
  python arena.py bots/claude_bot.py "node bots/arkadas.js" --rounds 20
  python arena.py --turnuva            (bots/ klasorundeki herkes birbiriyle)

Bir arguman .py ile bitiyorsa "python <dosya>" olarak calistirilir,
degilse oldugu gibi komut olarak calistirilir (her dilde bot yazilabilir).
Protokol icin: PROTOKOL.md
"""
import argparse
import asyncio
import glob
import itertools
import os

from quiz.db import FootballDB
from quiz.mac import play_match
from quiz.yerel import LocalBot

if os.name == "nt":
    os.system("")  # Windows terminalinde ANSI renkleri ac

R, G, Y, B, C, DIM, BOLD, X = ("\033[31m", "\033[32m", "\033[33m", "\033[34m",
                               "\033[36m", "\033[2m", "\033[1m", "\033[0m")


def printer(ev):
    e = ev["ev"]
    if e == "basla":
        print(f"\n{BOLD}{C}=== {ev['botlar'][0]}  vs  {ev['botlar'][1]} ==={X}")
    elif e == "uyari":
        print(f"{R}{ev['mesaj']}{X}")
    elif e == "geri_sayim":
        if ev["n"] == 3:
            print(f"\n{BOLD}Tur {ev['tur']}{X}")
        print(f"  {BOLD}{Y}{ev['n']}...{X}", end=" ", flush=True)
        if ev["n"] == 1:
            print(f"{BOLD}{G}BASLA!{X}")
    elif e == "takimlar":
        for s in ev["secimler"]:
            ok = f"{DIM}-> {s['takim']}{X}" if s["takim"] else f"{R}(gecersiz takim){X}"
            print(f"  {s['bot']:>14}: {s['soylenen']!s:<22} {ok}")
    elif e == "cevaplar":
        for r in ev["cevaplar"]:
            if r.get("sure_doldu"):
                print(f"  {r['bot']:>14}: {R}(sure doldu){X}")
                continue
            mark = f"{G}DOGRU{X}" if r["dogru"] else f"{R}yanlis{X}"
            print(f"  {r['bot']:>14}: {r['cevap']!s:<28} {r['ms']:8.2f} ms  {mark}")
    elif e == "tur_sonu":
        if ev["neden"] == "dogru_cevap":
            print(f"  {BOLD}{G}+1 {ev['kazanan']}{X}  ({ev['oyuncu']})")
        elif ev["neden"] == "gecersiz_takim":
            if ev["kazanan"]:
                print(f"  {Y}Gecersiz takim -> puan {ev['kazanan']}'a{X}")
        elif ev["neden"] == "ortak_oyuncu_yok":
            print(f"  {DIM}Ortak oyuncu yok, tur gecersiz.{X}")
        else:
            print(f"  {DIM}Kimse bilemedi. Ornek: {ev['ornek']}{X}")
    elif e == "bitti":
        print(f"\n{BOLD}{C}=== SKOR ==={X}")
        for n, s in sorted(ev["skor"].items(), key=lambda kv: -kv[1]):
            avg = ev["ort_ms"][n]
            avg = f"{avg:.2f} ms" if avg is not None else "-"
            print(f"  {n:>14}: {BOLD}{s}{X}   (ort. cevap {avg})")


async def match(db, spec_a, spec_b, rounds, fast, answer_timeout, quiet=False):
    a = await LocalBot(spec_a).start()
    b = await LocalBot(spec_b).start()
    if a.name == b.name:
        b.name += "_2"
    try:
        return await play_match(db, [a, b], rounds, answer_timeout,
                                countdown=0 if fast else 0.6,
                                on_event=(lambda ev: None) if quiet else printer)
    finally:
        await asyncio.gather(a.close(), b.close())


async def main():
    ap = argparse.ArgumentParser(description="FootbalQuiz bot arenasi")
    ap.add_argument("bots", nargs="*", help="iki bot (dosya ya da komut)")
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--hizli", action="store_true", help="3-2-1 beklemesini atla")
    ap.add_argument("--sure", type=float, default=10.0, help="cevap suresi (sn)")
    ap.add_argument("--turnuva", action="store_true", help="bots/ icindeki herkes kapissin")
    args = ap.parse_args()

    print(f"{DIM}Veritabani yukleniyor...{X}", flush=True)
    db = FootballDB()

    if args.turnuva:
        specs = sorted(glob.glob("bots/*.py"))
        table = {}
        for sa, sb in itertools.combinations(specs, 2):
            res = await match(db, sa, sb, args.rounds, True, args.sure)
            na, nb = list(res)
            for n in (na, nb):
                table.setdefault(n, 0)
            if res[na] != res[nb]:
                table[max(res, key=res.get)] += 3
            else:
                table[na] += 1
                table[nb] += 1
        print(f"\n{BOLD}{C}=== PUAN DURUMU ==={X}")
        for n, p in sorted(table.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>14}: {p}")
    elif len(args.bots) == 2:
        await match(db, args.bots[0], args.bots[1], args.rounds, args.hizli, args.sure)
    else:
        ap.error("iki bot ver ya da --turnuva kullan")


if __name__ == "__main__":
    asyncio.run(main())
