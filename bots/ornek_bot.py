"""Arkadaslar icin sablon bot. Kopyala, adini degistir, gelistir!

    copy bots\\ornek_bot.py bots\\ahmet_bot.py

Bu bot bilerek basit: elle yazilmis kucuk bir liste kullanir.
Protokol: PROTOKOL.md
"""
import json
import random
import sys

# Kendi bilgin: takim -> o takimda oynamis oyuncular
BILGI = {
    "Galatasaray": ["Hakan Şükür", "Gheorghe Hagi", "Arda Turan", "Wesley Sneijder", "Didier Drogba"],
    "Fenerbahçe": ["Alex de Souza", "Roberto Carlos", "Robin van Persie", "Hakan Şükür", "Arda Turan"],
    "Beşiktaş": ["Ricardo Quaresma", "Pepe", "Arda Turan", "Wesley Sneijder"],
    "Real Madrid": ["Roberto Carlos", "Pepe", "Wesley Sneijder", "Arda Guler"],
    "Barcelona": ["Arda Turan", "Gheorghe Hagi"],
}


def gonder(mesaj):
    print(json.dumps(mesaj, ensure_ascii=False), flush=True)


def cevapla(takim1, takim2, kullanilan):
    a = set(BILGI.get(takim1, []))
    b = set(BILGI.get(takim2, []))
    ortak = [o for o in a & b if o not in kullanilan]
    return ortak[0] if ortak else None


for satir in sys.stdin:
    m = json.loads(satir)
    if m["type"] == "hello":
        gonder({"ready": True})
    elif m["type"] == "pick":
        gonder({"team": random.choice(list(BILGI))})
    elif m["type"] == "question":
        t1, t2 = m["teams"]
        gonder({"player": cevapla(t1, t2, m["used"])})
    elif m["type"] == "end":
        break
