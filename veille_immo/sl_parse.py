"""Parsing des cartes d'annonces SeLoger depuis du HTML rendu.

SeLoger et Belles Demeures sont deux façades du même back-office (groupe AVIV) et
partagent un seul espace d'identifiants : l'URL SeLoger d'un bien « luxe » redirige
vers bellesdemeures.com sous le même id. Les biens collectés ici se chaînent donc
nativement avec ceux du portail luxe, sans préfixe ni dédoublonnage particulier.
Belles Demeures n'expose que le haut de gamme ; SeLoger ouvre tout le segment
700 k–1,2 M €, invisible autrement.

Le rendu est une SPA React : pas de classes stables, mais des `data-testid`. Le
texte de carte porte tout le reste — « 945 000 € · 7 pièces · 5 chambres · 150 m² ·
217 m² de terrain · Pavé des Gardes, Chaville (92370) ».
"""
import re
from bs4 import BeautifulSoup

CARD = '[data-testid="serp-core-classified-card-testid"]'
AD = re.compile(r"/(\d{6,})\.htm")
# prix de vente : montant en € NON suivi de /m² (qui est le prix au mètre carré)
PRICE = re.compile(r"(\d[\d\s  ]{4,})\s*€(?!\s*/\s*m)")
# surface habitable : m² NON suivis de « de terrain »
SURF = re.compile(r"(\d{2,4}(?:[.,]\d{1,2})?)\s*m²(?!\s*de\s*terrain)")
ROOMS = re.compile(r"(\d{1,2})\s*pi[eè]ces?", re.I)
# « Pavé des Gardes, Chaville (92370) » ou « Chaville (92370) »
LOC = re.compile(r"([^·,]{2,40}),\s*([^·,(]{2,30}?)\s*\((\d{5})\)|([^·,(]{2,30}?)\s*\((\d{5})\)")
# Bruit précédant le lieu dans le texte de carte (« … 150 m² · 217 m² de terrain
# Pavé des Gardes »). Volontairement gourmand : on coupe au DERNIER jeton de bruit,
# sinon « 217 m² de terrain X » ne perd que « 217 m² ».
NOISE = re.compile(r"^.*(?:de\s*terrain|m²|€|·)\s*", re.S)


def _to_int(t):
    d = re.sub(r"[^\d]", "", t or "")
    return int(d) if d else None


UNITES = {"m²", "€", "·", "-"}


def _clean(s):
    s = NOISE.sub("", s or "").strip(" -–·")
    # Reliquats : le balisage coupe parfois un nombre en deux (« 13 » « 4 m² »), ce
    # qui laisse « 4 m² Chaville ». Un lieu ne commence jamais par un chiffre ou une
    # unité — et laisser passer ce bruit ferait une commune fantôme (identity.commune
    # prend le segment après la dernière virgule).
    mots = s.split()
    while mots and (re.search(r"\d", mots[0]) or mots[0] in UNITES):
        mots.pop(0)
    return " ".join(mots).strip(" -–·")


def _location(txt):
    """-> 'Quartier, Commune' (ou 'Commune' seule). '' si illisible."""
    m = LOC.search(txt)
    if not m:
        return ""
    # Les deux groupes sont nettoyés : une surface décimale (« 103,4 m² Chaville »)
    # fait passer la virgule pour le séparateur quartier/commune, et le bruit se
    # retrouve alors côté commune.
    if m.group(1):
        quartier, commune = _clean(m.group(1)), _clean(m.group(2))
    else:
        quartier, commune = "", _clean(m.group(4))
    # un « quartier » encore truffé de chiffres est un reliquat de la description
    if quartier and not re.search(r"\d", quartier):
        return f"{quartier}, {commune}"
    return commune


def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for card in soup.select(CARD):
        a = card.select_one('a[href*=".htm"]')
        if not a or not a.get("href"):
            continue
        href = a["href"].split("?")[0].split("#")[0]
        m = AD.search(href)
        if not m:
            continue
        cid = m.group(1)
        if cid in seen:
            continue
        seen.add(cid)
        url = href if href.startswith("http") else "https://www.seloger.com" + href
        full = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
        # le descriptif commence après l'accroche crédit ; à défaut, on prend tout
        desc = full.split("Simuler mon crédit immobilier", 1)[-1].strip()
        pm, sm, rm = PRICE.search(full), SURF.search(full), ROOMS.search(full)
        out.append({
            "id": cid, "url": url, "title": desc[:120],
            "price": _to_int(pm.group(1)) if pm else None,
            "surface": float(sm.group(1).replace(",", ".")) if sm else None,
            "rooms": int(rm.group(1)) if rm else None,
            "quartier": _location(full), "agency": "",
        })
    return out
