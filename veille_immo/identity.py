"""Identité d'un bien indépendante de l'ID d'annonce (chaînage anti-republication).

Un même bien peut réapparaître sous un NOUVEL identifiant Belles Demeures
(changement d'agence, retrait/republication, baisse de prix relancée).
Comparer par ID seul le compte alors comme « nouveau » à tort.

On construit une EMPREINTE robuste en croisant quatre signaux :
  - lieu       : commune extraite du quartier (signal dur : doit correspondre)
  - surface    : à ± SURF_TOL m² près (signal dur)
  - pièces     : à ± 1 près (signal dur, si connu des deux côtés)
  - prix       : à ± PRICE_TOL % près  (signal de confirmation, tolérant : le
                 prix peut baisser à la republication)
  - description: recouvrement de mots-clés significatifs (signal de confirmation)

Deux annonces sont réputées « même bien » si les signaux durs concordent ET
qu'au moins un signal de confirmation (prix proche OU description proche) valide.
"""
import re
import unicodedata
from typing import List

SURF_TOL = 2.0        # m²
PRICE_TOL = 0.02      # "prix quasi identique" -> confirme à lui seul
PRICE_MAX_GAP = 0.08  # au-delà : ce ne peut PAS être le même bien (garde-fou dur)      # 6 %
JACCARD_MIN = 0.34    # recouvrement min. des mots-clés de description
ROOMS_TOL = 1

_STOP = set("""de la le les des du un une et a au aux en dans sur pour par avec sans
ce cette ces son sa ses vous votre nous notre est sont plus tres tout toute cet
proche pres entre chez rue avenue boulevard place quartier maison villa bien
propriete demeure vente vends propose exclusivite exclusiv, m2 environ""".split())

_NOISE = ["exclusivite", "votre consultant", "iad france", "barnes", "sous compromis",
          "sous-offre acceptee", "sous offre acceptee", "coup de coeur de l agence",
          "vous propose", "a le plaisir", "decouvrez", "rare", "notaire vend"]


def _strip(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    return _strip((s or "").lower()).strip()


def commune(quartier: str) -> str:
    """Commune = segment après la dernière virgule ('Père Komitas, Chaville' -> 'chaville')."""
    q = norm(quartier)
    if "," in q:
        q = q.rsplit(",", 1)[-1]
    return q.strip()


def desc_tokens(title: str) -> set:
    t = norm(title)
    for n in _NOISE:
        t = t.replace(n, " ")
    words = re.findall(r"[a-z0-9]+", t)
    return {w for w in words if len(w) > 3 and w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fingerprint(listing) -> str:
    """Clé grossière de regroupement des candidats (commune|surface arrondie|pièces)."""
    surf = round(listing.surface) if listing.surface else 0
    return f"{commune(listing.quartier)}|{surf}|{listing.rooms or 0}"


def same_property(a, b) -> bool:
    """Vrai si a et b désignent (très probablement) le même bien physique.

    Le PRIX est un garde-fou DUR : au-delà de PRICE_MAX_GAP d'écart, deux annonces
    ne peuvent pas décrire le même bien, même si la description se ressemble
    (titres courts et génériques -> faux positifs, et fausses "baisses" ensuite).
    """
    if commune(a.quartier) != commune(b.quartier):
        return False
    if a.surface and b.surface and abs(a.surface - b.surface) > SURF_TOL:
        return False
    if a.rooms and b.rooms and abs(a.rooms - b.rooms) > ROOMS_TOL:
        return False
    if a.price and b.price:
        gap = abs(a.price - b.price) / max(a.price, b.price)
        if gap > PRICE_MAX_GAP:
            return False                      # écart de prix rédhibitoire
        if gap <= PRICE_TOL:
            return True                       # prix quasi identique = même bien
        # Prix proche mais pas identique (honoraires, négociation, republication) :
        # on accepte si la STRUCTURE colle exactement (surface ~1 m² et mêmes pièces),
        # sinon on exige une description concordante.
        if (a.surface and b.surface and abs(a.surface - b.surface) <= 1.0
                and a.rooms and b.rooms and a.rooms == b.rooms):
            return True
    return _jaccard(desc_tokens(a.title), desc_tokens(b.title)) >= JACCARD_MIN


def cluster(listings: List) -> List[List]:
    """Regroupe une liste d'annonces en biens uniques (union-find sur same_property).

    On ne compare qu'à l'intérieur d'un même bucket d'empreinte (commune|surface|pièces),
    en élargissant la surface de ±SURF_TOL pour couvrir les arrondis limites.
    """
    items = list(listings)
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    # index par (commune, pièces) puis comparaison surface-proche
    from collections import defaultdict
    # Regroupement par COMMUNE seule : le nombre de pièces varie d'un diffuseur à
    # l'autre (7 vs 8 pour le même bien), or same_property tolère ±1 pièce. Bucketer
    # sur (commune, pièces) empêchait ces fusions. O(n²) par commune = négligeable ici.
    buckets = defaultdict(list)
    for idx, l in enumerate(items):
        buckets[commune(l.quartier)].append(idx)
    for _, idxs in buckets.items():
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                if same_property(items[idxs[x]], items[idxs[y]]):
                    union(idxs[x], idxs[y])

    groups = defaultdict(list)
    for idx in range(len(items)):
        groups[find(idx)].append(items[idx])
    return list(groups.values())
