"""Classification d'une offre : entreprise, ville, type de poste, desk,
dates de début, durée, compatibilité avec la période recherchée."""
from __future__ import annotations

import re
import unicodedata
from datetime import date

# ----------------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------------

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str | None) -> str:
    s = strip_accents((s or "").lower())
    s = re.sub(r"[’'`´]", " ", s)
    s = re.sub(r"[^a-z0-9&+./ -]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(" ")
    except Exception:  # pragma: no cover
        text = re.sub(r"<[^>]+>", " ", html)
    import html as htmllib
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def has_word(text: str, word: str) -> bool:
    """Recherche d'un mot/expression avec frontières de mots (texte déjà normalisé)."""
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


# ----------------------------------------------------------------------------
# Entreprises
# ----------------------------------------------------------------------------

class CompanyIndex:
    def __init__(self, companies: list[dict]):
        self.entries = []
        for c in companies:
            aliases = [norm(a) for a in c.get("alias", [])] + [norm(c["nom"])]
            # Les alias longs d'abord (plus spécifiques)
            for a in sorted(set(aliases), key=len, reverse=True):
                self.entries.append((a, c))
        self.entries.sort(key=lambda e: len(e[0]), reverse=True)
        self.by_name = {c["nom"]: c for c in companies}

    def match(self, raw_company: str | None) -> dict | None:
        n = norm(raw_company)
        if not n:
            return None
        for alias, c in self.entries:
            if len(alias) <= 4:
                # Alias courts (ING, UBS, TD, BP, SIG...) : le nom doit commencer par l'alias
                # ou lui être égal, pour éviter "ing" dans "trading".
                if n == alias or n.startswith(alias + " "):
                    return c
            elif has_word(n, alias):
                return c
        return None


# ----------------------------------------------------------------------------
# Villes
# ----------------------------------------------------------------------------

CITY_PATTERNS = {
    "Paris": ["paris", "la defense", "puteaux", "courbevoie", "nanterre", "montrouge", "saint-denis",
              "saint denis", "neuilly", "levallois", "boulogne-billancourt", "issy-les-moulineaux",
              "ile-de-france", "ile de france", "guyancourt", "charenton", "fontenay-sous-bois", "val de fontenay"],
    "Lyon": ["lyon", "villeurbanne"],
    "Lille": ["lille", "villeneuve d ascq", "marcq-en-baroeul"],
    "Montréal": ["montreal"],
    "Toronto": ["toronto"],
    "Londres": ["london", "londres", "canary wharf"],
    "New York": ["new york", "nyc", "jersey city", "manhattan"],
    "Chicago": ["chicago"],
    "Milan": ["milan", "milano"],
    "Zurich": ["zurich", "zuerich"],
    "Genève": ["geneva", "geneve", "genf"],
    "Luxembourg": ["luxembourg"],
    "Amsterdam": ["amsterdam"],
}
CITY_COUNTRY = {
    "Paris": "France", "Lyon": "France", "Lille": "France", "Montréal": "Canada", "Toronto": "Canada",
    "Londres": "Royaume-Uni", "New York": "États-Unis", "Chicago": "États-Unis", "Milan": "Italie",
    "Zurich": "Suisse", "Genève": "Suisse", "Luxembourg": "Luxembourg", "Amsterdam": "Pays-Bas",
}


def detect_cities(location_text: str) -> list[str]:
    n = norm(location_text)
    found = []
    for city, pats in CITY_PATTERNS.items():
        if any(has_word(n, p) for p in pats):
            found.append(city)
    return found


# ----------------------------------------------------------------------------
# Stage / contrat
# ----------------------------------------------------------------------------

INTERN_WORDS = ["stage", "stagiaire", "intern", "interns", "internship", "internships", "off-cycle", "off cycle",
                "offcycle", "summer analyst", "intern analyst", "praktikum", "tirocinio", "stage de fin d etudes",
                "end of studies", "industrial placement", "placement", "trainee"]


def is_internship(title: str, description: str = "") -> bool:
    t = norm(title)
    if any(has_word(t, w) for w in INTERN_WORDS):
        return True
    d = norm(description)[:1500]
    return any(has_word(d, w) for w in ["internship", "stage de fin d etudes", "off-cycle", "stage de 6 mois"])


def excluded(title: str, words: list[str]) -> str | None:
    t = " " + norm(title) + " "
    for w in words:
        wn = norm(w)
        if not wn:
            continue
        if w.startswith(" ") or w.endswith(" "):
            if " " + wn + " " in t:
                return w.strip()
        elif has_word(t, wn):
            return w
    return None


# ----------------------------------------------------------------------------
# Type de poste
# ----------------------------------------------------------------------------

TECH_WORDS = ["software", "developer", "developpeur", "engineer", "engineering", "devops", "cyber", "it ",
              "data engineer", "full stack", "fullstack", "front-end", "backend", "back-end", "sre",
              "infrastructure", "network", "fpga", "hardware", "asic", "machine learning engineer"]
OFF_TOPIC_WORDS = ["human resources", "ressources humaines", "rh ", "marketing", "communication", "legal",
                   "juridique", "audit", "accounting", "comptab", "tax", "fiscal", "retail", "agence",
                   "branch", "wealth", "private bank", "banque privee", "conseiller", "advisor", "real estate",
                   "immobilier", "procurement", "achats", "design", "recruit", "investment banking", "m&a",
                   "fusions", "corporate finance", "coverage corporate", "leasing", "insurance", "assurance",
                   "facilities", "office manager", "event", "equity capital markets", "debt capital markets", "ecm",
                   "dcm", "sponsor", "r&d", "listing", "leveraged finance", "project finance", "private equity",
                   "venture capital", "transaction services", "restructuring", "financement"]

MARKET_WORDS = ["trading", "trader", "markets", "market", "marches", "marche", "fixed income", "ficc",
                "derivatives", "derives", "rates", "taux", "fx", "forex", "marche des changes", "credit trading", "equity",
                "equities", "actions", "repo", "securities", "commodities", "matieres premieres", "structur",
                "salle des marches", "front office", "hedging", "couverture", "xva", "pnl", "p&l", "options",
                "futures", "swaps", "obligataire", "bonds", "money market", "tresorerie", "treasury", "global markets",
                "cib", "capital markets", "collateral"]

ROLE_RULES = [
    # (rôle, motifs dans le titre)
    ("Middle Office", ["middle office", "middle-office", "product control", "controle produit", "pnl control",
                       "p&l control", "trade support", "trading support", "trading assistant support",
                       "valuation control", "suivi des operations de marche"]),
    ("Risk", ["market risk", "risques de marche", "risque de marche", "counterparty risk", "risque de contrepartie",
              "xva", "risk management", "risk manager", "risk analyst", "risk", "risque", "risques", "alm",
              "liquidity risk"]),
    ("Structuring", ["structuring", "structureur", "structuration", "structurer", "structured products",
                     "produits structures"]),
    ("Sales", ["sales", "vente", "vendeur", "sales trader", "sales-trader", "distribution",
               "business developer markets"]),
    ("Trading", ["trading", "trader", "market making", "market maker", "desk assistant", "assistant trader",
                 "execution", "arbitrage"]),
    ("Quant/Research", ["quant", "quantitative", "strategist", "research", "recherche"]),
    ("Markets (général)", ["markets", "global markets", "marches financiers", "marches de capitaux",
                           "capital markets", "salle des marches", "ficc", "fixed income", "equities", "s&t"]),
]


def detect_role(title: str, description: str = "") -> tuple[str | None, list[str]]:
    """Renvoie (rôle principal, tous les rôles détectés dans le titre)."""
    t = norm(title)
    roles = []
    for role, pats in ROLE_RULES:
        if any(has_word(t, p) or (len(p) > 7 and p in t) for p in pats):
            roles.append(role)
    # "Sales & Trading" => Sales et Trading ; le principal = le premier spécifique trouvé
    primary = None
    order = ["Sales", "Trading", "Structuring", "Risk", "Middle Office", "Quant/Research", "Markets (général)"]
    if "Sales" in roles and "Trading" in roles:
        primary = "Sales & Trading"
    else:
        for r in order:
            if r in roles:
                primary = r
                break
    if primary is None and description:
        d = norm(description)[:3000]
        scores = {}
        for role, pats in ROLE_RULES:
            scores[role] = sum(d.count(" " + p) for p in pats if len(p) > 3)
        best = max(scores, key=scores.get)
        if scores[best] >= 3:
            primary = best
            roles.append(best)
    return primary, roles


def market_context(title: str, description: str = "") -> int:
    t = norm(title)
    d = norm(description)[:4000]
    score = 3 * sum(1 for w in MARKET_WORDS if has_word(t, w))
    score += min(6, sum(1 for w in MARKET_WORDS if has_word(d, w)))
    return score


def is_tech_or_off_topic(title: str) -> str | None:
    t = " " + norm(title) + " "
    for w in TECH_WORDS + OFF_TOPIC_WORDS:
        wn = norm(w)
        if w.endswith(" "):
            if " " + wn + " " in t:
                return w.strip()
        elif has_word(t, wn) or (len(wn) > 6 and wn in t):
            return w
    return None


# ----------------------------------------------------------------------------
# Desk / classe d'actifs
# ----------------------------------------------------------------------------

DESK_RULES = [
    ("Equity Derivatives", ["equity derivatives", "derives actions", "derives d actions", "eqd", "equity structured",
                            "volatility", "exotic equity", "flow equity derivatives"]),
    ("Cash Equities", ["cash equities", "cash equity", "actions cash", "equity sales", "equity trading",
                       "equities", "equity", "actions", "etf", "delta one", "prime brokerage"]),
    ("Rates", ["rates", "taux", "interest rate", "inflation", "govies", "government bonds", "swaps", "obligations d etat",
               "linear rates", "rates derivatives"]),
    ("FX", ["fx", "forex", "foreign exchange", "changes", "marche des changes", "devises", "currencies"]),
    ("Credit", ["credit trading", "credit sales", "credit", "high yield", "investment grade", "abs", "securitization",
                "titrisation", "distressed"]),
    ("Fixed Income (général)", ["fixed income", "ficc", "obligataire", "bonds", "debt"]),
    ("Commodities", ["commodities", "commodity", "matieres premieres", "energy", "energie", "power", "gas", "gaz",
                     "oil", "petrole", "metals", "metaux", "agri", "carbon", "lng", "electricite"]),
    ("Securities Finance / Repo", ["repo", "securities lending", "pret emprunt", "securities finance", "collateral",
                                   "collateral management", "triparty", "tri-party", "financing"]),
    ("Money Markets / Trésorerie", ["money market", "money markets", "marche monetaire", "tresorerie", "treasury",
                                    "liquidity", "liquidite", "cash & liquidite", "alm"]),
    ("Structured Products", ["structured products", "produits structures", "structured solutions", "structuring"]),
    ("Emerging Markets", ["emerging markets", "marches emergents", "cee", "latam"]),
    ("XVA / Counterparty", ["xva", "cva", "counterparty"]),
    ("Cross-Asset / Multi-Asset", ["cross-asset", "cross asset", "multi-asset", "multi asset", "global macro", "macro"]),
]


AMBIGUOUS_IN_DESCRIPTION = {"credit", "changes", "energy", "energie", "power", "gas", "gaz", "debt", "macro", "agri",
                            "actions", "equity", "taux", "financing", "liquidity", "alm", "cee", "abs", "oil",
                            "solutions", "treasury", "tresorerie", "metals"}


def detect_desks(title: str, description: str = "") -> list[str]:
    t = norm(title)
    found = []
    for desk, pats in DESK_RULES:
        if any(has_word(t, p) for p in pats):
            found.append(desk)
    if "Equity Derivatives" in found and "Cash Equities" in found:
        found.remove("Cash Equities")
    if "Credit" in found and "Fixed Income (général)" in found:
        found.remove("Fixed Income (général)")
    if found:
        return found
    # Sinon : regarder la description, en ne gardant que des signaux forts
    d = norm(description)[:4000]
    scores = []
    for desk, pats in DESK_RULES:
        pats = [p for p in pats if p not in AMBIGUOUS_IN_DESCRIPTION]
        s = sum(len(re.findall(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", d)) for p in pats)
        if s >= 2:
            scores.append((s, desk))
    scores.sort(reverse=True)
    return [d for _, d in scores[:2]]


# ----------------------------------------------------------------------------
# Dates de début, durée et compatibilité de période
# ----------------------------------------------------------------------------

MONTHS = {
    "janvier": 1, "january": 1, "jan": 1, "janv": 1, "fevrier": 2, "february": 2, "feb": 2, "fev": 2,
    "mars": 3, "march": 3, "mar": 3, "avril": 4, "april": 4, "apr": 4, "avr": 4, "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6, "juillet": 7, "july": 7, "jul": 7, "juil": 7, "aout": 8, "august": 8,
    "aug": 8, "septembre": 9, "september": 9, "sept": 9, "sep": 9, "octobre": 10, "october": 10, "oct": 10,
    "novembre": 11, "november": 11, "nov": 11, "decembre": 12, "december": 12, "dec": 12,
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "agosto": 8, "settembre": 9, "ottobre": 10, "dicembre": 12,
}
SEASONS = {"spring": 3, "printemps": 4, "summer": 6, "ete": 6, "autumn": 9, "fall": 9, "automne": 9, "winter": 1,
           "hiver": 1}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
SEASON_RE = "|".join(SEASONS)

START_CTX = (r"(?:start(?:ing|s)?|commenc\w*|debut\w*|from|a partir d[eu]?|des|as of|beginning|begin|starting date|"
             r"start date|date de debut|available|a pourvoir|pourvoir|demarr\w*|des le mois de|in)")


def extract_start(title: str, description: str = "") -> dict:
    """Essaie d'extraire le mois/année de début. Renvoie {year, month, text, precision}."""
    t = norm(title)
    d = norm(description)
    best = None
    # 1) Mois + année avec contexte de début dans la description
    for m in re.finditer(r"\b" + START_CTX + r"\b[^.;:]{0,40}?\b(" + MONTH_RE + r")\.?\s*(?:de\s+)?(20\d\d)", d):
        best = {"year": int(m.group(2)), "month": MONTHS[m.group(1)], "text": m.group(0)[-60:],
                "precision": "mois"}
        break
    # 2) Mois + année dans le titre
    if not best:
        m = re.search(r"\b(" + MONTH_RE + r")\.?\s*(?:-|/)?\s*(20\d\d)", t)
        if m:
            best = {"year": int(m.group(2)), "month": MONTHS[m.group(1)], "text": m.group(0), "precision": "mois"}
    # 3) Saison + année (titre puis description)
    if not best:
        for src in (t, d[:3000]):
            m = re.search(r"\b(" + SEASON_RE + r")\s*(?:internship\s*)?(20\d\d)\b|\b(20\d\d)\s*(" + SEASON_RE + r")\b", src)
            if m:
                season = m.group(1) or m.group(4)
                year = m.group(2) or m.group(3)
                best = {"year": int(year), "month": SEASONS[season], "text": m.group(0), "precision": "saison"}
                break
    # 4) Mois + année n'importe où dans la description (première occurrence plausible)
    if not best:
        m = re.search(r"\b(" + MONTH_RE + r")\.?\s*(20\d\d)\b", d[:5000])
        if m and int(m.group(2)) >= 2026:
            best = {"year": int(m.group(2)), "month": MONTHS[m.group(1)], "text": m.group(0), "precision": "mois?"}
    # 5) Année seule dans le titre (ex. "Off-cycle Internship 2027")
    if not best:
        m = re.search(r"\b(202[6-9])\b", t)
        if m:
            best = {"year": int(m.group(1)), "month": None, "text": m.group(0), "precision": "annee"}
    return best or {"year": None, "month": None, "text": None, "precision": None}


def extract_duration_months(title: str, description: str = "") -> int | None:
    txt = norm(title) + " " + norm(description)[:6000]
    words = {"six": 6, "six-month": 6, "4": 4, "four": 4, "quatre": 4, "five": 5, "cinq": 5, "three": 3, "trois": 3,
             "twelve": 12, "douze": 12, "ten": 10}
    m = re.search(r"\b(\d{1,2}|six|four|quatre|five|cinq|three|trois|twelve|douze)\s*(?:-|\s)?\s*(?:mois|months?|month)\b", txt)
    if m:
        v = m.group(1)
        n = int(v) if v.isdigit() else words.get(v)
        if n and 1 <= n <= 12:
            return n
    m = re.search(r"\b(\d{1,2})\s*(?:-|\s)?\s*(?:weeks?|semaines?)\b", txt)
    if m and 4 <= int(m.group(1)) <= 16 and ("summer" in txt or "ete" in txt):
        return round(int(m.group(1)) / 4.3)
    if re.search(r"\bsummer (?:internship|analyst|intern)\b", txt) and "off-cycle" not in txt:
        return 2
    return None


def period_fit(start: dict, duration: int | None, avail_from: date, avail_to: date, wanted_months: int = 6) -> tuple[str, str]:
    """Renvoie (statut, explication). statut ∈ {"OK", "À vérifier", "Incompatible"}."""
    y, m = start.get("year"), start.get("month")
    if duration and duration < 4:
        return "Incompatible", f"Durée {duration} mois (stage court / summer)"
    if y is None:
        return "À vérifier", "Date de début non précisée"
    if m is None:
        if y < avail_from.year:
            return "Incompatible", f"Stage {y}"
        if y > avail_to.year:
            return "Incompatible", f"Stage {y}"
        return "À vérifier", f"Année {y}, mois non précisé"
    dur = duration or wanted_months
    start_idx = y * 12 + (m - 1)
    end_idx = start_idx + dur - 1
    a = avail_from.year * 12 + (avail_from.month - 1)
    b = avail_to.year * 12 + (avail_to.month - 1)
    label = f"Début {m:02d}/{y}"
    if start_idx >= a and end_idx <= b:
        return "OK", label
    # Tolérance d'un mois (dates souvent indicatives)
    if start_idx >= a - 1 and end_idx <= b + 1:
        return "À vérifier", label + " (à la limite)"
    return "Incompatible", label
