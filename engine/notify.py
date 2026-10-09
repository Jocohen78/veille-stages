"""Notifications sur téléphone via ntfy (https://ntfy.sh)."""
from __future__ import annotations

import os

import requests


def _send(server: str, topic: str, title: str, message: str, click: str | None = None, priority: int = 3,
          tags: str = "") -> bool:
    """Publication JSON (gère correctement les accents)."""
    payload = {"topic": topic, "title": title, "message": message, "priority": priority,
               "tags": [t for t in tags.split(",") if t]}
    if click:
        payload["click"] = click
    try:
        r = requests.post(server.rstrip("/") + "/", json=payload, timeout=20)
        return r.status_code < 300
    except requests.RequestException:
        return False


def describe(o: dict) -> str:
    bits = [o.get("role_type") or "Poste ?", " / ".join(o.get("desks") or []) or None, o.get("city") or o.get("location"),
            o.get("period_label")]
    if o.get("match_score") is not None:
        bits.append(f"{o['match_score']} % de match")
    return " · ".join(b for b in bits if b)


def notify_offers(conf: dict, events: list[tuple[str, dict]]) -> int:
    """events : liste de (type, offre) avec type ∈ {"nouvelle", "repost", "maj"}."""
    topic = os.environ.get("NTFY_TOPIC")
    ncfg = conf.get("notifications", {})
    if not ncfg.get("actif", True) or not topic or not events:
        return 0
    server = ncfg.get("serveur", "https://ntfy.sh")
    limit = int(ncfg.get("max_notifications_par_passage", 8))
    labels = {"nouvelle": ("Nouvelle offre", "new,briefcase"), "repost": ("Repost", "repeat,briefcase"),
              "maj": ("Offre mise à jour", "pencil,briefcase")}
    sent = 0
    # Les offres dont la période est compatible passent en premier
    events = sorted(events, key=lambda e: (e[1].get("period_fit") != "OK", e[0] != "nouvelle"))
    for kind, o in events[:limit]:
        label, tags = labels[kind]
        title = f"{label} : {o['company']} — {o['title']}"[:180]
        prio = 4 if o.get("period_fit") == "OK" else 3
        msg = describe(o) + "\nTouchez pour ouvrir l'offre."
        sent += _send(server, topic, title, msg, click=o.get("apply_url") or o.get("url"), priority=prio, tags=tags)
    rest = events[limit:]
    if rest:
        names = ", ".join(sorted({o["company"] for _, o in rest}))[:300]
        sent += _send(server, topic, f"+{len(rest)} autres offres", f"Entreprises : {names}\nVoir le dashboard.",
                      click=ncfg.get("url_dashboard") or None, tags="card_index")
    return sent


def notify_text(title: str, message: str, conf: dict) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        _send(conf.get("notifications", {}).get("serveur", "https://ntfy.sh"), topic, title, message, tags="warning")
