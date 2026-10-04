"""Bilgisayarindaki botu FootbalQuiz sitesine baglar.

  python bagla.py bots/claude_bot.py --token TOKENIN
  python bagla.py "node bots/benim.js" --token TOKENIN --sor

Token'i sitede "Botunu kaydet" diyerek alirsin. Token'i FQ_TOKEN ortam
degiskenine de koyabilirsin. Bot kodun kendi bilgisayarinda calisir, siteye
sadece cevaplari gider.

--sor   : gelen davetleri kabul etmeden once sana sorar (yoksa otomatik kabul)

Hizli mod: Python botun `Bot` adinda, `handle(mesaj) -> cevap ya da None`
metodu olan bir sinif tanimliyorsa (bkz. bots/claude_bot.py) bot ayri surec
acilmadan bagla.py'nin icinde calisir: cevap boru atlamadan aninda siteye gider.
Istemezsen --ayri-surec ekle.
"""
import argparse
import asyncio
import importlib.util
import json
import os
import sys

import aiohttp

from quiz.yerel import LocalBot

VARSAYILAN_SUNUCU = os.environ.get("FQ_SUNUCU", "http://localhost:8080")


def bot_yukle(spec):
    """Dosya `Bot.handle` tanimliyorsa botu bu surecte olustur, yoksa None."""
    if not spec.endswith(".py") or not os.path.isfile(spec):
        return None
    sp = importlib.util.spec_from_file_location("kullanici_botu", spec)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    cls = getattr(mod, "Bot", None)
    if cls is None or not callable(getattr(cls, "handle", None)):
        return None
    return cls()


class Relay:
    def __init__(self, spec, ws, sor, inproc=None):
        self.spec, self.ws, self.sor = spec, ws, sor
        self.inproc = inproc
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
            try:
                await self.ws.send_str(json.dumps({"k": "bot", "m": msg}, ensure_ascii=False))
            except ConnectionError:
                return

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
            if self.inproc:
                # Sicak yol: once cevapla, sonra her sey
                reply = self.inproc.handle(m)
                if reply is not None:
                    await self.ws.send_str(json.dumps({"k": "bot", "m": reply}, ensure_ascii=False))
            elif m.get("type") == "hello":
                await self.bot_baslat()
            if self.bot:
                await self.bot.send(m)
            if m.get("type") == "hello":
                print(f"Mac basladi: {m['you']} vs {m['opponent']}", flush=True)
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
    ap.add_argument("--ayri-surec", action="store_true", help="hizli modu kapat")
    args = ap.parse_args()
    if not args.token:
        ap.error("--token gerekli (sitede 'Botunu kaydet' ile al)")

    inproc = None if args.ayri_surec else bot_yukle(args.bot)
    print("Hizli mod: bot bu surecte calisiyor." if inproc
          else "Bot her macta ayri surec olarak baslatilacak.", flush=True)

    url = args.sunucu.rstrip("/").replace("http", "ws", 1) + "/ws/bot"
    headers = {"Authorization": f"Bearer {args.token}"}
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(url, headers=headers, heartbeat=25, compress=0) as ws:
                    relay = Relay(args.bot, ws, args.sor, inproc)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await relay.siteden(json.loads(msg.data))
                    if relay.bot:
                        await relay.bot.close()
                    if ws.close_code == 4009:
                        sys.exit("Bu isimde baska bir bot zaten bagli. Sitede farkli isimle kayit ol.")
                    if ws.close_code == 4010:
                        sys.exit("Bu bot baska bir pencereden/bilgisayardan baglandi, bu baglanti kapandi.")
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
