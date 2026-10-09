"""Connecteurs vers les plateformes de recrutement (API publiques des sites carrière)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode, urlparse

from bs4 import BeautifulSoup

from .. import net
from ..classify import html_to_text


def _item(**kw) -> dict:
    base = {"source": None, "source_id": None, "company": None, "title": "", "url": None, "apply_url": None,
            "location": "", "posted_at": None, "description": None, "extra": {}}
    base.update(kw)
    return base


def _iso(d) -> str | None:
    if not d:
        return None
    try:
        s = str(d).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s) if "T" in s else datetime.fromisoformat(s[:10] + "T00:00:00+00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _posted_on(text: str | None) -> str | None:
    """Workday : "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago"."""
    if not text:
        return None
    now = datetime.now(timezone.utc)
    t = text.lower()
    if "today" in t or "aujourd" in t:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if "yesterday" in t or "hier" in t:
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    m = re.search(r"(\d+)\+?\s*(day|jour)", t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return None


# ----------------------------------------------------------------------------
# Workday
# ----------------------------------------------------------------------------

def workday_base(site_url: str) -> str:
    u = urlparse(site_url)
    host = u.netloc
    parts = [p for p in u.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if host.startswith("wd") and "myworkdaysite" in host:  # ex. wd1.myworkdaysite.com/recruiting/wf/Site
        tenant, site = parts[1], parts[2]
    else:
        tenant, site = host.split(".")[0], parts[0]
    return f"https://{host}/wday/cxs/{tenant}/{site}", f"https://{host}/{site}"


def workday_list(conf: dict, searches: list[str], max_per_search: int = 40) -> list[dict]:
    api, public = workday_base(conf["url"])
    out, seen = [], set()
    for q in searches:
        offset = 0
        while offset < max_per_search:
            data = net.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
            posts = data.get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                sid = (p.get("bulletFields") or [None])[0] or path.rsplit("_", 1)[-1]
                out.append(_item(source="Site officiel", source_id=f"{conf['entreprise']}|{sid}", company=conf["entreprise"],
                                 title=p.get("title", ""), url=public + path, apply_url=public + path,
                                 location=p.get("locationsText") or "", posted_at=_posted_on(p.get("postedOn")),
                                 extra={"api": api, "path": path}))
            offset += 20
            if len(posts) < 20 or offset >= (data.get("total") or 0):
                break
    return out


def workday_detail(item: dict) -> dict:
    data = net.get_json(item["extra"]["api"] + item["extra"]["path"])
    info = data.get("jobPostingInfo") or {}
    locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    item["location"] = " ; ".join(l for l in locs if l) or item["location"]
    item["description"] = html_to_text(info.get("jobDescription"))
    item["posted_at"] = _iso(info.get("startDate")) or item["posted_at"]
    if info.get("externalUrl"):
        item["url"] = item["apply_url"] = info["externalUrl"]
    return item


# ----------------------------------------------------------------------------
# Oracle Recruiting Cloud (J.P. Morgan)
# ----------------------------------------------------------------------------

def oracle_list(conf: dict, searches: list[str], pages: int = 3) -> list[dict]:
    """Recherches triées par pertinence (pour couvrir le stock d'offres) + une passe sur les plus récentes."""
    host, site = conf["hote"].rstrip("/"), conf["site"]
    out, seen = [], set()
    passes = [(q, "RELEVANCY", pages) for q in searches] + [("intern", "POSTING_DATES_DESC", 2)]
    for q, sort, n_pages in passes:
        for page in range(n_pages):
            finder = (f"findReqs;siteNumber={site},limit=25,offset={page * 25},"
                      f"keyword=\"{q}\",sortBy={sort}")
            url = (f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                   f"&expand=requisitionList.secondaryLocations&finder={quote(finder, safe='=;,')}")
            data = net.get_json(url)
            items = (data.get("items") or [{}])[0].get("requisitionList") or []
            for r in items:
                rid = str(r.get("Id"))
                if rid in seen:
                    continue
                seen.add(rid)
                locs = [r.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in (r.get("secondaryLocations") or [])]
                link = f"{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}"
                out.append(_item(source="Site officiel", source_id=f"{conf['entreprise']}|{rid}",
                                 company=conf["entreprise"], title=r.get("Title", ""), url=link, apply_url=link,
                                 location=" ; ".join(l for l in locs if l), posted_at=_iso(r.get("PostedDate")),
                                 extra={"host": host, "site": site, "id": rid}))
            if len(items) < 25:
                break
    return out


def oracle_detail(item: dict) -> dict:
    e = item["extra"]
    finder = f'ById;Id="{e["id"]}",siteNumber={e["site"]}'
    url = (f"{e['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
           f"&finder={quote(finder, safe='=;,')}")
    data = net.get_json(url)
    d = (data.get("items") or [{}])[0]
    parts = [d.get("ExternalDescriptionStr"), d.get("ExternalResponsibilitiesStr"), d.get("ExternalQualificationsStr")]
    item["description"] = html_to_text(" ".join(p for p in parts if p))
    return item


# ----------------------------------------------------------------------------
# Greenhouse
# ----------------------------------------------------------------------------

def greenhouse_list(conf: dict) -> list[dict]:
    token = conf["jeton"]
    data = net.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    out = []
    for j in data.get("jobs") or []:
        out.append(_item(source="Site officiel", source_id=f"gh|{token}|{j['id']}", company=conf["entreprise"],
                         title=j.get("title", ""), url=j.get("absolute_url"), apply_url=j.get("absolute_url"),
                         location=(j.get("location") or {}).get("name", ""),
                         posted_at=_iso(j.get("first_published") or j.get("updated_at")),
                         extra={"token": token, "id": j["id"]}))
    return out


def greenhouse_detail(item: dict) -> dict:
    e = item["extra"]
    j = net.get_json(f"https://boards-api.greenhouse.io/v1/boards/{e['token']}/jobs/{e['id']}")
    item["description"] = html_to_text(j.get("content"))
    return item


# ----------------------------------------------------------------------------
# SmartRecruiters
# ----------------------------------------------------------------------------

def smartrecruiters_list(conf: dict) -> list[dict]:
    cid = conf["identifiant"]
    out, offset = [], 0
    while offset < 500:
        data = net.get_json(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings?limit=100&offset={offset}")
        for p in data.get("content") or []:
            loc = p.get("location") or {}
            out.append(_item(source="Site officiel", source_id=f"sr|{cid}|{p['id']}", company=conf["entreprise"],
                             title=p.get("name", ""), url=f"https://jobs.smartrecruiters.com/{cid}/{p['id']}",
                             location=loc.get("fullLocation") or ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                             posted_at=_iso(p.get("releasedDate")), extra={"cid": cid, "id": p["id"]}))
        offset += 100
        if offset >= (data.get("totalFound") or 0):
            break
    return out


def smartrecruiters_detail(item: dict) -> dict:
    e = item["extra"]
    p = net.get_json(f"https://api.smartrecruiters.com/v1/companies/{e['cid']}/postings/{e['id']}")
    secs = ((p.get("jobAd") or {}).get("sections") or {})
    item["description"] = html_to_text(" ".join((secs.get(k) or {}).get("text", "") for k in
                                                ("jobDescription", "qualifications", "additionalInformation")))
    item["url"] = p.get("postingUrl") or item["url"]
    item["apply_url"] = p.get("applyUrl") or item["url"]
    return item


# ----------------------------------------------------------------------------
# BNP Paribas (site du groupe, pages HTML + données JSON-LD)
# ----------------------------------------------------------------------------

BNP_ROOT = "https://group.bnpparibas"


def bnp_list(conf: dict) -> list[dict]:
    out, seen = [], set()
    for page in range(1, int(conf.get("pages_max", 10)) + 1):
        html = net.get_text(conf["url"] + f"&page={page}")
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("article.card-offer")
        if not cards:
            if page == 1:
                raise net.FetchError("BNP : aucune offre trouvée sur la page (structure modifiée ou blocage anti-robot)")
            break
        for c in cards:
            a = c.select_one("a.card-link") or c.find("a")
            if not a or not a.get("href"):
                continue
            href = a["href"]
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            if slug in seen:
                continue
            seen.add(slug)
            title = (c.select_one("h3") or a).get_text(" ", strip=True)
            loc = c.select_one(".offer-location")
            out.append(_item(source="Site officiel", source_id=f"bnp|{slug}", company="BNP Paribas CIB", title=title,
                             url=BNP_ROOT + href if href.startswith("/") else href,
                             location=loc.get_text(" ", strip=True) if loc else ""))
        if len(cards) < 10:
            break
    return out


def bnp_detail(item: dict) -> dict:
    html = net.get_text(item["url"])
    soup = BeautifulSoup(html, "html.parser")
    for s in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(s.string or "{}", strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            item["description"] = html_to_text(data.get("description"))
            item["posted_at"] = _iso(data.get("datePosted"))
            addr = ((data.get("jobLocation") or {}).get("address") or {})
            loc = ", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")] if x)
            item["location"] = loc or item["location"]
            break
    apply = soup.select_one('a[href*="bwelcome"], a[href*="JobDetails"]')
    item["apply_url"] = apply["href"] if apply else item["url"]
    return item


# ----------------------------------------------------------------------------
# LinkedIn : recherche d'offres publique (sans connexion)
# ----------------------------------------------------------------------------

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"


def linkedin_search(keywords: str, location: str, start: int = 0) -> list[dict]:
    # f_TPR=r604800 : offres publiées depuis 7 jours ; sortBy=DD : les plus récentes d'abord
    params = {"keywords": keywords, "location": location, "f_TPR": "r604800", "sortBy": "DD", "start": start}
    html = net.get_text(LI_SEARCH + "?" + urlencode(params), retries=1)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li"):
        urn = li.select_one("[data-entity-urn]")
        title = li.select_one(".base-search-card__title")
        if not urn or not title:
            continue
        jid = urn["data-entity-urn"].rsplit(":", 1)[-1]
        comp = li.select_one(".base-search-card__subtitle")
        loc = li.select_one(".job-search-card__location")
        t = li.select_one("time")
        link = li.select_one("a.base-card__full-link")
        url = (link["href"].split("?")[0] if link and link.get("href") else f"https://www.linkedin.com/jobs/view/{jid}")
        out.append(_item(source="LinkedIn", source_id=f"li|{jid}", company=comp.get_text(" ", strip=True) if comp else "",
                         title=title.get_text(" ", strip=True), url=url, apply_url=url,
                         location=loc.get_text(" ", strip=True) if loc else "",
                         posted_at=_iso(t.get("datetime")) if t and t.get("datetime") else None,
                         extra={"id": jid}))
    return out


def linkedin_detail(item: dict) -> dict:
    html = net.get_text(LI_DETAIL + item["extra"]["id"], retries=1)
    soup = BeautifulSoup(html, "html.parser")
    desc = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    item["description"] = desc.get_text(" ", strip=True) if desc else ""
    crit = {}
    for c in soup.select(".description__job-criteria-item"):
        k = c.select_one(".description__job-criteria-subheader")
        v = c.select_one(".description__job-criteria-text")
        if k and v:
            crit[k.get_text(strip=True)] = v.get_text(strip=True)
    item["extra"]["criteria"] = crit
    # Lien de candidature externe, s'il est présent dans la page
    code = soup.select_one("code#applyUrl")
    if code and code.string:
        m = re.search(r"url=([^\"&]+)", code.string)
        if m:
            from urllib.parse import unquote
            item["apply_url"] = unquote(m.group(1))
    return item
