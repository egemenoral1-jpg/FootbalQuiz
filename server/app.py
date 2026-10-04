"""FootbalQuiz web sitesi: botlar internetten baglanir, birbirini davet eder,
maclar tarayicida canli izlenir.

Calistir:  python -m server.app            (http://localhost:8080)
Ortam:     PORT, DB_YOLU (sqlite dosyasi)
"""
import asyncio
import collections
import hashlib
import itertools
import json
import os
import re
import secrets
import sqlite3
import time

from aiohttp import web, WSMsgType

from quiz.db import FootballDB
from quiz.mac import play_match

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MAX_TUR = 30
DAVET_SURE = 15  # sn: davet edilen bot bu surede kabul etmeli


def hash_token(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


# ---------------------------------------------------------------- kalici veri
class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS bots (
                ad TEXT PRIMARY KEY COLLATE NOCASE, token TEXT NOT NULL, olusturma REAL);
            CREATE TABLE IF NOT EXISTS maclar (
                id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT, b TEXT, skor_a INT,
                skor_b INT, tarih REAL, olaylar TEXT);
        """)

    def kayit(self, ad):
        tok = secrets.token_urlsafe(24)
        try:
            self.db.execute("INSERT INTO bots VALUES (?,?,?)", (ad, hash_token(tok), time.time()))
            self.db.commit()
        except sqlite3.IntegrityError:
            return None
        return tok

    def kim(self, tok):
        row = self.db.execute("SELECT ad FROM bots WHERE token=?", (hash_token(tok or ""),)).fetchone()
        return row[0] if row else None

    def mac_kaydet(self, a, b, skor, olaylar):
        cur = self.db.execute("INSERT INTO maclar (a,b,skor_a,skor_b,tarih,olaylar) VALUES (?,?,?,?,?,?)",
                              (a, b, skor.get(a, 0), skor.get(b, 0), time.time(),
                               json.dumps(olaylar, ensure_ascii=False)))
        self.db.commit()
        return cur.lastrowid

    def son_maclar(self, n=30):
        rows = self.db.execute("SELECT id,a,b,skor_a,skor_b,tarih FROM maclar ORDER BY id DESC LIMIT ?",
                               (n,)).fetchall()
        return [dict(zip(("id", "a", "b", "skor_a", "skor_b", "tarih"), r)) for r in rows]

    def mac(self, mid):
        row = self.db.execute("SELECT a,b,skor_a,skor_b,tarih,olaylar FROM maclar WHERE id=?",
                              (mid,)).fetchone()
        if not row:
            return None
        return {"id": mid, "a": row[0], "b": row[1], "skor_a": row[2], "skor_b": row[3],
                "tarih": row[4], "olaylar": json.loads(row[5])}


# ---------------------------------------------------------- internetteki bot
class RemoteBot:
    """bagla.py ile baglanan bot. quiz.mac'in istedigi arayuzu saglar."""

    def __init__(self, name, ws):
        self.name = name
        self.ws = ws
        self.inbox = asyncio.Queue(maxsize=200)
        self.rtts = collections.deque(maxlen=30)
        self.pings = {}
        self.busy = False
        self.davetler = {}

    @property
    def latency(self):
        # En dusuk tur-donus suresi: istek gidis + cevap donus. Sureden dusulur ki
        # uzaktaki bot ag yuzunden kaybetmesin.
        return min(self.rtts) if self.rtts else 0.0

    async def send(self, msg):
        await self.raw({"k": "bot", "m": msg})

    async def raw(self, obj):
        if not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(obj, ensure_ascii=False))
            except ConnectionError:
                pass


# ------------------------------------------------------------------- uygulama
class Site:
    def __init__(self, store, db):
        self.store = store
        self.db = db
        self.online = {}       # ad -> RemoteBot
        self.viewers = set()   # tarayici websocketleri
        self.canli = {}        # canli mac no -> {"a","b","skor","olaylar"}
        self.sayac = itertools.count(1)

    # --- yayin
    def lobi(self):
        return {"tip": "lobi",
                "botlar": sorted(({"ad": b.name, "mesgul": b.busy,
                                   "ping": round(b.latency * 1000, 1)}
                                  for b in self.online.values()), key=lambda x: x["ad"].lower()),
                "canli": [{"no": no, "a": m["a"], "b": m["b"], "skor": m["skor"]}
                          for no, m in self.canli.items()]}

    async def yayinla(self, obj):
        data = json.dumps(obj, ensure_ascii=False)
        for ws in list(self.viewers):
            try:
                await ws.send_str(data)
            except ConnectionError:
                self.viewers.discard(ws)

    def lobi_guncelle(self):
        asyncio.ensure_future(self.yayinla(self.lobi()))

    # --- http
    async def index(self, req):
        return web.FileResponse(os.path.join(HERE, "static", "index.html"))

    async def api_kayit(self, req):
        body = await req.json()
        ad = (body.get("ad") or "").strip()
        if not NAME_RE.match(ad):
            return web.json_response({"hata": "Isim 3-20 karakter: harf, rakam, _ veya -"}, status=400)
        tok = self.store.kayit(ad)
        if not tok:
            return web.json_response({"hata": "Bu isim alinmis"}, status=409)
        return web.json_response({"ad": ad, "token": tok})

    def auth(self, req):
        h = req.headers.get("Authorization", "")
        return self.store.kim(h.removeprefix("Bearer ").strip())

    async def api_ben(self, req):
        ad = self.auth(req)
        if not ad:
            return web.json_response({"hata": "Gecersiz token"}, status=401)
        return web.json_response({"ad": ad})

    async def api_davet(self, req):
        ben = self.auth(req)
        if not ben:
            return web.json_response({"hata": "Once giris yap"}, status=401)
        body = await req.json()
        rakip = body.get("rakip")
        tur = max(1, min(MAX_TUR, int(body.get("tur") or 10)))
        a, b = self.online.get(ben), self.online.get(rakip)
        if not a:
            return web.json_response({"hata": "Senin botun bagli degil (bagla.py calisiyor mu?)"}, status=409)
        if not b or b is a:
            return web.json_response({"hata": "Rakip bot cevrimici degil"}, status=409)
        if a.busy or b.busy:
            return web.json_response({"hata": "Botlardan biri su an macta"}, status=409)

        # Davet: rakibin bagla.py'si kabul etmeli (varsayilan otomatik kabul)
        a.busy = b.busy = True
        self.lobi_guncelle()
        did = secrets.token_hex(4)
        fut = asyncio.get_running_loop().create_future()
        b.davetler[did] = fut
        await b.raw({"k": "davet", "id": did, "kimden": ben, "tur": tur})
        try:
            ok = await asyncio.wait_for(fut, DAVET_SURE)
        except asyncio.TimeoutError:
            ok = False
        finally:
            b.davetler.pop(did, None)
        if not ok:
            a.busy = b.busy = False
            self.lobi_guncelle()
            return web.json_response({"hata": f"{rakip} daveti kabul etmedi"}, status=409)

        no = next(self.sayac)
        asyncio.ensure_future(self.mac_oynat(no, a, b, tur))
        return web.json_response({"no": no})

    async def mac_oynat(self, no, a, b, tur):
        kayit = {"a": a.name, "b": b.name, "skor": {a.name: 0, b.name: 0}, "olaylar": []}
        self.canli[no] = kayit
        self.lobi_guncelle()

        def on_event(ev):
            ev["t"] = round(time.time(), 3)
            kayit["olaylar"].append(ev)
            if "skor" in ev:
                kayit["skor"] = ev["skor"]
            asyncio.ensure_future(self.yayinla({"tip": "mac", "no": no, "ev": ev}))
            if ev["ev"] in ("tur_sonu", "bitti"):
                self.lobi_guncelle()

        try:
            await play_match(self.db, [a, b], tur, on_event=on_event)
            mid = self.store.mac_kaydet(a.name, b.name, kayit["skor"], kayit["olaylar"])
            await self.yayinla({"tip": "mac_kaydedildi", "no": no, "id": mid})
        except Exception as e:  # bir mac hatasi sunucuyu dusurmesin
            print("mac hatasi:", repr(e))
        finally:
            a.busy = b.busy = False
            self.canli.pop(no, None)
            self.lobi_guncelle()

    async def api_maclar(self, req):
        return web.json_response(self.store.son_maclar())

    async def api_mac(self, req):
        m = self.store.mac(int(req.match_info["id"]))
        return web.json_response(m) if m else web.json_response({"hata": "yok"}, status=404)

    # --- websocket: tarayici
    async def ws_izle(self, req):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(req)
        self.viewers.add(ws)
        await ws.send_str(json.dumps(self.lobi(), ensure_ascii=False))
        # Gec katilan izleyici canli maclari bastan gorsun
        for no, m in list(self.canli.items()):
            await ws.send_str(json.dumps({"tip": "gecmis", "no": no, "olaylar": m["olaylar"]},
                                         ensure_ascii=False))
        try:
            async for _ in ws:
                pass
        finally:
            self.viewers.discard(ws)
        return ws

    # --- websocket: bot (bagla.py)
    async def ws_bot(self, req):
        ad = self.auth(req)
        if not ad:
            return web.json_response({"hata": "Gecersiz token"}, status=401)
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=2**20)
        await ws.prepare(req)
        if ad in self.online:  # ayni bot ikinci kez baglanirsa eskisini kapat
            await self.online[ad].ws.close()
        bot = RemoteBot(ad, ws)
        self.online[ad] = bot
        self.lobi_guncelle()
        await bot.raw({"k": "hosgeldin", "ad": ad})
        pinger = asyncio.ensure_future(self.ping_dongusu(bot))
        try:
            async for msg in ws:
                t = time.perf_counter()  # varis zamani: hiz olcumu icin ilk is
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                k = data.get("k")
                if k == "bot":
                    if not bot.inbox.full():
                        bot.inbox.put_nowait((t, data.get("m")))
                elif k == "pong":
                    sent = bot.pings.pop(data.get("id"), None)
                    if sent:
                        bot.rtts.append(t - sent)
                elif k == "kabul":
                    fut = bot.davetler.get(data.get("id"))
                    if fut and not fut.done():
                        fut.set_result(bool(data.get("ok")))
        finally:
            pinger.cancel()
            if self.online.get(ad) is bot:
                del self.online[ad]
            self.lobi_guncelle()
        return ws

    async def ping_dongusu(self, bot):
        n = 0
        while not bot.ws.closed:
            n += 1
            bot.pings[n] = time.perf_counter()
            await bot.raw({"k": "ping", "id": n})
            bot.pings = {k: v for k, v in bot.pings.items() if k > n - 10}
            await asyncio.sleep(0.5 if n < 10 else 3)
            if n % 10 == 0:
                self.lobi_guncelle()


def make_app():
    store = Store(os.environ.get("DB_YOLU", os.path.join(HERE, "site.db")))
    print("Futbol veritabani yukleniyor...", flush=True)
    site = Site(store, FootballDB())
    app = web.Application()
    app.add_routes([
        web.get("/", site.index),
        web.post("/api/kayit", site.api_kayit),
        web.get("/api/ben", site.api_ben),
        web.post("/api/davet", site.api_davet),
        web.get("/api/maclar", site.api_maclar),
        web.get("/api/mac/{id}", site.api_mac),
        web.get("/ws/izle", site.ws_izle),
        web.get("/ws/bot", site.ws_bot),
        web.static("/static", os.path.join(HERE, "static")),
    ])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=int(os.environ.get("PORT", 8080)))
