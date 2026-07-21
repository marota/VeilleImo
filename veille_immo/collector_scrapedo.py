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


def _title_ok(title, expect):
    """expect peut être une chaîne ou une liste : au moins un motif doit apparaître."""
    if not expect:
        return True
    pats = expect if isinstance(expect, (list, tuple)) else [expect]
    return any(str(x).lower() in title.lower() for x in pats)


def collect(sources, delay=4.0, api_key=None, super_proxy=None):
    """Collecte TOUTES les URL d'une source et fusionne (couverture garantie même
    si l'une des URL est redirigée vers la recherche nationale)."""
    token = api_key or os.environ.get("SCRAPER_API_KEY")
    if not token:
        raise RuntimeError("SCRAPER_API_KEY manquant")
    if super_proxy is None:
        super_proxy = os.environ.get("SCRAPER_SUPER", "true").lower() != "false"
    listings, errors, per_source = {}, [], {}
    for src in sources:
        got, urls = {}, (src.get("urls") or [src["url"]])
        for url_try in urls:
            recs, err = None, None
            for attempt in (1, 2):
                try:
                    r = _fetch(url_try, token, super_proxy)
                    if r.status_code != 200:
                        err = f"{src['name']} : HTTP {r.status_code} ({url_try[-40:]})"
                        time.sleep(delay); continue
                    tm = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
                    title = (tm.group(1) if tm else "").strip()
                    if not _title_ok(title, src.get("expect")):
                        err = f"{src['name']} : titre inattendu ('{title[:46]}') sur ...{url_try[-34:]}"
                        recs = None; break        # redirection : inutile de réessayer
                    recs = parse_cards(r.text)
                    if not recs:
                        err = f"{src['name']} : 0 annonce sur ...{url_try[-34:]}"
                        time.sleep(delay); continue
                    err = None; break
                except Exception as e:
                    err = f"{src['name']} : {type(e).__name__} {str(e)[:60]}"
                    time.sleep(delay)
            if recs:
                for rec in recs:
                    got.setdefault(rec["id"], rec)
            elif err:
                errors.append(err)
            time.sleep(delay)
        for rid, rec in got.items():
            listings.setdefault(rid, rec)
        per_source[src["name"]] = len(got)
        print(f"[scrapedo{'/super' if super_proxy else ''}] {src['name']}: {len(got)} annonces"
              + (f"  ({len(urls)} url)" if len(urls) > 1 else ""))
        time.sleep(delay)
    return list(listings.values()), errors, per_source
