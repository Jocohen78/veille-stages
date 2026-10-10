"""Moteur de veille : collecte -> filtres -> classification -> dédoublonnage -> stockage -> notifications.

Lancement :  python -m engine.main            (production, avec Supabase)
             python -m engine.main --dry-run  (essai : rien n'est écrit ni notifié)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import uuid
from datetime import date, datetime, timezone

import yaml

from . import ai_match, classify as C, dedupe as D, net, notify
from .sources import ats
from .store import make_store, now_iso

PARTIAL_SOURCES = {"Workday", "Oracle", "LinkedIn"}  # recherches par mots-clés : absence != offre fermée


class Ctx:
    def __init__(self, conf: dict, store, dry_run: bool = False):
        self.conf = conf
        self.store = store
        self.dry = dry_run
        self.now = datetime.now(timezone.utc)
        self.rech = conf["recherche"]
        self.dd = conf["dedoublonnage"]
        self.companies = C.CompanyIndex(conf["entreprises"])
        self.avail_from = date.fromisoformat(self.rech["disponible_du"])
        self.avail_to = date.fromisoformat(self.rech["disponible_au"])
        self.target_cities = {c for c in self.rech["villes"]}
        self.offers = store.load_offers()
        self.by_sid = {o["source_id"]: o for o in self.offers if o.get("source_id")}
        self.events: list[tuple[str, dict]] = []
        self.seen_ids: set[str] = set()
        self.stats = {}
        self.detail_budget = 0
        self.recheck_budget = 15
        self.resumed = False  # reprise après une pause : pas de faux "Repost"

    # -------------------------------------------------------------- écriture
    def insert(self, row: dict) -> dict:
        if self.dry:
            row = dict(row)
        else:
            row = self.store.insert_offer(row)
        self.offers.append(row)
        if row.get("source_id"):
            self.by_sid[row["source_id"]] = row
        return row

    def patch(self, o: dict, patch: dict) -> None:
        o.update(patch)
        if not self.dry:
            self.store.update_offer(o["id"], patch)

    def group(self, group_id: str) -> list[dict]:
        return [o for o in self.offers if o.get("group_id") == group_id]

    def primary_of(self, group_id: str) -> dict | None:
        g = self.group(group_id)
        return next((o for o in g if o.get("is_primary")), g[0] if g else None)

    def promote(self, new: dict) -> None:
        """La nouvelle version devient l'offre principale ; les autres passent en doublons."""
        for o in self.group(new["group_id"]):
            if o["id"] != new["id"] and o.get("is_primary"):
                self.patch(o, {"is_primary": False, "dup_reason": "Version précédente"})
        if not new.get("is_primary"):
            self.patch(new, {"is_primary": True, "dup_reason": None})


# ---------------------------------------------------------------------------
# Classification d'une offre brute
# ---------------------------------------------------------------------------

def build_row(item: dict, ctx: Ctx) -> dict:
    rech = ctx.rech
    title, desc = item.get("title") or "", item.get("description") or ""
    comp = ctx.companies.match(item.get("company"))
    company = comp["nom"] if comp else (item.get("company") or "Inconnue").strip()
    cities = C.detect_cities(item.get("location") or "")
    if not cities and not (item.get("location") or "").strip():
        cities = C.detect_cities(title)
    targets = [c for c in cities if c in ctx.target_cities]
    role, roles = C.detect_role(title, desc)
    desks = C.detect_desks(title, desc)
    start = C.extract_start(title, desc)
    duration = C.extract_duration_months(title, desc)
    fit, fit_label = C.period_fit(start, duration, ctx.avail_from, ctx.avail_to, int(rech.get("duree_mois", 6)))
    mctx = C.market_context(title, desc)

    reason = None
    excl = C.excluded(title, rech.get("exclure_mots", []))
    off = C.is_tech_or_off_topic(title)
    wanted = set(rech.get("postes_voulus", []))
    role_ok = role in wanted or (role == "Sales & Trading" and ({"Sales", "Trading"} & wanted))
    if not (C.is_internship(title, desc) or (item.get("extra") or {}).get("internship")):
        reason = "Pas un stage"
    elif excl:
        reason = f"Contrat exclu ({excl})"
    elif not targets:
        reason = "Ville hors cible" if cities or item.get("location") else "Ville inconnue"
    elif off and role not in ("Trading", "Sales & Trading", "Structuring", "Middle Office"):
        reason = f"Hors marchés ({off})"
    elif not role_ok:
        reason = f"Poste non recherché ({role or 'non identifié'})"
    elif role in ("Sales", "Risk", "Middle Office") and mctx < 3:
        reason = "Pas de contexte marchés"
    elif not comp and not (rech.get("inclure_autres_entreprises") and mctx >= 3 and
                           any(C.has_word(C.norm(title), w) for w in C.MARKET_WORDS)):
        reason = "Entreprise hors liste"
    if reason == "Ville inconnue" and item.get("source") == "Ajout manuel":
        reason = None  # un ajout manuel est toujours conservé

    row = {
        "id": str(uuid.uuid4()),
        "company": company,
        "company_raw": item.get("company"),
        "company_category": comp["categorie"] if comp else "Autres (hors liste)",
        "company_listed": bool(comp),
        "title": title[:300],
        "title_norm": D.title_key(title),
        "city": targets[0] if targets else (cities[0] if cities else None),
        "cities": targets or cities,
        "country": C.CITY_COUNTRY.get(targets[0]) if targets else None,
        "location": (item.get("location") or "")[:300],
        "source": item.get("source"),
        "source_id": item.get("source_id"),
        "source_meta": item.get("extra") or {},
        "url": item.get("url"),
        "apply_url": item.get("apply_url") or item.get("url"),
        "posted_at": item.get("posted_at"),
        "first_seen_at": now_iso(),
        "last_seen_at": now_iso(),
        "detail_checked_at": now_iso() if desc else None,
        "description": desc[:8000] if not reason else desc[:600],
        "description_hash": D.description_hash(desc),
        "role_type": role,
        "roles": roles,
        "desks": desks,
        "duration_months": duration,
        "start_year": start["year"],
        "start_month": start["month"],
        "start_text": start["text"],
        "period_fit": fit,
        "period_label": fit_label,
        "market_score": mctx,
        "relevant": reason is None,
        "filter_reason": reason,
        "active": True,
        "is_primary": True,
        "manual": item.get("source") == "Ajout manuel",
    }
    row["group_id"] = row["id"]
    return row


# ---------------------------------------------------------------------------
# Traitement d'une offre collectée
# ---------------------------------------------------------------------------

def prefilter(item: dict, ctx: Ctx) -> bool:
    """Filtre rapide sur le titre et le lieu, avant d'aller chercher le détail de l'offre."""
    title = item.get("title") or ""
    if not (C.is_internship(title) or (item.get("extra") or {}).get("internship")):
        return False
    if C.excluded(title, ctx.rech.get("exclure_mots", [])):
        return False
    loc = item.get("location") or ""
    cities = C.detect_cities(loc)
    multi = any(w in loc.lower() for w in ("locations", "lieux", "sites", "multiple"))
    if loc and not multi and cities and not (set(cities) & ctx.target_cities):
        return False
    if loc and not multi and not cities and not C.detect_cities(title):
        return False
    return True


DETAIL_FN = {"Workday": ats.workday_detail, "Oracle": ats.oracle_detail, "Greenhouse": ats.greenhouse_detail,
             "SmartRecruiters": ats.smartrecruiters_detail, "BNP": ats.bnp_detail, "LinkedIn": ats.linkedin_detail}


def connector_of(o: dict) -> str | None:
    sid = o.get("source_id") or ""
    if sid.startswith("gh|"):
        return "Greenhouse"
    if sid.startswith("sr|"):
        return "SmartRecruiters"
    if sid.startswith("bnp|"):
        return "BNP"
    if sid.startswith("li|"):
        return "LinkedIn"
    meta = o.get("source_meta") or {}
    if "api" in meta:
        return "Workday"
    if "site" in meta and "host" in meta:
        return "Oracle"
    return None


def handle_known(o: dict, item: dict, ctx: Ctx, connector: str) -> None:
    ctx.seen_ids.add(o["id"])
    gap = D.days_between(o.get("last_seen_at"), ctx.now)
    if ctx.resumed and (gap > ctx.dd["jours_absence_repost"] or o.get("active") is False):
        ctx.patch(o, {"active": True, "last_seen_at": now_iso()})  # toujours en ligne après la pause
        return
    if o.get("relevant") and (gap > ctx.dd["jours_absence_repost"] or o.get("active") is False):
        ctx.patch(o, {"badge": "Repost", "badge_at": now_iso(), "active": True, "last_seen_at": now_iso()})
        ctx.promote(o)
        ctx.events.append(("repost", o))
        return
    if (o.get("relevant") and o.get("is_primary") and ctx.recheck_budget > 0
            and D.days_between(o.get("detail_checked_at"), ctx.now) > 1):
        ctx.recheck_budget -= 1
        try:
            item = DETAIL_FN[connector](item)
        except Exception:
            return
        new_desc = item.get("description") or ""
        sim = D.description_similarity(new_desc, o.get("description"))
        patch = {"detail_checked_at": now_iso()}
        if sim is not None and sim < ctx.dd["seuil_changement_description"]:
            fresh = build_row(item, ctx)
            for k in ("title", "title_norm", "description", "description_hash", "role_type", "roles", "desks",
                      "duration_months", "start_year", "start_month", "start_text", "period_fit", "period_label",
                      "location", "apply_url"):
                patch[k] = fresh[k]
            patch.update({"badge": "Mise à jour", "badge_at": now_iso()})
            ctx.patch(o, patch)
            ctx.events.append(("maj", o))
        else:
            ctx.patch(o, patch)


def handle_new(item: dict, ctx: Ctx, connector: str) -> None:
    if ctx.detail_budget <= 0:
        return  # sera traitée au prochain passage
    ctx.detail_budget -= 1
    if item.get("description") is None and connector in DETAIL_FN:
        try:
            item = DETAIL_FN[connector](item)
        except net.FetchError:
            return
    row = build_row(item, ctx)
    ingest_row(row, ctx)


def ingest_row(row: dict, ctx: Ctx) -> dict:
    if not row["relevant"]:
        return ctx.insert(row)
    candidates = [o for o in ctx.offers if o.get("relevant")]
    match = D.find_group(row, candidates, ctx.dd["seuil_similarite_titre"])
    if not match:
        row = ctx.insert(row)
        ctx.events.append(("nouvelle", row))
        return row
    gid = match["group_id"]
    primary = ctx.primary_of(gid) or match
    group = ctx.group(gid)
    last_seen = max((o.get("last_seen_at") or "") for o in group)
    row.update({"group_id": gid, "status": primary.get("status") or "Nouvelle", "notes": primary.get("notes")})
    sim = D.description_similarity(row.get("description"), primary.get("description"))
    if not ctx.resumed and (D.days_between(last_seen, ctx.now) > ctx.dd["jours_absence_repost"]
                            or not any(o.get("active") for o in group)):
        row.update({"is_primary": False, "badge": "Repost", "badge_at": now_iso()})
        row = ctx.insert(row)
        ctx.promote(row)
        ctx.events.append(("repost", row))
    elif sim is not None and sim < ctx.dd["seuil_changement_description"] and row["source"] == primary.get("source"):
        row.update({"is_primary": False, "badge": "Mise à jour", "badge_at": now_iso()})
        row = ctx.insert(row)
        ctx.promote(row)
        ctx.events.append(("maj", row))
    else:
        same_src = row["source"] == primary.get("source")
        row.update({"is_primary": False,
                    "dup_reason": "Doublon sur la même source" if same_src else f"Déjà vue sur {primary.get('source')}"})
        row = ctx.insert(row)
        # L'offre principale est toujours en ligne
        ctx.patch(primary, {"last_seen_at": now_iso(), "active": True})
    return row


def process(items: list[dict], ctx: Ctx, connector: str) -> dict:
    kept = [it for it in items if prefilter(it, ctx)]
    n_new = 0
    for it in kept:
        o = ctx.by_sid.get(it["source_id"])
        if o:
            handle_known(o, it, ctx, connector)
        else:
            before = len(ctx.offers)
            handle_new(it, ctx, connector)
            n_new += len(ctx.offers) > before
    return {"fetched": len(items), "kept": len(kept), "new": n_new}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def due(name: str, every_min: int, last: dict, ctx: Ctx, force: bool) -> bool:
    if force or name not in last:
        return True
    return D.days_between(last[name], ctx.now) * 1440 >= every_min - 5


def run_sources(ctx: Ctx, only: str | None, force: bool) -> list[dict]:
    S = ctx.conf["sources"]
    last = {} if ctx.dry else ctx.store.last_runs()
    if last:
        pause = D.days_between(max(last.values()), ctx.now)
        if pause > 2:
            ctx.resumed = True
            print(f"Reprise après {pause:.0f} jours de pause : les offres déjà connues ne seront pas signalées comme reposts.")
    jobs = []  # (nom du run, connecteur, fonction de collecte, budget de détails)
    if S.get("workday", {}).get("actif"):
        for site in S["workday"]["sites"]:
            jobs.append((f"Workday · {site['entreprise']}", "Workday", S["workday"]["toutes_les_minutes"],
                         lambda s=site: ats.workday_list(s, S["workday"]["recherches"]), 25))
    if S.get("oracle", {}).get("actif"):
        for site in S["oracle"]["sites"]:
            jobs.append((f"Oracle · {site['entreprise']}", "Oracle", S["oracle"]["toutes_les_minutes"],
                         lambda s=site: ats.oracle_list(s, S["oracle"]["recherches"]), 25))
    if S.get("greenhouse", {}).get("actif"):
        for b in S["greenhouse"]["tableaux"]:
            jobs.append((f"Greenhouse · {b['entreprise']}", "Greenhouse", S["greenhouse"]["toutes_les_minutes"],
                         lambda b=b: ats.greenhouse_list(b), 20))
    if S.get("smartrecruiters", {}).get("actif"):
        for c in S["smartrecruiters"]["entreprises"]:
            jobs.append((f"SmartRecruiters · {c['entreprise']}", "SmartRecruiters",
                         S["smartrecruiters"]["toutes_les_minutes"], lambda c=c: ats.smartrecruiters_list(c), 20))
    if S.get("bnp", {}).get("actif"):
        jobs.append(("Site BNP Paribas", "BNP", S["bnp"]["toutes_les_minutes"], lambda: ats.bnp_list(S["bnp"]), 40))
    if S.get("linkedin", {}).get("actif"):
        jobs.append(("LinkedIn (offres publiques)", "LinkedIn", S["linkedin"]["toutes_les_minutes"],
                     lambda: linkedin_collect(S["linkedin"]), 60))

    results = []
    for name, connector, every, fn, budget in jobs:
        if only and only.lower() not in name.lower():
            continue
        if not due(name, every, last, ctx, force):
            continue
        started = now_iso()
        t0 = time.time()
        try:
            items = fn()
            ctx.detail_budget = budget
            st = process(items, ctx, connector)
            res = {"source": name, "ok": True, **st, "error": None}
        except Exception as e:  # une source en panne ne bloque pas les autres
            res = {"source": name, "ok": False, "fetched": 0, "kept": 0, "new": 0,
                   "error": f"{type(e).__name__}: {e}"[:500]}
            if os.environ.get("DEBUG"):
                traceback.print_exc()
        res.update({"started_at": started, "finished_at": now_iso(), "duration_s": round(time.time() - t0, 1)})
        print(f"[{'OK ' if res['ok'] else 'ERR'}] {name}: {res['fetched']} récupérées, {res['kept']} après filtre, "
              f"{res['new']} nouvelles ({res['duration_s']} s){' — ' + res['error'] if res['error'] else ''}")
        results.append(res)
    return results


def linkedin_collect(conf: dict) -> list[dict]:
    out, seen, errors = [], set(), 0
    searches = conf["recherches"]
    for i, loc in enumerate(conf["lieux"]):
        qs = searches if i == 0 else searches[: int(conf.get("recherches_hors_paris", 3))]
        for q in qs:
            for page in range(int(conf.get("pages_par_recherche", 2))):
                try:
                    res = ats.linkedin_search(q, loc, start=page * 10)
                except net.FetchError:
                    errors += 1
                    if errors >= 4:  # LinkedIn limite les requêtes : on garde ce qui a déjà été collecté
                        if not out:
                            raise
                        print(f"LinkedIn : arrêt anticipé après {errors} refus ({len(out)} offres collectées)")
                        return out
                    time.sleep(10)
                    break
                for it in res:
                    if it["source_id"] not in seen:
                        seen.add(it["source_id"])
                        out.append(it)
                time.sleep(float(conf.get("pause_secondes", 2.5)))
                if len(res) < 10:
                    break
    return out


# ---------------------------------------------------------------------------
# Ajouts manuels (depuis le dashboard), expiration, analyse IA
# ---------------------------------------------------------------------------

def process_inbox(ctx: Ctx) -> int:
    if ctx.dry:
        return 0
    n = 0
    for e in ctx.store.pending_inbox():
        try:
            item = {"source": "Ajout manuel", "source_id": f"manual|{e['id']}", "company": e.get("company") or "",
                    "title": e.get("title") or "", "url": e.get("url"), "apply_url": e.get("url"),
                    "location": e.get("location") or "", "posted_at": e.get("created_at"),
                    "description": e.get("text") or "", "extra": {"origin": e.get("origin")}}
            if not item["title"]:
                item["title"] = (e.get("text") or "Offre ajoutée manuellement").strip().split("\n")[0][:140]
            row = build_row(item, ctx)
            if not C.is_internship(row["title"], row["description"]) and row["filter_reason"] == "Pas un stage":
                row["relevant"], row["filter_reason"] = True, None  # l'utilisateur a choisi de l'ajouter
            if row["filter_reason"]:
                # Un ajout manuel reste visible ; la raison est gardée en note
                row["relevant"], row["filter_reason"] = True, None
            if e.get("posted_at"):
                row["posted_at"] = e["posted_at"]
            row = ingest_row(row, ctx)
            ctx.store.mark_inbox(e["id"], {"processed": True, "offer_id": row["id"], "processed_at": now_iso(),
                                           "result": "Doublon" if not row.get("is_primary") else "Ajoutée"})
            n += 1
        except Exception as ex:  # pragma: no cover
            ctx.store.mark_inbox(e["id"], {"processed": True, "processed_at": now_iso(), "result": f"Erreur : {ex}"[:300]})
    return n


def expire(ctx: Ctx, results: list[dict]) -> int:
    ok_sources = {r["source"] for r in results if r["ok"]}
    if not ok_sources:
        return 0
    limit = ctx.dd["jours_avant_expiration"]
    n, checks = 0, 20
    for o in ctx.offers:
        if not o.get("active") or o.get("manual") or not o.get("relevant") or o["id"] in ctx.seen_ids:
            continue
        conn = connector_of(o)
        age = D.days_between(o.get("last_seen_at"), ctx.now)
        if conn in ("Greenhouse", "SmartRecruiters", "BNP"):
            if age > 2:  # listes complètes : absente 2 jours = fermée
                ctx.patch(o, {"active": False})
                n += 1
        elif conn in PARTIAL_SOURCES and age > limit and checks > 0:
            checks -= 1
            if still_open(o, conn):
                ctx.patch(o, {"last_seen_at": now_iso()})
            else:
                ctx.patch(o, {"active": False})
                n += 1
    return n


def still_open(o: dict, conn: str) -> bool:
    item = {"extra": dict(o.get("source_meta") or {}), "url": o.get("url"), "location": o.get("location"),
            "posted_at": o.get("posted_at"), "apply_url": o.get("apply_url")}
    try:
        if conn == "LinkedIn":
            html = net.get_text(ats.LI_DETAIL + item["extra"]["id"], retries=0)
            return "closed-job" not in html and "No longer accepting applications" not in html
        DETAIL_FN[conn](item)
        return bool(item.get("description"))
    except net.FetchError as e:
        return not any(code in str(e) for code in ("HTTP 404", "HTTP 410"))
    except Exception:
        return True


def run_ai(ctx: Ctx) -> int:
    if ctx.dry or not ai_match.is_enabled(ctx.conf):
        return 0
    cfg = ctx.conf.get("analyse_ia", {})
    todo = [o for o in ctx.offers if o.get("relevant") and o.get("is_primary") and o.get("match_score") is None
            and o.get("description") and (not cfg.get("seulement_offres_pertinentes", True) or o.get("period_fit") != "Incompatible")]
    n = 0
    for o in todo[: int(cfg.get("max_analyses_par_passage", 25))]:
        try:
            res = ai_match.analyze(o, ctx.conf)
            if res:
                ctx.patch(o, {**res, "match_at": now_iso()})
                n += 1
        except Exception as e:
            print("Analyse IA impossible :", e)
            break
    return n


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="n'écrit rien, n'envoie aucune notification")
    ap.add_argument("--source", help="ne lancer qu'une source (ex. 'Citi', 'LinkedIn')")
    ap.add_argument("--force", action="store_true", help="ignorer les intervalles entre collectes")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        conf = yaml.safe_load(f)
    ctx = Ctx(conf, make_store(), dry_run=args.dry_run)
    print(f"{len(ctx.offers)} offres déjà en base.")

    results = run_sources(ctx, args.source, args.force or args.dry_run)
    n_manual = process_inbox(ctx)
    if not args.dry_run and not args.source:
        # Les offres vues ce passage sont marquées "en ligne"
        seen = [i for i in ctx.seen_ids]
        if seen:
            ctx.store.update_many(seen, {"last_seen_at": now_iso(), "active": True})
        n_exp = expire(ctx, results)
    else:
        n_exp = 0
    n_ai = run_ai(ctx)

    events = [(k, o) for k, o in ctx.events
              if o.get("relevant") and (conf["notifications"].get("notifier_periode_incompatible")
                                        or o.get("period_fit") != "Incompatible")]
    sent = 0 if args.dry_run else notify.notify_offers(conf, events)

    if not args.dry_run:
        for r in results:
            ctx.store.log_run(r)
        failing = [r for r in results if not r["ok"]]
        if results and len(failing) == len(results):
            notify.notify_text("Veille stages : toutes les sources ont échoué",
                               "Vérifie l'onglet Sources du dashboard ou l'onglet Actions de GitHub.", conf)

    print(f"\nRésumé : {len(ctx.events)} événements (nouvelles / reposts / mises à jour), {sent} notifications, "
          f"{n_manual} ajouts manuels traités, {n_exp} offres expirées, {n_ai} analyses IA.")
    if args.dry_run:
        rel = [o for o in ctx.offers if o.get("relevant")]
        print(f"\n--- Essai à blanc : {len(rel)} offres pertinentes ---")
        for o in sorted(rel, key=lambda o: (o["company"], o["title"])):
            print(f"{'  ' if o.get('is_primary') else 'D '}{o['company'][:22]:22} | {o['title'][:70]:70} | "
                  f"{o.get('city') or '?':10} | {o.get('role_type') or '?':16} | {','.join(o.get('desks') or [])[:25]:25} | "
                  f"{o.get('period_fit')} {o.get('period_label') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
