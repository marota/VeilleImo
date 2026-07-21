"""Collecte via l'API ScrapingBee : rendu de la page depuis une IP résidentielle
française + mode stealth pour franchir DataDome. On récupère le HTML rendu puis
on l'analyse côté serveur (BeautifulSoup) avec la même logique que la collecte
navigateur (cartes div.item.js_favoritesParent : lieu, prix, surface, pièces, desc).

Clé lue dans l'environnement : SCRAPER_API_KEY (jamais en dur)."""
import os, re, time, requests
from .bd_parse import parse_cards

API = "https://app.scrapingbee.com/api/v1/"
AD = re.compile(r"/annonces/vente/([^/\"'?]+)/(\d{6,})/")
PRICE = re.compile(r"(\d[\d\s  ]{4,})\s*€")
SURF = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*m²")
ROOMS = re.compile(r"(\d{1,2})\s*Pi[eè]ces?", re.I)


def _to_int(t):
    d = re.sub(r"[^\d]", "", t or "")
    return int(d) if d else None


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


def _parse(html, name):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for card in soup.select("div.item.js_favoritesParent"):
        a = card.select_one('a[href*="/annonces/vente/"]')
        if not a or not a.get("href"):
            continue
        href = a["href"].split("?")[0].split("#")[0]
        m = AD.search(href)
        if not m:
            continue
        cid = m.group(2)
        if cid in seen:
            continue
        seen.add(cid)
        url = href if href.startswith("http") else "https://www.bellesdemeures.com" + href
        loc = (card.select_one(".location").get_text(" ", strip=True) if card.select_one(".location") else "")
        desc = (card.select_one(".desc").get_text(" ", strip=True) if card.select_one(".desc") else "")
        price_el = (card.select_one(".price").get_text(" ", strip=True) if card.select_one(".price") else "")
        full = card.get_text(" ", strip=True)
        price = _to_int((PRICE.search(price_el) or PRICE.search(full) or [None, None])[1]) if (PRICE.search(price_el) or PRICE.search(full)) else None
        sm = SURF.search(full)
        rm = ROOMS.search(full)
        out.append({
            "id": cid, "url": url, "title": re.sub(r"\s+", " ", desc)[:120], "price": price,
            "surface": float(sm.group(1).replace(",", ".")) if sm else None,
            "rooms": int(rm.group(1)) if rm else None,
            "quartier": re.sub(r"\s+", " ", loc), "agency": "",
        })
    return out


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
