"""Mac motoru: kurallar burada. Terminal arenasi da web sitesi de bunu kullanir.

Bir "bot" su arayuze sahip herhangi bir nesnedir:
    name      : str
    inbox     : asyncio.Queue  -> (varis_zamani perf_counter, mesaj dict)
    latency   : float          -> sureden dusulecek ag gecikmesi (sn), yerelde 0
    async send(msg)

Mac boyunca olan her sey on_event(dict) ile disari bildirilir (ekrana basmak,
tarayiciya yollamak vb. icin).
"""
import asyncio
import random
import time

PICK_TIMEOUT = 2.0
READY_TIMEOUT = 120.0


def drain(bot):
    while not bot.inbox.empty():
        bot.inbox.get_nowait()


async def broadcast(bots, msg):
    """Herkese 'ayni anda' yolla: sira avantaji olmasin diye karistir."""
    order = list(bots)
    random.shuffle(order)
    t0 = time.perf_counter()
    await asyncio.gather(*(b.send(msg) for b in order))
    return t0


async def collect(bots, timeout, want):
    """Her bottan `want(msg)` saglayan ilk mesaji topla: {bot: (zaman, mesaj)}.
    Sure her bot icin kendi gecikmesi kadar uzatilir."""
    async def one(b):
        deadline = time.perf_counter() + timeout + b.latency
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                return None
            try:
                t, msg = await asyncio.wait_for(b.inbox.get(), left)
            except asyncio.TimeoutError:
                return None
            if isinstance(msg, dict) and want(msg):
                return t, msg

    res = await asyncio.gather(*(one(b) for b in bots))
    return {b: r for b, r in zip(bots, res) if r}


async def play_match(db, bots, rounds=10, answer_timeout=10.0, countdown=0.7,
                     on_event=lambda ev: None):
    a, b = bots
    score = {a.name: 0, b.name: 0}
    times = {a.name: [], b.name: []}
    used = []

    def emit(**ev):
        on_event(ev)

    emit(ev="basla", botlar=[a.name, b.name], tur_sayisi=rounds)
    for me, other in ((a, b), (b, a)):
        await me.send({"type": "hello", "you": me.name, "opponent": other.name,
                       "rounds": rounds})
    ready = await collect(bots, READY_TIMEOUT, lambda m: "ready" in m)
    for x in bots:
        if x not in ready:
            emit(ev="uyari", mesaj=f"{x.name} hazir olmadi")

    for rnd in range(1, rounds + 1):
        for n in (3, 2, 1):
            emit(ev="geri_sayim", tur=rnd, n=n)
            if countdown:
                await asyncio.sleep(countdown)
        for x in bots:
            drain(x)

        # 1) Herkes ayni anda takim soyler
        await broadcast(bots, {"type": "pick", "round": rnd})
        picks = await collect(bots, PICK_TIMEOUT, lambda m: "team" in m)
        said, tids = {}, {}
        for x in bots:
            said[x] = picks[x][1].get("team") if x in picks else None
            tids[x] = db.resolve_team(said[x]) if isinstance(said[x], str) else None
        emit(ev="takimlar", tur=rnd, secimler=[
            {"bot": x.name, "soylenen": said[x],
             "takim": db.team_name(tids[x]) if tids[x] else None} for x in bots])

        bad = [x for x in bots if not tids[x]]
        if bad:
            winner = None
            if len(bad) == 1:
                winner = a if bad[0] is b else b
                score[winner.name] += 1
            emit(ev="tur_sonu", tur=rnd, kazanan=winner.name if winner else None,
                 oyuncu=None, neden="gecersiz_takim", skor=dict(score))
            await broadcast(bots, {"type": "result", "round": rnd,
                                   "winner": winner.name if winner else None, "player": None})
            continue

        valid = db.common_players(tids[a], tids[b]) - set(used)
        if not valid:
            emit(ev="tur_sonu", tur=rnd, kazanan=None, oyuncu=None,
                 neden="ortak_oyuncu_yok", skor=dict(score))
            await broadcast(bots, {"type": "result", "round": rnd, "winner": None,
                                   "player": None})
            continue

        # 2) Ayni anda soru: iki takimda da oynamis bir oyuncu
        t0 = await broadcast(bots, {"type": "question", "round": rnd,
                                    "teams": [said[a], said[b]],
                                    "used": [db.player_name(p) for p in used]})
        answers = await collect(bots, answer_timeout, lambda m: "player" in m)

        rows = []
        for x, (t, msg) in answers.items():
            ans = msg.get("player")
            pid = db.match_player(ans, valid) if isinstance(ans, str) else None
            ms = max(0.0, (t - t0 - x.latency) * 1000)
            times[x.name].append(ms)
            rows.append({"bot": x.name, "cevap": ans, "ms": round(ms, 3), "pid": pid})
        rows.sort(key=lambda r: r["ms"])
        winner, wpid = None, None
        for r in rows:
            r["dogru"] = bool(r["pid"])
            if r["pid"] and not winner:
                winner, wpid = r["bot"], r["pid"]
        for x in bots:
            if x not in answers:
                rows.append({"bot": x.name, "cevap": None, "ms": None, "dogru": False,
                             "sure_doldu": True})
        for r in rows:
            r.pop("pid", None)
        emit(ev="cevaplar", tur=rnd, takimlar=[db.team_name(tids[a]), db.team_name(tids[b])],
             cevaplar=rows)

        if winner:
            score[winner] += 1
            used.append(wpid)
        ornek = None if winner else db.player_name(max(valid, key=db.fame))
        emit(ev="tur_sonu", tur=rnd, kazanan=winner,
             oyuncu=db.player_name(wpid) if wpid else None,
             neden="dogru_cevap" if winner else "kimse_bilemedi", ornek=ornek,
             skor=dict(score))
        await broadcast(bots, {"type": "result", "round": rnd, "winner": winner,
                               "player": db.player_name(wpid) if wpid else None})

    for x in bots:
        await x.send({"type": "end"})
    ort = {n: (round(sum(v) / len(v), 3) if v else None) for n, v in times.items()}
    emit(ev="bitti", skor=dict(score), ort_ms=ort)
    return score
