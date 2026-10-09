"""Stockage des offres : Supabase (production) ou fichier JSON local (tests / essai à blanc)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import requests

OFFER_COLUMNS = "*"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseStore:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        # Nouvelles clés "sb_secret_..." : en-tête apikey uniquement ; anciennes clés JWT : apikey + Bearer
        self.h = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):
            self.h["Authorization"] = f"Bearer {key}"

    def _get_all(self, table: str, select: str, query: str = "") -> list[dict]:
        rows, start, step = [], 0, 1000
        while True:
            r = requests.get(f"{self.base}/{table}?select={select}{query}",
                             headers={**self.h, "Range-Unit": "items", "Range": f"{start}-{start + step - 1}"}, timeout=60)
            r.raise_for_status()
            batch = r.json()
            rows += batch
            if len(batch) < step:
                return rows
            start += step

    def load_offers(self) -> list[dict]:
        return self._get_all("offers", OFFER_COLUMNS)

    def insert_offer(self, row: dict) -> dict:
        r = requests.post(f"{self.base}/offers", headers={**self.h, "Prefer": "return=representation"},
                          data=json.dumps(row, default=str), timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"Insertion refusée par Supabase : {r.status_code} {r.text[:300]}")
        return r.json()[0]

    def update_offer(self, offer_id: str, patch: dict) -> None:
        r = requests.patch(f"{self.base}/offers?id=eq.{offer_id}", headers=self.h,
                           data=json.dumps(patch, default=str), timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"Mise à jour refusée par Supabase : {r.status_code} {r.text[:300]}")

    def update_many(self, ids: list[str], patch: dict) -> None:
        for i in range(0, len(ids), 150):
            chunk = ",".join(ids[i:i + 150])
            r = requests.patch(f"{self.base}/offers?id=in.({chunk})", headers=self.h, data=json.dumps(patch, default=str),
                               timeout=60)
            r.raise_for_status()

    def log_run(self, row: dict) -> None:
        requests.post(f"{self.base}/runs", headers=self.h, data=json.dumps(row, default=str), timeout=30)

    def last_runs(self) -> dict[str, str]:
        """Dernière collecte réussie de chaque source."""
        rows = self._get_all("source_last_success", "source,last_ok")
        return {r["source"]: r["last_ok"] for r in rows}

    def pending_inbox(self) -> list[dict]:
        return self._get_all("inbox", "*", "&processed=is.false")

    def mark_inbox(self, inbox_id: str, patch: dict) -> None:
        requests.patch(f"{self.base}/inbox?id=eq.{inbox_id}", headers=self.h, data=json.dumps(patch, default=str),
                       timeout=30).raise_for_status()


class LocalStore:
    """Même interface, stockée dans un fichier JSON (essais sans Supabase)."""

    def __init__(self, path: str):
        self.path = path
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.db = json.load(f)
        else:
            self.db = {"offers": [], "runs": [], "inbox": []}

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.db, f, ensure_ascii=False, indent=1, default=str)

    def load_offers(self):
        return [dict(o) for o in self.db["offers"]]

    def insert_offer(self, row):
        row = dict(row)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("group_id", row["id"])
        row.setdefault("status", "Nouvelle")
        self.db["offers"].append(row)
        self.save()
        return dict(row)

    def update_offer(self, offer_id, patch):
        for o in self.db["offers"]:
            if o["id"] == offer_id:
                o.update(patch)
        self.save()

    def update_many(self, ids, patch):
        s = set(ids)
        for o in self.db["offers"]:
            if o["id"] in s:
                o.update(patch)
        self.save()

    def log_run(self, row):
        self.db["runs"].append(row)
        self.save()

    def last_runs(self):
        out = {}
        for r in self.db["runs"]:
            if r.get("ok"):
                out[r["source"]] = max(out.get(r["source"], ""), r["finished_at"])
        return out

    def pending_inbox(self):
        return [i for i in self.db["inbox"] if not i.get("processed")]

    def mark_inbox(self, inbox_id, patch):
        for i in self.db["inbox"]:
            if i["id"] == inbox_id:
                i.update(patch)
        self.save()


def make_store():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    return LocalStore(os.environ.get("LOCAL_DB", "local_db.json"))
