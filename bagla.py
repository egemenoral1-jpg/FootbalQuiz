"""Bilgisayarindaki botu FootbalQuiz sitesine baglar.

  python bagla.py bots/claude_bot.py --token TOKENIN
  python bagla.py "node bots/benim.js" --token TOKENIN --sor

Token'i sitede "Botunu kaydet" diyerek alirsin. Token'i FQ_TOKEN ortam
degiskenine de koyabilirsin. Bot kodun kendi bilgisayarinda calisir, siteye
sadece cevaplari gider.

--sor   : gelen davetleri kabul etmeden once sana sorar (yoksa otomatik kabul)
"""
import argparse
import asyncio
import json
import os
import sys

import aiohttp

from quiz.yerel import LocalBot

VARSAYILAN_SUNUCU = os.environ.get("FQ_SUNUCU", "http://localhost:8080")


class Relay:
    def __init__(self, spec, ws, sor):
        self.spec, self.ws, self.sor = spec, ws, sor
        self.bot = None
        self.pump = None

    async def bot_baslat(self):
        if self.bot and self.bot.proc.returncode is None:
            return
        if self.pump:
            self.pump.cancel()
        self.bot = await LocalBot(self.spec).start()
        self.pump = asyncio.ensure_future(self.bottan_siteye(self.bot))

    async def bottan_siteye(self, bot):
        # Botun her cevabini bekletmeden siteye ilet
        while True:
            _, msg = await bot.inbox.get()
            await self.ws.send_str(json.dumps({"k": "bot", "m": msg}, ensure_ascii=False))

    async def davet(self, data):
        ok = True
        if self.sor:
            cevap = await asyncio.to_thread(
                input, f"\n{data['kimden']} seni {data['tur']} turluk maca davet ediyor. Kabul? [E/h] ")
            ok = cevap.strip().lower() not in ("h", "hayir", "n", "no")
        else:
            print(f"Davet: {data['kimden']} ({data['tur']} tur) -> kabul edildi", flush=True)
        await self.ws.send_str(json.dumps({"k": "kabul", "id": data["id"], "ok": ok}))

    async def siteden(self, data):
        k = data.get("k")
        if k == "ping":  # gecikme olcumu: hemen cevapla
            await self.ws.send_str(json.dumps({"k": "pong", "id": data["id"]}))
        elif k == "bot":
            m = data["m"]
            if m.get("type") == "hello":
                await self.bot_baslat()
                print(f"Mac basladi: {m['you']} vs {m['opponent']}", flush=True)
            if self.bot:
                await self.bot.send(m)
            if m.get("type") == "result" and m.get("winner"):
                print(f"  Tur {m['round']}: +1 {m['winner']} ({m.get('player')})", flush=True)
            elif m.get("type") == "end":
                print("Mac bitti.", flush=True)
                if self.bot:
                    await self.bot.close()
        elif k == "davet":
            asyncio.ensure_future(self.davet(data))
        elif k == "hosgeldin":
            print(f"Baglandi! Botun sitede '{data['ad']}' olarak cevrimici. "
                  "Davet bekleniyor... (Ctrl+C ile cik)", flush=True)


async def main():
    ap = argparse.ArgumentParser(description="Botunu FootbalQuiz sitesine bagla")
    ap.add_argument("bot", help="bot dosyasi ya da komutu (orn: bots/claude_bot.py)")
    ap.add_argument("--token", default=os.environ.get("FQ_TOKEN"))
    ap.add_argument("--sunucu", default=VARSAYILAN_SUNUCU)
    ap.add_argument("--sor", action="store_true", help="davetleri kabul etmeden once sor")
    args = ap.parse_args()
    if not args.token:
        ap.error("--token gerekli (sitede 'Botunu kaydet' ile al)")

    url = args.sunucu.rstrip("/").replace("http", "ws", 1) + "/ws/bot"
    headers = {"Authorization": f"Bearer {args.token}"}
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(url, headers=headers, heartbeat=25) as ws:
                    relay = Relay(args.bot, ws, args.sor)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await relay.siteden(json.loads(msg.data))
                    if relay.bot:
                        await relay.bot.close()
            print("Baglanti koptu, 3 sn sonra tekrar deneniyor...", flush=True)
        except aiohttp.WSServerHandshakeError as e:
            if e.status == 401:
                sys.exit("Token gecersiz. Sitede botunu kaydedip yeni token al.")
            print(f"Sunucu hatasi ({e.status}), 3 sn sonra tekrar...", flush=True)
        except (aiohttp.ClientError, OSError) as e:
            print(f"Sunucuya ulasilamadi ({e}), 3 sn sonra tekrar...", flush=True)
        await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
