"""Analyse de compatibilité CV / offre via l'API Anthropic.

MODULE DÉSACTIVÉ PAR DÉFAUT (config.yaml > analyse_ia > actif: false).
Pour l'activer :
  1. secret GitHub ANTHROPIC_API_KEY  (clé créée sur console.anthropic.com)
  2. secret GitHub CV_TEXT            (le texte de ton CV, copié-collé)
  3. passer `actif: true` dans config.yaml
"""
from __future__ import annotations

import json
import os
import re

import requests

API_URL = "https://api.anthropic.com/v1/messages"

PROMPT = """Tu es un recruteur expérimenté en salle des marchés (sales, trading, structuring, risk, middle office).
Compare le CV du candidat avec l'offre de stage, et réponds UNIQUEMENT avec un objet JSON, sans texte autour :
{{
  "score": <entier 0-100, adéquation globale du profil à l'offre>,
  "fiabilite": "<haute|moyenne|faible>  (faible si l'offre est très courte ou vague)",
  "points_forts": ["<3 à 5 points concrets du CV qui correspondent à l'offre>"],
  "ecarts": ["<0 à 5 exigences de l'offre que le CV ne montre pas>"],
  "mots_cles_manquants": ["<mots-clés de l'offre absents du CV, utiles pour adapter CV/lettre>"],
  "resume": "<une phrase de synthèse en français>"
}}

<cv>
{cv}
</cv>

<offre>
Entreprise : {company}
Intitulé : {title}
Lieu : {location}
Description :
{description}
</offre>"""


def is_enabled(conf: dict) -> bool:
    c = conf.get("analyse_ia", {})
    return bool(c.get("actif")) and bool(os.environ.get("ANTHROPIC_API_KEY")) and bool(cv_text())


def cv_text() -> str:
    txt = os.environ.get("CV_TEXT", "")
    if not txt and os.path.exists("cv.txt"):
        with open("cv.txt", encoding="utf-8") as f:
            txt = f.read()
    return txt.strip()


def analyze(offer: dict, conf: dict) -> dict | None:
    model = conf.get("analyse_ia", {}).get("modele", "claude-haiku-5-5")
    prompt = PROMPT.format(cv=cv_text()[:8000], company=offer.get("company"), title=offer.get("title"),
                           location=offer.get("location"), description=(offer.get("description") or "")[:9000])
    r = requests.post(API_URL, timeout=90, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]})
    if r.status_code >= 300:
        raise RuntimeError(f"API Anthropic : {r.status_code} {r.text[:200]}")
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    data = json.loads(m.group(0))
    return {
        "match_score": max(0, min(100, int(data.get("score", 0)))),
        "match_confidence": data.get("fiabilite"),
        "match_strengths": data.get("points_forts") or [],
        "match_gaps": data.get("ecarts") or [],
        "match_keywords": data.get("mots_cles_manquants") or [],
        "match_summary": data.get("resume"),
    }
