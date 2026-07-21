"""Collecte directe sur les sites d'agences locales (hors portail).

Beaucoup d'agences publient leurs biens sur leur propre site avant (ou sans) les
portails : c'est là que se trouvent les exclusivités et les avant-premières.
Ces sites sont en HTML simple, sans anti-robot → collecte gratuite (pas de crédit
scrape.do) via requests.

Principe générique : sur une page de liste, chaque annonce est un LIEN dont le
texte contient à la fois un prix (€) et une surface (m²). On extrait depuis ce
texte : commune, quartier, titre, surface, pièces, prix. Ajouter une agence =
3 lignes de config (pas de code).
"""
import re, time, requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PRICE = re.compile(r"(\d[\d\s  ]{4,})\s*€")
# surface "collée" au prix : '230m² - 2 000 000 €'  (évite de capter le terrain)
SURF_NEAR = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*m²\s*[-–]\s*\d[\d\s  ]{4,}\s*€")
SURF_ANY = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*m²")
ROOMS = re.compile(r"(\d{1,2})\s*pi[eè]ces?", re.I)

COMMUNES = {
    "VILLE D AVRAY": "Ville-d'Avray", "VILLE-D'AVRAY": "Ville-d'Avray",
    "SEVRES": "Sèvres", "SÈVRES": "Sèvres", "MEUDON": "Meudon",
    "CHAVILLE": "Chaville", "VIROFLAY": "Viroflay", "SAINT-CLOUD": "Saint-Cloud",
    "SAINT CLOUD": "Saint-Cloud",
}
QUARTIERS = ["Bellevue", "Brancas", "Rive Gauche", "Rive Droite", "Croix Bosset",
             "Val Fleury", "Centre", "Cote d'Argent", "Côte d'Argent", "Musée Rodin",
             "Château", "Etangs", "Étangs"]


def _to_int(t):
    d = re.sub(r"[^\d]", "", t or "")
    return int(d) if d else None


def _parse_link(text, href, base):
    """Extrait une annonce depuis le texte d'un lien de liste. None si non exploitable."""
    txt = re.sub(r"\s+", " ", text or "").strip()
    pm = PRICE.search(txt)
    if not pm:
        return None
    sm = SURF_NEAR.search(txt) or SURF_ANY.search(txt)
    if not sm:
        return None
    commune = next((v for k, v in COMMUNES.items() if k in txt.upper()), "")
    quartier = next((q for q in QUARTIERS if q.lower() in txt.lower()), "")
    loc = f"{quartier}, {commune}" if quartier and commune else (commune or "")
    rm = ROOMS.search(txt)
    url = href if href.startswith("http") else base.rstrip("/") + "/" + href.lstrip("/")
    return {
        "url": url.split("?")[0],
        "title": re.sub(r"^D[ée]couvrir\s+", "", txt)[:120],
        "price": _to_int(pm.group(1)),
        "surface": float(sm.group(1).replace(",", ".")),
        "rooms": int(rm.group(1)) if rm else None,
        "quartier": loc,
    }


def _card_text(a, max_up=6):
    """Remonte au plus petit conteneur contenant à la fois un prix et une surface.
    Gère les deux gabarits : prix dans le texte du lien, ou prix dans la carte."""
    node = a
    for _ in range(max_up):
        txt = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "")
        if PRICE.search(txt) and SURF_ANY.search(txt) and len(txt) < 2000:
            return txt
        if node.parent is None:
            break
        node = node.parent
    return None


def _scan_site(src):
    """src: {name, agency, base, urls[], href_filter, id_regex, commune_default}"""
    out, seen = [], set()
    href_filter = re.compile(src["href_filter"]) if src.get("href_filter") else None
    id_re = re.compile(src.get("id_regex", r"(\d{5,})"))
    for url in src["urls"]:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"},
                         timeout=45)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href_filter and not href_filter.search(href):
                continue
            m = id_re.search(href)
            if not m or f"{src['name']}_{m.group(1)}" in seen:
                continue
            txt = _card_text(a)
            if not txt:
                continue
            rec = _parse_link(txt, href, src["base"])
            if not rec:
                continue
            if not rec["quartier"] and src.get("commune_default"):
                rec["quartier"] = src["commune_default"]
            rec["id"] = f"{src['name']}_{m.group(1)}"
            rec["agency"] = src.get("agency", src["name"])
            seen.add(rec["id"])
            out.append(rec)
        time.sleep(1.5)
    return out


def collect(sources, delay=2.0):
    listings, errors, per_source = {}, [], {}
    for src in sources:
        n = 0
        try:
            recs = _scan_site(src)
            for rec in recs:
                if rec["id"] not in listings:
                    listings[rec["id"]] = rec
            n = len(recs)
            if not recs:
                errors.append(f"{src['name']} : 0 annonce extraite")
        except Exception as e:
            errors.append(f"{src['name']} : {type(e).__name__} {str(e)[:70]}")
        per_source[src["name"]] = n
        print(f"[agence] {src['name']}: {n} annonces")
        time.sleep(delay)
    return list(listings.values()), errors, per_source
