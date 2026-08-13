"""Lecture et contrôle de sanité des prix affichés sur les cartes d'annonces.

Les cartes des portails commencent par le compteur du carrousel de photos
(« 1 / 11 »), parfois suivi d'un badge (« Nouveau ») et de la lettre DPE. Quand le
compteur est directement collé au prix — « 1 / 11 950 000 € » — une regex de prix
naïve démarre sur le second nombre du compteur et lit 11 950 000 € au lieu de
950 000 €. Le prix pollué se propage ensuite partout : état persistant, moyennes
de zone, mouvements (+1 629 % au scan suivant).

D'où deux garde-fous complémentaires, appliqués dans cet ordre :
  1. on consomme le compteur AVANT de chercher le prix (`strip_photo_counter`) ;
  2. tout prix restant au-dessus d'un plafond résidentiel raisonnable est refusé
     (`is_sane`), plutôt que d'être stocké et cru sur parole.
"""
import os
import re

# Espaces fines/insécables : les portails séparent les milliers avec l'un ou l'autre.
_ESP = " \u00a0\u202f\u2009"   # espace, insécable, fine insécable, fine

# Compteur de carrousel « 1 / 11 » UNIQUEMENT quand un nombre le suit directement :
# c'est le seul cas nuisible, et le seul où l'on peut retirer sans risque. « 1 / 17
# Nouveau C 1 100 000 € » n'est pas touché (la regex de prix ne peut pas y démarrer
# sur « 17 »), pas plus qu'un « €/m² » (le / y est précédé d'un €) ni qu'une date
# (« 13/08/2026 » : le second nombre a quatre chiffres).
COUNTER = re.compile(rf"(?<![\d/.,])\d{{1,3}}\s*/\s*\d{{1,3}}(?![\d/])(?=[{_ESP}]+\d)")

# Prix de vente : montant en € NON suivi de /m² (qui est le prix au mètre carré).
# La borne gauche refuse un chiffre collé devant (« …14 1 190 000 € ») : sans elle,
# la capture démarrerait au premier chiffre venu et gonflerait le montant.
PRICE = re.compile(rf"(?<![\d/.,])(\d[\d{_ESP}]{{4,}})\s*€(?!\s*/\s*m)")

# Regex d'AVANT le correctif, conservée pour reconnaître sa signature dans un état
# déjà écrit : si elle reproduit exactement le prix stocké alors que la regex
# corrigée en lit un autre, ce prix vient bien du bug — et pas d'une médiane
# multi-mandats ni d'un bien réellement cher.
_LEGACY_PRICE = re.compile(rf"(\d[\d{_ESP}]{{4,}})\s*€(?!\s*/\s*m)")

PRICE_SANITY_MAX = 5_000_000   # plafond résidentiel IdF : au-delà, on suspecte le parsing
PRICE_MIN = 700_000            # bas du budget (cf. report_html.CRIT)
PRICE_MAX = 1_200_000          # haut du budget, borne INCLUSE
DELTA_MAX_PCT = 20.0           # variation de prix au-delà de laquelle on suspecte une anomalie


def _env_num(nom, defaut, cast=int):
    """Lit une variable d'environnement numérique ; ignore une valeur illisible."""
    brut = os.environ.get(nom)
    if brut is None or not str(brut).strip():
        return defaut
    try:
        return cast(str(brut).strip().replace(" ", "").replace("_", ""))
    except ValueError:
        print(f"[veille] {nom}='{brut}' illisible — valeur par défaut {defaut}")
        return defaut


def sanity_max():
    """Plafond de plausibilité d'un prix (VEILLEIMO_PRICE_SANITY_MAX)."""
    return _env_num("VEILLEIMO_PRICE_SANITY_MAX", PRICE_SANITY_MAX)


def price_max():
    """Haut du budget, borne INCLUSE (VEILLEIMO_PRICE_MAX)."""
    return _env_num("VEILLEIMO_PRICE_MAX", PRICE_MAX)


def price_min():
    """Bas du budget, borne INCLUSE (VEILLEIMO_PRICE_MIN)."""
    return _env_num("VEILLEIMO_PRICE_MIN", PRICE_MIN)


def delta_max_pct():
    """Variation de prix maximale considérée comme normale (VEILLEIMO_DELTA_MAX_PCT)."""
    return _env_num("VEILLEIMO_DELTA_MAX_PCT", DELTA_MAX_PCT, float)


def is_sane(price):
    """Un prix nul/absent n'est pas une anomalie : seul un montant hors plafond l'est."""
    return not price or price <= sanity_max()


def in_budget(price, pmin=None, pmax=None):
    """Prix dans le budget, bornes INCLUSES. Un prix inconnu n'y est jamais."""
    if not price:
        return False
    lo = price_min() if pmin is None else pmin
    hi = price_max() if pmax is None else pmax
    return lo <= price <= hi


def strip_photo_counter(text):
    """Retire le compteur de carrousel collé devant un nombre (« 1 / 11 950 000 € »)."""
    return COUNTER.sub("", text or "")


def to_int(t):
    d = re.sub(r"[^\d]", "", t or "")
    return int(d) if d else None


def parse_price(text):
    """Prix de vente lu dans un texte de carte, ou None. Le compteur est consommé
    d'abord : c'est ce qui distingue « 1 / 11 950 000 € » (950 000) de « 11 950 000 € »."""
    m = PRICE.search(strip_photo_counter(text))
    return to_int(m.group(1)) if m else None


def repair_price(price, title):
    """Prix d'un bien déjà stocké -> (prix, statut).

    Deux façons de reconnaître un prix pollué :
      - il porte la signature du bug (l'ancienne regex le reproduit à l'identique
        depuis le libellé, la nouvelle en lit un autre) — c'est le cas sûr, même
        sous le plafond (« 1 / 3 911 000 € » stocké 3 911 000 au lieu de 911 000) ;
      - à défaut, il dépasse le plafond de plausibilité.

    statut : 'ok' (rien à faire), 'corrige' (relu depuis le libellé, valeur plausible),
    'suspect' (hors plafond et non réparable — la valeur est conservée telle quelle,
    à revérifier à la main : un bien réel très cher n'est pas un prix pollué)."""
    relu = parse_price(title or "")
    if relu and relu != price:
        ancien = _LEGACY_PRICE.search(title or "")
        if ancien and to_int(ancien.group(1)) == price:
            return relu, "corrige"
    if is_sane(price):
        return price, "ok"
    if relu and is_sane(relu):
        return relu, "corrige"
    return price, "suspect"


def migrate_properties(props):
    """Nettoie en place les prix pollués d'une liste de biens de l'état persistant.

    -> (corrigés, suspects). Les biens ne sont jamais supprimés : un prix hors
    plafond mais réel (villa à 5,2 M €) est seulement marqué `price_suspect`."""
    fixed = flagged = 0
    for p in props or []:
        neuf, statut = repair_price(p.get("price"), p.get("title"))
        if statut == "corrige":
            print(f"[veille] prix corrigé [{p.get('canonical_id')}] "
                  f"{p['price']} -> {neuf} ({(p.get('title') or '')[:40]})")
            p["price"] = neuf
            p.pop("price_suspect", None)
            fixed += 1
        elif statut == "suspect":
            if not p.get("price_suspect"):
                print(f"[veille] prix à revérifier [{p.get('canonical_id')}] {p.get('price')}")
            p["price_suspect"] = True
            flagged += 1
        else:
            p.pop("price_suspect", None)
    return fixed, flagged


# Nettoyage du libellé affiché -------------------------------------------------
# Le texte de carte agrège tout ce qui n'a pas de balise propre : compteur, badge,
# DPE, prix, prix/m², puis seulement la description. Les colonnes du rapport
# portent déjà prix et surface — les répéter dans la cellule « Bien » la rend
# illisible (« 1 / 14 D 1 200 000 € 4 762 €/m² Maison à vendre 8 pièces »).
_TETE = re.compile(
    rf"^[{_ESP}]*(?:\d{{1,3}}\s*/\s*\d{{1,3}}[{_ESP}]*)?"          # compteur du carrousel
    rf"(?:(?:nouveau|exclusivit[ée]|coup de c(?:oe|œ)ur)[{_ESP}]*)*"  # badges
    rf"(?:[A-G](?=[{_ESP}]+\d[\d{_ESP}]{{3,}}\s*€)[{_ESP}]*)?",    # lettre DPE devant le prix
    re.I)
_MONTANT = re.compile(rf"\d[\d{_ESP}]*\s*€(?:\s*/\s*m²)?", re.I)
_SURF_PRIX = re.compile(rf"\d+(?:[.,]\d+)?\s*m²\s*[-–]\s*(?=\d)")   # « 230m² - 2 000 000 € »


def clean_title(text):
    """Libellé lisible : sans compteur, badge, DPE ni montants (ils ont leur colonne)."""
    t = _TETE.sub("", text or "", count=1)
    t = _SURF_PRIX.sub(" ", t)      # « 230m² - 2 000 000 € » : la surface a sa colonne
    t = _MONTANT.sub(" ", t)
    t = re.sub(rf"[{_ESP}\s]+", " ", t)
    return t.strip(" -–·,")
