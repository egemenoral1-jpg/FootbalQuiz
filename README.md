# FootbalQuiz ⚽ — Bot Kapışması

3… 2… 1… iki bot aynı anda birer takım söyler. **İki takımda da oynamış** bir
futbolcuyu ilk söyleyen puanı alır.

```bash
python arena.py bots/claude_bot.py bots/ornek_bot.py
```

## Klasörler
| | |
|---|---|
| `dene.py` | Botu elle seçtiğin takımlarla dener, cevabı ve süreyi gösterir |
| `arena.py` | Hakem: geri sayım, takımları alır, süreyi ölçer, puanlar |
| `quiz/db.py` | Ortak veritabanı: takım/oyuncu isim çözme, ortak oyuncu bulma |
| `data/football.json.gz` | ~195 bin futbolcu, ~23 bin takım (Wikidata) |
| `data/build_db.py` | Veritabanını Wikidata'dan yeniden indirir (~15 dk) |
| `bots/claude_bot.py` | Bizim bot |
| `bots/ornek_bot.py` | Arkadaşlar için şablon |
| `PROTOKOL.md` | Kurallar ve bot ↔ hakem mesajları |

## Kendi botunu yaz
1. `bots/ornek_bot.py` dosyasını `bots/<adın>_bot.py` olarak kopyala.
2. `PROTOKOL.md`'yi oku. Bot stdin'den JSON okur, stdout'a JSON yazar; yani
   istediğin dilde yazabilirsin.
3. Tek soruyla dene: `python dene.py bots/<adın>_bot.py Galatasaray Fenerbahçe`
   (ya da sadece `python dene.py bots/<adın>_bot.py` yazıp takımları kendin gir)
4. Maç yap: `python arena.py bots/<adın>_bot.py bots/claude_bot.py`
5. Herkes hazır olunca: `python arena.py --turnuva`

Ayarlar: `--rounds 20` (tur sayısı), `--hizli` (geri sayımı atla), `--sure 5`
(cevap süresi, saniye).
