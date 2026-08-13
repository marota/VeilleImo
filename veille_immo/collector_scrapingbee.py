"""Collecte via l'API ScrapingBee : rendu de la page depuis une IP résidentielle
française + mode stealth pour franchir DataDome. Le HTML rendu est analysé par
`bd_parse.parse_cards` (BeautifulSoup, cartes div.item.js_favoritesParent) — le même
code que les autres collecteurs, donc la même lecture de prix : c'est ce qui garantit
qu'un changement de provider ne change pas les montants collectés.

Clé lue dans l'environnement : SCRAPER_API_KEY (jamais en dur)."""
import os, re, time, requests
from .bd_parse import parse_cards

API = "https://app.scrapingbee.com/api/v1/"


def _fetch(url, api_key, wait_for="div.item.js_favoritesParent"):
    params = {
        "api_key": api_key,
        "url": url,
        "stealth_proxy": "true",     # proxy résidentiel + anti-DataDome
        "country_code": "fr",
        "wait_for": wait_for,        # attend le rendu des cartes
        "wait": "3000",
        "timeout": "20000",
    }
    return requests.get(API, params=params, timeout=100)


def collect(sources, delay=4.0, api_key=None):
    api_key = api_key or os.environ.get("SCRAPER_API_KEY")
    if not api_key:
        raise RuntimeError("SCRAPER_API_KEY manquant")
    listings, errors, per_source = {}, [], {}
    for src in sources:
        recs, err = None, None
        for attempt in (1, 2):
            try:
                r = _fetch(src["url"], api_key)
                if r.status_code != 200:
                    err = f"{src['name']} : HTTP {r.status_code} ScrapingBee ({r.text[:80]})"
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
        print(f"[bee] {src['name']}: {n} annonces" + (f" — {err}" if err else ""))
        time.sleep(delay)
    return list(listings.values()), errors, per_source
