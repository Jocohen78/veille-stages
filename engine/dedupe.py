"""Dédoublonnage : reconnaître la même offre publiée plusieurs fois (autre source,
republication, mise à jour)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .classify import norm

NOISE = [
    r"\(?\b[hfmxwd]\s*/\s*[hfmxwd](\s*/\s*[hfmxwd])?\b\)?",  # H/F, M/F/D, F/H/X
    r"\b\d{1,2}\s*(mois|months?)\b",
    r"\b(stage|stagiaire|internship|internships|intern|programme|program|analyst|analyste|trainee|praktikum|tirocinio|de|du|des|la|le|les|en|"
    r"et|and|the|of|for|in|au|aux|a|pour|fin|d|etudes|end|studies|month|mois|six|6|h|f|x|-)\b",
]
CITY_WORDS = r"\b(paris|london|londres|new york|nyc|chicago|toronto|montreal|milan|milano|zurich|geneva|geneve|" \
             r"luxembourg|amsterdam|lyon|lille|france|uk|united kingdom|usa|us|canada|switzerland|suisse|italy|italie)\b"


def title_key(title: str) -> str:
    t = norm(title)
    t = re.sub(CITY_WORDS, " ", t)
    for p in NOISE:
        t = re.sub(p, " ", t)
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def token_set_ratio(a: str, b: str) -> float:
    """Similarité 0-100 insensible à l'ordre des mots (équivalent rapidfuzz.token_set_ratio)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = " ".join(sorted(ta & tb))
    da = " ".join(sorted(ta - tb))
    db = " ".join(sorted(tb - ta))
    s1 = (inter + " " + da).strip()
    s2 = (inter + " " + db).strip()
    scores = [_ratio(s1, s2)]
    if inter:
        scores += [_ratio(inter, s1), _ratio(inter, s2)]
        # Si l'un des titres est entièrement contenu dans l'autre, on exige au moins 2 mots communs
        if (not da or not db) and len(ta & tb) < 2:
            scores = [_ratio(s1, s2)]
    return 100 * max(scores)


def shingles(text: str, k: int = 5) -> set[str]:
    w = norm(text).split()
    return {" ".join(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def description_similarity(a: str | None, b: str | None) -> float | None:
    if not a or not b or len(a) < 300 or len(b) < 300:
        return None
    sa, sb = shingles(a[:6000]), shingles(b[:6000])
    if not sa or not sb:
        return None
    return len(sa & sb) / len(sa | sb)


def description_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha1(norm(text)[:8000].encode()).hexdigest()


def same_place(a: list | None, b: list | None) -> bool:
    if not a or not b:
        return True  # lieu inconnu d'un côté : on ne bloque pas
    return bool(set(a) & set(b))


def find_group(candidate: dict, offers: list[dict], threshold: float) -> dict | None:
    """Cherche une offre existante (même entreprise, titre proche, même ville) ; renvoie la meilleure."""
    best, best_score = None, 0.0
    ckey = candidate["title_norm"]
    for o in offers:
        if o.get("company") != candidate["company"]:
            continue
        if not same_place(o.get("cities"), candidate.get("cities")):
            continue
        s = token_set_ratio(ckey, o.get("title_norm") or "")
        if s < threshold:
            dsim = description_similarity(candidate.get("description"), o.get("description"))
            if dsim is not None and dsim >= 0.85 and s >= 60:
                s = threshold  # même texte d'annonce, titre reformulé
        if s >= threshold and s > best_score + 0.01:
            best, best_score = o, s
        elif s >= threshold and abs(s - best_score) <= 0.01 and best is not None:
            # À égalité, préférer l'offre principale
            if o.get("is_primary") and not best.get("is_primary"):
                best = o
    return best


def days_between(a: str | None, b: datetime) -> float:
    if not a:
        return 0.0
    da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
    if da.tzinfo is None:
        da = da.replace(tzinfo=timezone.utc)
    return (b - da).total_seconds() / 86400
