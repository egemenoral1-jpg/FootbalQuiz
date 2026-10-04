"""Ortak veritabani: takim/oyuncu isimlerini cozer, ortak oyunculari bulur.

Hem hakem (arena.py) hem de botlar bunu kullanabilir.
"""
import gzip
import json
import os
import re
import unicodedata

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "football.json.gz")

_TR = str.maketrans("ıİşŞğĞçÇöÖüÜâÂîÎûÛ", "iIsSgGcCoOuUaAiIuU")
# Takim isimlerinde anlam tasimayan ekler: "Galatasaray S.K." == "Galatasaray"
_TEAM_NOISE = {"fc", "sk", "cf", "afc", "ac", "as", "jk", "fk", "sc", "cfc", "ssc", "sv",
               "club", "de", "futbol", "football", "kulubu", "spor kulubu", "as", "a s"}

# Wikidata'da olmayan yaygin takma adlar: takma ad -> veritabaninda cozulen isim
MANUAL_TEAM_ALIASES = {
    "gs": "Galatasaray", "cimbom": "Galatasaray",
    "fb": "Fenerbahçe", "fener": "Fenerbahçe",
    "bjk": "Beşiktaş", "kartal": "Beşiktaş",
    "ts": "Trabzonspor", "trabzon": "Trabzonspor",
    "psg": "Paris Saint-Germain", "paris": "Paris Saint-Germain",
    "barca": "FC Barcelona", "barcelona": "FC Barcelona",
    "real": "Real Madrid", "man utd": "Manchester United", "man united": "Manchester United",
    "marsilya": "Olympique de Marseille", "marseille": "Olympique de Marseille",
    "om": "Olympique de Marseille", "schalke": "FC Schalke 04",
    "sporting": "Sporting CP", "sporting lizbon": "Sporting CP", "juve": "Juventus",
    "bayern munih": "FC Bayern Münih", "bayern munchen": "FC Bayern Münih",
    "atletico": "Atlético Madrid", "inter milan": "FC Internazionale Milano",
    "liverpool": "Liverpool FC", "arsenal": "Arsenal FC", "chelsea": "Chelsea FC",
}
_NATIONAL = re.compile(r"^(.*?) (?:erkek )?mill?i futbol takimi$|"
                       r"^(.*?) (?:men s )?national (?:association )?football team$")


def norm(s):
    """'Fenerbahçe S.K.' -> 'fenerbahce s k'"""
    s = s.translate(_TR).casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def team_keys(name):
    """Bir takim isminden aranabilir anahtarlar (en ozelden en genele)."""
    n = norm(name)
    keys = [n]
    m = _NATIONAL.match(n)
    if m:  # "Türkiye millî futbol takımı" -> "turkiye"
        keys.append(m.group(1) or m.group(2))
    words = [w for w in n.split() if w not in _TEAM_NOISE]
    # "s k" gibi tek harfli kisaltma parcalarini da at
    words = [w for w in words if len(w) > 1 or w.isdigit()]
    if words:
        keys.append(" ".join(words))
    return keys


class FootballDB:
    def __init__(self, path=DB_PATH):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        # Eski veri dosyalarinda ismi bos kalan kayitlari onar
        for table in (raw["players"], raw["teams"]):
            for k, v in table.items():
                if not v[0]:
                    v[0] = v[2][0] if v[2] else k
        self.players = raw["players"]          # pid -> [isim, unlu_lik, aliases]
        self.teams = raw["teams"]              # tid -> [isim, unlu_lik, aliases]
        self.links = {t: frozenset(ps) for t, ps in raw["links"].items()}

        # isim anahtari -> takim. Cakisirsa en cok oyuncusu olan kazanir
        # (boylece "Galatasaray" -> futbol takimi, basketbol degil; A takim, U21 degil)
        best = {}
        for tid, (name, _fame, aliases) in self.teams.items():
            size = len(self.links.get(tid, ()))
            for nm in [name, *aliases]:
                for k in team_keys(nm):
                    if k and (k not in best or size > best[k][0]):
                        best[k] = (size, tid)
        self.team_index = {k: tid for k, (_, tid) in best.items()}
        for k, target in MANUAL_TEAM_ALIASES.items():
            tid = self.resolve_team(target)
            if tid:
                self.team_index[k] = tid

        # Oyuncu isim anahtarlari (tam isim + takma adlar)
        self.player_keys = {pid: {norm(n) for n in [v[0], *v[2]]}
                            for pid, v in self.players.items()}

    # --- takimlar ---
    def resolve_team(self, text):
        if not text:
            return None
        for k in team_keys(text):
            if k in self.team_index:
                return self.team_index[k]
        return None

    def team_name(self, tid):
        return self.teams[tid][0]

    # --- oyuncular ---
    def common_players(self, t1, t2):
        a, b = self.links.get(t1, frozenset()), self.links.get(t2, frozenset())
        return a & b if t1 != t2 else a

    def player_name(self, pid):
        return self.players[pid][0]

    def fame(self, pid):
        return self.players[pid][1]

    def match_player(self, answer, candidates):
        """Cevabi aday oyuncularla eslestirir. Tam isim/takma ad ya da
        adaylar icinde tek olan soyad kabul edilir. Bulamazsa None."""
        a = norm(answer or "")
        if not a:
            return None
        surname_hits = []
        for pid in candidates:
            keys = self.player_keys[pid]
            if a in keys:
                return pid
            if any(k.split()[-1] == a for k in keys if k):
                surname_hits.append(pid)
        return surname_hits[0] if len(surname_hits) == 1 else None
