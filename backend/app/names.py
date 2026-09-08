"""Сопоставление имён людей, написанных кириллицей и латиницей (v1.1.1).

Имя пользователя при первом входе берётся из Microsoft на латинице («Aidos Bekov»), а голосом или текстом
Claude получает «Айдос». Обычное сравнение строк их не связывает. Здесь оба написания приводятся к одному
«фонетическому ключу»: кириллица транслитерируется, а у латиницы схлопываются варианты транслитерации
(zh/j/dzh → j, kh/h → h, y/i/iy/ii → i, ye → e, x → ks, удвоения убираются и т.п.).

    key("Жанибек") == key("Zhanibek") == key("Janibek") == key("Dzhanibek")
    key("Айдос") == key("Aidos") == key("Aydos")

Ключ — не транслитерация для показа человеку, а внутренний вид только для сравнения.
"""
import re

# кириллица (русская + казахская) → черновая латиница; й/ы → i, ж → j, х → h, ц → c, ч → 4, ш/щ → 6 (спецтокены,
# чтобы «ч» и «ц»+«х» не путались), ь/ъ пропадают
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j", "з": "z", "и": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "c", "ч": "4", "ш": "6", "щ": "6", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "u", "я": "a",
    "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u", "һ": "h", "і": "i",
}

# латиница → канонический вид; порядок важен (длинные сочетания раньше коротких)
_LAT_RULES = [
    ("shch", "6"), ("sch", "6"), ("sh", "6"), ("ch", "4"), ("tch", "4"),
    ("dzh", "j"), ("zh", "j"), ("dj", "j"),
    ("kh", "h"), ("gh", "g"), ("th", "t"), ("ph", "f"), ("ck", "k"),
    ("ts", "c"), ("tz", "c"),
    ("ya", "a"), ("ia", "a"), ("yu", "u"), ("iu", "u"), ("yo", "o"), ("io", "o"), ("ye", "e"), ("je", "e"),
    ("iy", "i"), ("yi", "i"), ("ii", "i"), ("y", "i"),
    ("x", "ks"), ("w", "v"), ("q", "k"),
]

_WORD_SPLIT = re.compile(r"[^\w]+", re.UNICODE)


def _fold(word: str) -> str:
    out = []
    for ch in word:
        out.append(_CYR.get(ch, ch) if ch in _CYR else ch)
    s = "".join(out)
    for a, b in _LAT_RULES:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z46]", "", s)          # только латиница и спецтокены ч/ш
    s = re.sub(r"(.)\1+", r"\1", s)         # удвоения: Abilkhanov ≈ Abilhannov
    return s


def key_words(s: str) -> list[str]:
    """Фонетические ключи слов имени (пустые слова выброшены)."""
    return [k for k in (_fold(w) for w in _WORD_SPLIT.split(str(s or "").lower())) if k]


def key(s: str) -> str:
    return " ".join(key_words(s))


def email_words(email: str | None) -> list[str]:
    """Слова из части почты до @: «zh.mubinov» → [«zh», «mubinov»] — фамилия в почте помогает найти человека,
    если в справочнике он записан иначе."""
    if not email or "@" not in email:
        return []
    return key_words(email.split("@", 1)[0].replace(".", " ").replace("_", " ").replace("-", " "))


def word_hit(qk: str, nk: str) -> bool:
    """Слово запроса ≈ слово имени: равны, либо одно — начало другого (≥ 4 символов, чтобы «ali» не ловило всех)."""
    if qk == nk:
        return True
    short, long_ = (qk, nk) if len(qk) <= len(nk) else (nk, qk)
    return len(short) >= 4 and long_.startswith(short)


def person_matches(query: str, name: str, email: str | None = None) -> bool:
    """Каждое слово запроса находится среди слов имени (или почты). «Айдос» → «Aidos Bekov» ✓,
    «Беков Айдос» → «Aidos Bekov» ✓, «Айдар» → «Aidos Bekov» ✗."""
    qws = key_words(query)
    if not qws:
        return False
    nws = key_words(name) + email_words(email)
    return all(any(word_hit(q, n) for n in nws) for q in qws)
