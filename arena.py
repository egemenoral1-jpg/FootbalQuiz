"""Iki botu kapistiran hakem.

Kullanim:
  python arena.py bots/claude_bot.py bots/ornek_bot.py
  python arena.py bots/claude_bot.py "node bots/arkadas.js" --rounds 20
  python arena.py --turnuva            (bots/ klasorundeki herkes birbiriyle)

Bir arguman .py ile bitiyorsa "python <dosya>" olarak calistirilir,
degilse oldugu gibi komut olarak calistirilir (her dilde bot yazilabilir).
Protokol icin: PROTOKOL.md
"""
import argparse
import glob
import itertools
import json
import os
import queue
import random
import shlex
import subprocess
import sys
import threading
import time

from quiz.db import FootballDB

if os.name == "nt":
    os.system("")  # Windows terminalinde ANSI renkleri ac

R, G, Y, B, C, DIM, BOLD, X = ("\033[31m", "\033[32m", "\033[33m", "\033[34m",
                               "\033[36m", "\033[2m", "\033[1m", "\033[0m")


class BotProcess:
    def __init__(self, spec):
        self.spec = spec
        self.name = os.path.splitext(os.path.basename(spec.split()[-1]))[0]
        cmd = [sys.executable, "-X", "utf8", spec] if spec.endswith(".py") else shlex.split(spec)
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   PYTHONPATH=os.path.dirname(os.path.abspath(__file__)))
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=sys.stderr, text=True, encoding="utf-8",
                                     bufsize=1, env=env)
        self.inbox = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        # Varis zamanini satir okunur okunmaz damgala: hiz olcumu buna gore
        for line in self.proc.stdout:
            t = time.perf_counter()
            try:
                self.inbox.put((t, json.loads(line)))
            except json.JSONDecodeError:
                pass  # botun debug ciktisi: yok say

    def send(self, msg):
        try:
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except OSError:
            pass

    def drain(self):
        while not self.inbox.empty():
            self.inbox.get_nowait()

    def recv(self, timeout):
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None, None

    def close(self):
        self.send({"type": "end"})
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def broadcast(bots, msg):
    """Mesaji herkese 'ayni anda' yolla: siralama avantaji olmasin diye karistir."""
    order = list(bots)
    random.shuffle(order)
    t0 = time.perf_counter()
    for b in order:
        b.send(msg)
    return t0


def collect(bots, timeout):
    """Her bottan bir cevap topla. [(bot, varis_zamani, mesaj)]"""
    out = {}
    deadline = time.perf_counter() + timeout
    while len(out) < len(bots):
        left = deadline - time.perf_counter()
        if left <= 0:
            break
        for b in bots:
            if b in out:
                continue
            t, msg = b.recv(timeout=min(left, 0.001))
            if msg is not None:
                out[b] = (t, msg)
    return out


def countdown(fast):
    for n in ("3", "2", "1"):
        print(f"  {BOLD}{Y}{n}...{X}", end=" ", flush=True)
        if not fast:
            time.sleep(0.6)
    print(f"{BOLD}{G}BASLA!{X}")


def play_match(db, spec_a, spec_b, rounds, fast, answer_timeout, quiet=False):
    bots = [BotProcess(spec_a), BotProcess(spec_b)]
    if bots[0].name == bots[1].name:
        bots[1].name += "_2"
    log = (lambda *a, **k: None) if quiet else print
    score = {b: 0 for b in bots}
    times = {b: [] for b in bots}
    used = []

    for i, b in enumerate(bots):
        b.send({"type": "hello", "you": b.name, "opponent": bots[1 - i].name, "rounds": rounds})
    ready = collect(bots, timeout=120)
    for b in bots:
        if b not in ready:
            log(f"{R}{b.name} hazir olmadi (120s){X}")

    log(f"\n{BOLD}{C}=== {bots[0].name}  vs  {bots[1].name} ==={X}")
    for rnd in range(1, rounds + 1):
        log(f"\n{BOLD}Tur {rnd}/{rounds}{X}")
        if not quiet:
            countdown(fast)
        for b in bots:
            b.drain()

        # 1) Herkes ayni anda takim soyler
        broadcast(bots, {"type": "pick", "round": rnd})
        picks = collect(bots, timeout=2.0)
        said, tids = {}, {}
        for b in bots:
            said[b] = (picks.get(b, (None, {}))[1] or {}).get("team")
            tids[b] = db.resolve_team(said[b]) if said[b] else None
            ok = f"{DIM}-> {db.team_name(tids[b])}{X}" if tids[b] else f"{R}(gecersiz takim){X}"
            log(f"  {b.name:>14}: {said[b]!s:<22} {ok}")

        bad = [b for b in bots if not tids[b]]
        if bad:
            for b in bots:
                if b not in bad and len(bad) == 1:
                    score[b] += 1
                    log(f"  {Y}Gecersiz takim -> puan {b.name}'a{X}")
            continue

        valid = db.common_players(tids[bots[0]], tids[bots[1]]) - set(used)
        if not valid:
            log(f"  {DIM}Ortak oyuncu yok, tur gecersiz.{X}")
            broadcast(bots, {"type": "result", "round": rnd, "winner": None, "player": None})
            continue

        # 2) Ayni anda soru: iki takimda da oynamis bir oyuncu
        teams_said = [said[bots[0]], said[bots[1]]]
        t0 = broadcast(bots, {"type": "question", "round": rnd, "teams": teams_said,
                              "used": [db.player_name(p) for p in used]})
        answers = collect(bots, timeout=answer_timeout)

        winner, wpid = None, None
        for b, (t, msg) in sorted(answers.items(), key=lambda kv: kv[1][0]):
            ans = (msg or {}).get("player")
            pid = db.match_player(ans, valid) if ans else None
            ms = (t - t0) * 1000
            times[b].append(ms)
            mark = f"{G}DOGRU{X}" if pid else f"{R}yanlis{X}"
            log(f"  {b.name:>14}: {ans!s:<28} {ms:8.2f} ms  {mark}")
            if pid and winner is None:
                winner, wpid = b, pid
        for b in bots:
            if b not in answers:
                log(f"  {b.name:>14}: {R}(sure doldu){X}")

        if winner:
            score[winner] += 1
            used.append(wpid)
            log(f"  {BOLD}{G}+1 {winner.name}{X}  ({db.player_name(wpid)})")
        else:
            ornek = db.player_name(max(valid, key=db.fame))
            log(f"  {DIM}Kimse bilemedi. Ornek: {ornek}{X}")
        broadcast(bots, {"type": "result", "round": rnd,
                         "winner": winner.name if winner else None,
                         "player": db.player_name(wpid) if wpid else None})

    for b in bots:
        b.close()

    log(f"\n{BOLD}{C}=== SKOR ==={X}")
    for b in sorted(bots, key=lambda b: -score[b]):
        avg = sum(times[b]) / len(times[b]) if times[b] else float("nan")
        log(f"  {b.name:>14}: {BOLD}{score[b]}{X}   (ort. cevap {avg:.2f} ms)")
    return {b.name: score[b] for b in bots}


def main():
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
        table = {os.path.splitext(os.path.basename(s))[0]: 0 for s in specs}
        for a, b in itertools.combinations(specs, 2):
            res = play_match(db, a, b, args.rounds, True, args.sure)
            na, nb = list(res)
            if res[na] != res[nb]:
                table[max(res, key=res.get)] += 3
            else:
                table[na] += 1
                table[nb] += 1
        print(f"\n{BOLD}{C}=== PUAN DURUMU ==={X}")
        for n, p in sorted(table.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>14}: {p}")
    elif len(args.bots) == 2:
        play_match(db, args.bots[0], args.bots[1], args.rounds, args.hizli, args.sure)
    else:
        ap.error("iki bot ver ya da --turnuva kullan")


if __name__ == "__main__":
    main()
