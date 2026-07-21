"""Parsing des cartes d'annonces Belles Demeures depuis du HTML rendu."""
import re
from bs4 import BeautifulSoup

AD = re.compile(r"/annonces/vente/([^/\"'?]+)/(\d{6,})/")
PRICE = re.compile(r"(\d[\d\s  ]{4,})\s*€")
SURF = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*m²")
ROOMS = re.compile(r"(\d{1,2})\s*Pi[eè]ces?", re.I)


def _to_int(t):
    d = re.sub(r"[^\d]", "", t or "")
    return int(d) if d else None


def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for card in soup.select("div.item.js_favoritesParent"):
        a = card.select_one('a[href*="/annonces/vente/"]')
        if not a or not a.get("href"):
            continue
        m = AD.search(a["href"].split("?")[0].split("#")[0])
        if not m:
            continue
        cid = m.group(2)
        if cid in seen:
            continue
        seen.add(cid)
        href = a["href"].split("?")[0]
        url = href if href.startswith("http") else "https://www.bellesdemeures.com" + href
        loc = card.select_one(".location").get_text(" ", strip=True) if card.select_one(".location") else ""
        desc = card.select_one(".desc").get_text(" ", strip=True) if card.select_one(".desc") else ""
        price_el = card.select_one(".price").get_text(" ", strip=True) if card.select_one(".price") else ""
        full = card.get_text(" ", strip=True)
        pm = PRICE.search(price_el) or PRICE.search(full)
        sm = SURF.search(full)
        rm = ROOMS.search(full)
        out.append({
            "id": cid, "url": url, "title": re.sub(r"\s+", " ", desc)[:120],
            "price": _to_int(pm.group(1)) if pm else None,
            "surface": float(sm.group(1).replace(",", ".")) if sm else None,
            "rooms": int(rm.group(1)) if rm else None,
            "quartier": re.sub(r"\s+", " ", loc), "agency": "",
        })
    return out
