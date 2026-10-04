# FootbalQuiz — Bot Protokolü

## Oyun
1. Ekranda **3… 2… 1…** sayılır.
2. İki bot **aynı anda** birer takım söyler.
3. İki takımda da oynamış bir futbolcuyu **ilk söyleyen** 1 puan alır.
4. Doğru cevap verilen oyuncu o maçta bir daha kullanılamaz.
5. Geçersiz (tanınmayan) takım söyleyen bot o turu kaybeder; rakip 1 puan alır.
6. İki takımın ortak oyuncusu yoksa tur geçersiz sayılır.

Hakem `data/football.json.gz` veritabanını (Wikidata) kullanır. Oyuncu adında
büyük/küçük harf ve Türkçe karakter fark etmez (`hakan sukur` = `Hakan Şükür`).
Soyadı, iki takımın ortak oyuncuları arasında tek kişiye denk geliyorsa sadece
soyadı da kabul edilir.

## Bot nasıl konuşur
Bot bir program olur. Hakem botun **stdin**'ine her satıra bir JSON mesaj yazar,
bot da **stdout**'a her satıra bir JSON cevap yazar. Her yazdığından sonra
**flush** etmeyi unutma. JSON olmayan satırları hakem yok sayar (debug için
`stderr` kullan).

| Hakem → Bot | Bot → Hakem | Süre |
|---|---|---|
| `{"type":"hello","you":"ahmet_bot","opponent":"claude_bot","rounds":10}` | `{"ready":true}` | 120 sn (veri yükle) |
| `{"type":"pick","round":1}` | `{"team":"Galatasaray"}` | 2 sn |
| `{"type":"question","round":1,"teams":["Galatasaray","Fenerbahçe"],"used":["Hakan Şükür"]}` | `{"player":"Arda Turan"}` ya da `{"player":null}` | 10 sn |
| `{"type":"result","round":1,"winner":"claude_bot","player":"Arda Turan"}` | (cevap yok) | |
| `{"type":"end"}` | (çık) | |

`teams` içindeki isimler botların **söylediği gibi** gelir. Takım adını çözmek
de botun işi. Her soruya **tek** cevap verilir. Hız, hakemin mesajı yolladığı an
ile cevap satırının geldiği an arasında ölçülür.

## Çalıştırma
```bash
python arena.py bots/claude_bot.py bots/ornek_bot.py
python arena.py bots/claude_bot.py "node bots/benim_botum.js" --rounds 20
python arena.py --turnuva
```
`.py` dosyaları `python` ile çalışır; diğer diller için komutu tırnak içinde ver.

## Hızlı mod (Python botlar için, isteğe bağlı)
Bot dosyan `handle(mesaj)` metodu olan bir `Bot` sınıfı tanımlarsa `bagla.py`
botu ayrı süreç açmadan kendi içinde çalıştırır. Cevap boru/süreç atlaması
olmadan siteye gider. Ölçümde site üzerinden medyan süre ~1,5 ms'den ~0,9 ms'e
indi. `handle` cevap dict'i ya da cevap yoksa `None` döndürür. Örnek:
`bots/claude_bot.py`. Kapatmak için: `bagla.py ... --ayri-surec`.
