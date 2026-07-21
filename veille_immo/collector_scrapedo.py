"""Collecte via l'API scrape.do : rendu JS + proxy résidentiel (Super) français
pour franchir DataDome. Récupère le HTML rendu et le parse avec la même logique
que le collecteur ScrapingBee (réutilise bd_parse).

Clé lue dans l'environnement : SCRAPER_API_KEY (le 'token' scrape.do).
Réglage 'super_proxy' : True (résidentiel, franchit DataDome, plus cher) ou
False (datacenter, ~coût minimal, mais souvent bloqué)."""
import os, re, time, requests
from .bd_parse import parse_cards

API = "https://api.scrape.do/"


def _fetch(url, token, super_proxy=True):
    params = {
        "token": token,
        "url": url,
        "render": "true",
        "geoCode": "fr",
        "waitSelector": "div.item.js_favoritesParent",
        "customWait": "3000",
    }
    if super_proxy:
        params["super"] = "true"      # proxy résidentiel (anti-DataDome)
    return requests.get(API, params=params, timeout=100)


def collect(sources, delay=4.0, api_key=None, super_proxy=None):
    token = api_key or os.environ.get("SCRAPER_API_KEY")
    if not token:
        raise RuntimeError("SCRAPER_API_KEY manquant")
    if super_proxy is None:
        super_proxy = os.environ.get("SCRAPER_SUPER", "true").lower() != "false"
    listings, errors, per_source = {}, [], {}
    for src in sources:
        recs, err = None, None
        for attempt in (1, 2):
            try:
                r = _fetch(src["url"], token, super_proxy)
                if r.status_code != 200:
                    err = f"{src['name']} : HTTP {r.status_code} scrape.do ({r.text[:80]})"
                    time.sleep(delay); continue
                title_m = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
                title = (title_m.group(1) if title_m else "").strip()
                exp = src.get("expect")
                if exp and exp.lower() not in title.lower():
                    err = f"{src['name']} : titre inattendu ('{title[:50]}') — source ignorée"
                    recs = None; break
                recs = parse_cards(r.text)
                if not recs:
                    err = f"{src['name']} : 0 annonce (page rendue mais vide)"
                    time.sleep(delay); continue
                err = None; break
            except Exception as e:
                err = f"{src['name']} : {type(e).__name__} {str(e)[:70]}"
                time.sleep(delay)
        n = 0
        if recs:
            for rec in recs:
                if rec["id"] not in listings:
                    listings[rec["id"]] = rec
            n = len(recs)
        else:
            errors.append(err)
        per_source[src["name"]] = n
        print(f"[scrapedo{'/super' if super_proxy else ''}] {src['name']}: {n} annonces"
              + (f" — {err}" if err else ""))
        time.sleep(delay)
    return list(listings.values()), errors, per_source
