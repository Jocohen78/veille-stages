"""Client HTTP commun : en-têtes de navigateur, réessais, délais."""
from __future__ import annotations

import random
import time

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
})


class FetchError(Exception):
    pass


def request(method: str, url: str, *, retries: int = 2, timeout: int = 25, **kw) -> requests.Response:
    last = None
    for attempt in range(retries + 1):
        try:
            r = _session.request(method, url, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(3 * (attempt + 1) + random.random())
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} sur {url[:120]}")
            return r
        except requests.RequestException as e:  # réseau
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise FetchError(f"Échec réseau sur {url[:120]} : {last}")


def get_json(url: str, **kw):
    kw.setdefault("headers", {})["Accept"] = "application/json"
    return request("GET", url, **kw).json()


def post_json(url: str, payload: dict, **kw):
    headers = kw.pop("headers", {})
    headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return request("POST", url, json=payload, headers=headers, **kw).json()


def get_text(url: str, **kw) -> str:
    return request("GET", url, **kw).text
