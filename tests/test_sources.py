"""Tests des connecteurs sur des réponses réelles (structures relevées en octobre 2026)."""
import json

from engine import net
from engine.sources import ats

BNP_CARD = """<html><body>
<article class="card-custom card-offer category-28">
    <a href="/emploi-carriere/offre-emploi/business-management-intern-summer-2027" class="card-link">
        <div class="card-container"><div class="card-flex"><div class="card-content">
            <div class="offer-type">Stage</div>
            <h3 class="title-4">Business Management Intern - Summer 2027</h3>
            <div class="offer-location"><span class="icon icon-location" aria-hidden="true"></span>
                Montréal, Québec, Canada</div>
        </div></div></div>
    </a>
</article></body></html>"""

BNP_DETAIL = """<html><head><script type="application/ld+json">
{ "@context": "http://schema.org", "@type": "JobPosting", "title": "Business Management Intern - Summer 2027",
  "employmentType": "Stage", "datePosted": "2026-10-09",
  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Montréal",
  "addressRegion": "Québec", "addressCountry": "CA" }},
  "description": "<p>Join one of Montreal's Top Employers.</p><p>4months program</p>" }
</script></head><body><a href="https://bwelcome.hr.bnpparibas/en_US/externalcareers/JobDetails?jobId=111516">Postuler</a></body></html>"""

LI_SEARCH = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4457236919">
<a class="base-card__full-link" href="https://fr.linkedin.com/jobs/view/stage-assistant-e-sales-4457236919?position=1&pageNum=0"></a>
<h3 class="base-search-card__title">Stage - Assistant(e) Sales Front Office - Securities Finance et Repo H/F</h3>
<h4 class="base-search-card__subtitle"><a>Crédit Agricole CACEIS</a></h4>
<span class="job-search-card__location">Montrouge, Île-de-France, France</span>
<time class="job-search-card__listdate" datetime="2026-10-08">1 day ago</time></div></li>"""

LI_DETAIL = """<section><div class="show-more-less-html__markup">Nous recherchons un stagiaire. Le stage est à pourvoir pour juillet 2027.</div>
<ul><li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Employment type</h3>
<span class="description__job-criteria-text">Internship</span></li></ul></section>"""


def test_bnp(monkeypatch):
    pages = {1: BNP_CARD}
    monkeypatch.setattr(net, "get_text", lambda url, **k: pages.get(int(url.rsplit("page=", 1)[1]), "<html></html>")
                        if "page=" in url else BNP_DETAIL)
    items = ats.bnp_list({"url": "https://x/?a=1", "pages_max": 3})
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Business Management Intern - Summer 2027"
    assert it["location"].startswith("Montréal")
    assert it["url"] == "https://group.bnpparibas/emploi-carriere/offre-emploi/business-management-intern-summer-2027"
    it = ats.bnp_detail(it)
    assert it["posted_at"].startswith("2026-10-09")
    assert "4months" in it["description"]
    assert "bwelcome" in it["apply_url"]


def test_linkedin(monkeypatch):
    monkeypatch.setattr(net, "get_text", lambda url, **k: LI_SEARCH if "search" in url else LI_DETAIL)
    items = ats.linkedin_search("stage", "Paris")
    assert len(items) == 1
    it = items[0]
    assert it["source_id"] == "li|4457236919"
    assert it["company"] == "Crédit Agricole CACEIS"
    assert it["url"].endswith("4457236919")
    assert it["posted_at"].startswith("2026-10-08")
    it = ats.linkedin_detail(it)
    assert "juillet 2027" in it["description"]
    assert it["extra"]["criteria"]["Employment type"] == "Internship"


def test_workday(monkeypatch):
    listing = {"total": 1, "jobPostings": [{
        "title": "Markets – Sales and Trading, Off-Cycle Internship, Paris – France, 2027",
        "externalPath": "/job/Paris--France/Markets---Sales-and-Trading--Off-Cycle-Internship--Paris---France--2027_26992518",
        "locationsText": "Paris  France", "postedOn": "Posted 18 Days Ago", "bulletFields": ["26992518"]}]}
    detail = {"jobPostingInfo": {"title": "x", "jobDescription": "<p>six months starting in January 2027</p>",
                                 "location": "Paris  France", "startDate": "2026-09-21",
                                 "externalUrl": "https://citi.wd5.myworkdayjobs.com/2/job/abc"}}
    calls = []
    monkeypatch.setattr(net, "post_json", lambda url, payload, **k: calls.append((url, payload)) or listing)
    monkeypatch.setattr(net, "get_json", lambda url, **k: detail)
    items = ats.workday_list({"entreprise": "Citi (Citigroup)", "url": "https://citi.wd5.myworkdayjobs.com/2"}, ["markets intern"])
    assert calls[0][0] == "https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs"
    assert len(items) == 1 and items[0]["source_id"] == "Citi (Citigroup)|26992518"
    it = ats.workday_detail(items[0])
    assert it["posted_at"].startswith("2026-09-21")
    assert "January 2027" in it["description"]
    assert ats.workday_base("https://wf.wd1.myworkdayjobs.com/fr-FR/WellsFargoJobs")[0] == \
        "https://wf.wd1.myworkdayjobs.com/wday/cxs/wf/WellsFargoJobs"


def test_oracle(monkeypatch):
    data = {"items": [{"TotalJobsCount": 1, "requisitionList": [
        {"Id": "210795737", "Title": "2027 Markets - Off-Cycle Internship Program - Paris",
         "PrimaryLocation": "Paris, Ile-de-France, France", "PostedDate": "2026-10-05",
         "secondaryLocations": []}]}]}
    seen = []
    monkeypatch.setattr(net, "get_json", lambda url, **k: seen.append(url) or data)
    items = ats.oracle_list({"entreprise": "J.P. Morgan", "hote": "https://jpmc.fa.oraclecloud.com", "site": "CX_1001"},
                            ["internship"], pages=1)
    assert "finder=findReqs;siteNumber=CX_1001,limit=25,offset=0,keyword=%22internship%22,sortBy=RELEVANCY" in seen[0]
    assert items[0]["url"].endswith("/sites/CX_1001/job/210795737")
    assert items[0]["posted_at"].startswith("2026-10-05")
