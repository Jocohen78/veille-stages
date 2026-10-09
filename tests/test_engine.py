"""Tests du moteur (lancer : python -m pytest -q)."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from engine import classify as C, dedupe as D, main as M
from engine.store import LocalStore

CONF = yaml.safe_load(open("config.yaml", encoding="utf-8"))


def ctx(tmp_path, conf=None):
    return M.Ctx(conf or copy.deepcopy(CONF), LocalStore(str(tmp_path / "db.json")))


def item(company, title, location="Paris, Île-de-France, France", desc="", source="LinkedIn", sid=None):
    return {"source": source, "source_id": sid or f"x|{company}|{title}|{location}", "company": company, "title": title,
            "url": "https://example.org/" + title.replace(" ", "-"), "apply_url": None, "location": location,
            "posted_at": None, "description": desc, "extra": {}}


# ---------------------------------------------------------------------------
# Classification, sur de vrais intitulés relevés sur LinkedIn / Workday (oct. 2026)
# ---------------------------------------------------------------------------

REAL = [
    # (entreprise, intitulé, pertinent attendu, rôle attendu)
    ("Citi", "Markets – Sales and Trading, Off-Cycle Internship, Paris – France, 2027", True, "Sales & Trading"),
    ("Natixis Corporate & Investment Banking", "Stage - 6 mois - Quantitative Algo Trading – Rates F/H", True, "Trading"),
    ("HSBC", "Stage - Assistant Trader desk Cash & Liquidité et Portefeuille (f/m/d)", True, "Trading"),
    ("Natixis Corporate & Investment Banking", "Stage - 6 mois - Market Risk FRTB Data Quality Analyst F/H", True, "Risk"),
    ("Barclays", "Capital Markets Off Cycle Internship Programme 2027 Paris", True, "Markets (général)"),
    ("Crédit Agricole CACEIS", "Stage - Assistant(e) Sales Front Office - Securities Finance et Repo H/F", True, "Sales"),
    ("Citi", "Banking, Financing, Equity Capital Markets, Placement Analyst Internship, Paris - France 2027", False, None),
    ("MUFG", "6 month internship - Debt Capital Markets Bonds & Loans - January 2027", False, None),
    ("Wells Fargo", "Off-Cycle M&A Intern Analyst", False, None),
    ("Natixis Corporate & Investment Banking", "Stage - 6 mois - Analyste Sponsor Coverage F/H", False, None),
    ("Euronext", "Equity Listing Analyst Intern", False, None),
    ("Danone", "STAGE - Chef de Marché Paris Ouest - Janvier 2027 - (H/F)", False, None),
    ("DECATHLON FRANCE", "STAGE COMMERCE - Développer l’activité commerciale de ton sport (H/F)", False, None),
    ("Moët Hennessy", "Alternance – Assistant(e) Grands Comptes On-Trade (F/H/X)", False, None),
    ("Sienna Investment Managers", "Assistant(e) Sales - Offre de Stage - Janvier 2027", False, None),
    ("Thales", "Stage - Gestionnaire Risque de Change - F/H", False, None),
    ("Palatine", "Stage – Analyste risques de crédit H/F", False, None),
    ("Societe Generale Corporate and Investment Banking - SGCIB", "Trésorier", False, None),
    ("Crédit Agricole CIB", "Trader EUR Swap Trader H/F", False, None),  # pas un stage
    ("XRAYS TRADING", "Développeur(euse) C# performance (H/F)", False, None),
    ("Forvis Mazars en France", "Stagiaire de Fin d’Etudes en Analyste Finance Quantitative - 2027 (H/F)", False, None),
]


@pytest.mark.parametrize("company,title,relevant,role", REAL)
def test_real_titles(tmp_path, company, title, relevant, role):
    c = ctx(tmp_path)
    row = M.build_row(item(company, title, desc="Stage au sein de la salle des marchés, desk taux et FX."), c)
    assert row["relevant"] is relevant, (title, row["filter_reason"], row["role_type"])
    if relevant:
        assert row["role_type"] == role


def test_company_matching():
    idx = C.CompanyIndex(CONF["entreprises"])
    assert idx.match("JPMorganChase")["nom"] == "J.P. Morgan"
    assert idx.match("Societe Generale Corporate and Investment Banking - SGCIB")["nom"] == "Société Générale CIB"
    assert idx.match("Crédit Agricole CIB")["nom"] == "Crédit Agricole CIB (CACIB)"
    assert idx.match("ING")["nom"] == "ING"
    assert idx.match("Marex Trading") is None          # "ing" ne doit pas matcher dans "trading"
    assert idx.match("Citizens Bank") is None
    assert idx.match("TD Securities")["nom"].startswith("TD")
    assert idx.match("Crédit Agricole CACEIS") is None  # hors liste (gardée via "autres entreprises")


def test_cities():
    assert C.detect_cities("Montrouge, Île-de-France, France") == ["Paris"]
    assert C.detect_cities("La Défense, Île-de-France, France") == ["Paris"]
    assert C.detect_cities("London, England, United Kingdom") == ["Londres"]
    assert C.detect_cities("Genève, Switzerland") == ["Genève"]
    assert C.detect_cities("New York New York United States ; London  United Kingdom") == ["Londres", "New York"]
    assert C.detect_cities("Bogota  Colombia") == []


def test_desks():
    assert "Rates" in C.detect_desks("Stage - Quantitative Algo Trading – Rates F/H")
    assert C.detect_desks("Equity Derivatives Sales Internship") == ["Equity Derivatives"]
    assert "Securities Finance / Repo" in C.detect_desks("Stage - Sales Front Office - Securities Finance et Repo")
    assert "FX" in C.detect_desks("FX Options Trading intern")
    assert "Money Markets / Trésorerie" in C.detect_desks("Assistant Trader desk Cash & Liquidité")


def test_start_dates_and_period():
    from datetime import date
    a, b = date(2027, 5, 1), date(2027, 12, 31)
    citi = "The Markets intern analyst program runs for six months starting in January 2027."
    s = C.extract_start("Markets Off-Cycle Internship, Paris, 2027", citi)
    assert (s["year"], s["month"]) == (2027, 1)
    assert C.extract_duration_months("x", citi) == 6
    assert C.period_fit(s, 6, a, b)[0] == "Incompatible"

    hsbc = "Le stage se déroule à Paris, à temps plein et sur 6 mois. Le stage est à pourvoir pour juillet 2027."
    s = C.extract_start("Stage - Assistant Trader", hsbc)
    assert (s["year"], s["month"]) == (2027, 7)
    assert C.period_fit(s, 6, a, b)[0] == "OK"

    s = C.extract_start("Stage Sales Rates - Mai 2027 - 6 mois", "")
    assert (s["year"], s["month"]) == (2027, 5)
    assert C.period_fit(s, 6, a, b)[0] == "OK"

    s = C.extract_start("Off-cycle internship 2027", "")
    assert C.period_fit(s, None, a, b)[0] == "À vérifier"
    s = C.extract_start("Summer Internship 2027", "10-week summer internship program")
    assert C.period_fit(s, C.extract_duration_months("Summer Internship 2027", "10-week summer internship program"), a, b)[0] == "Incompatible"
    s = C.extract_start("Stage 2026 - Trading", "")
    assert C.period_fit(s, None, a, b)[0] == "Incompatible"
    assert C.period_fit(C.extract_start("Stage sales", ""), None, a, b)[0] == "À vérifier"


# ---------------------------------------------------------------------------
# Dédoublonnage
# ---------------------------------------------------------------------------

def test_title_similarity():
    a = D.title_key("Markets – Sales and Trading, Off-Cycle Internship, Paris – France, 2027")
    b = D.title_key("Markets - Sales & Trading Off-Cycle Internship Paris 2027 (H/F)")
    assert D.token_set_ratio(a, b) >= 86
    c = D.title_key("Markets – Summer Internship, Paris, 2027")
    assert D.token_set_ratio(a, c) < 86
    d = D.title_key("Stage Sales Rates H/F")
    e = D.title_key("Stage Sales Equity Derivatives H/F")
    assert D.token_set_ratio(d, e) < 86


DESC = ("Au sein de la salle des marchés, vous rejoindrez le desk Rates Sales en charge de la clientèle institutionnelle. "
        "Vos missions : préparation des pricings, suivi des positions clients, analyses de marché quotidiennes, "
        "participation aux points du matin, construction d'outils en VBA et Python pour l'équipe. Profil : école de "
        "commerce ou d'ingénieur, dernière année, stage de fin d'études de 6 mois à partir de juin 2027. ") * 2
DESC2 = ("Nouvelle version complètement réécrite : le poste porte désormais sur le desk Credit Trading à Londres "
         "avec un fort accent sur le market making de high yield, la gestion du book et la couverture CDS ; "
         "maîtrise de Bloomberg exigée, anglais courant, disponibilité dès juillet 2027 pour une durée de six mois "
         "minimum, possibilité de prolongation, rémunération attractive et logement fourni. ") * 2


def test_pipeline_new_duplicate_repost_update(tmp_path):
    c = ctx(tmp_path)
    # 1) Nouvelle offre sur le site officiel
    it1 = item("Natixis CIB", "Stage - Rates Sales - Juin 2027", desc=DESC, source="Site officiel", sid="nat|1")
    M.ingest_row(M.build_row(it1, c), c)
    assert len(c.events) == 1 and c.events[0][0] == "nouvelle"
    p = c.offers[0]
    assert p["is_primary"] and p["period_fit"] == "OK" and p["desks"] == ["Rates"]

    # 2) La même offre sur LinkedIn -> doublon, rattaché au même groupe, pas de notification
    it2 = item("Natixis Corporate & Investment Banking", "Stage Rates Sales (Juin 2027) H/F", desc=DESC, sid="li|9")
    r2 = M.ingest_row(M.build_row(it2, c), c)
    assert r2["is_primary"] is False and r2["group_id"] == p["group_id"]
    assert r2["dup_reason"] == "Déjà vue sur Site officiel"
    assert len(c.events) == 1

    # 3) Le statut est propagé au doublon (côté base : déclencheur SQL ; ici on simule la lecture)
    c.patch(p, {"status": "Postulée"})

    # 4) Repost tardif : le groupe n'a pas été vu depuis 20 jours
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    for o in c.offers:
        c.patch(o, {"last_seen_at": old, "active": False})
    it3 = item("Natixis CIB", "Stage - Rates Sales - Juin 2027", desc=DESC, source="Site officiel", sid="nat|2")
    r3 = M.ingest_row(M.build_row(it3, c), c)
    assert r3["is_primary"] and r3["badge"] == "Repost" and r3["status"] == "Postulée"
    assert sum(o["is_primary"] for o in c.offers if o["group_id"] == p["group_id"]) == 1
    assert c.events[-1][0] == "repost"

    # 5) Mise à jour importante (description très différente, même source)
    it4 = item("Natixis CIB", "Stage - Rates Sales - Juin 2027", desc=DESC2, source="Site officiel", sid="nat|3")
    r4 = M.ingest_row(M.build_row(it4, c), c)
    assert r4["is_primary"] and r4["badge"] == "Mise à jour"
    assert c.events[-1][0] == "maj"


def test_different_city_not_duplicate(tmp_path):
    c = ctx(tmp_path)
    M.ingest_row(M.build_row(item("UBS", "Markets Off-Cycle Internship 2027", "London, UK", sid="a"), c), c)
    M.ingest_row(M.build_row(item("UBS", "Markets Off-Cycle Internship 2027", "Zurich, Switzerland", sid="b"), c), c)
    assert all(o["is_primary"] for o in c.offers)


def test_irrelevant_kept_but_flagged(tmp_path):
    c = ctx(tmp_path)
    r = M.ingest_row(M.build_row(item("Danone", "Stage Chef de produit Marketing"), c), c)
    assert r["relevant"] is False and r["filter_reason"]
    assert c.events == []


def test_known_offer_not_reprocessed(tmp_path, monkeypatch):
    c = ctx(tmp_path)
    calls = []
    monkeypatch.setitem(M.DETAIL_FN, "LinkedIn", lambda it: calls.append(1) or {**it, "description": DESC})
    it = item("BNP Paribas", "Stage Sales Rates - Juin 2027", sid="li|42")
    it["description"] = None
    c.detail_budget = 5
    st = M.process([dict(it)], c, "LinkedIn")
    assert st["new"] == 1 and len(calls) == 1
    st = M.process([dict(it)], c, "LinkedIn")
    assert st["new"] == 0 and len(calls) == 1  # pas de nouvel appel au détail


def test_prefilter():
    c = M.Ctx(copy.deepcopy(CONF), LocalStore("/tmp/_unused.json"))
    assert M.prefilter(item("Citi", "Markets Off-Cycle Internship", "Paris  France"), c)
    assert not M.prefilter(item("Citi", "Markets Internship", "Bogota  Colombia"), c)
    assert M.prefilter(item("Citi", "Markets Internship", "2 Locations"), c)
    assert not M.prefilter(item("Citi", "Senior Trader", "Paris"), c)
    assert not M.prefilter(item("X", "Alternance - Assistant Sales", "Paris"), c)
