"""Chaînage des scans au niveau BIEN (et non annonce), anti-republication.

Un bien = un cluster d'annonces (voir identity.cluster). L'état persistant
stocke, par bien : un id canonique, la liste des id-alias rencontrés, l'empreinte,
la date de première apparition (first_seen) et le dernier prix vu.

Au scan suivant, chaque bien courant est rattaché à un bien connu :
  1. par recouvrement d'ID (un alias déjà vu), sinon
  2. par identity.same_property (republication sous nouvel ID).
Le first_seen est alors conservé ; sinon le bien est NOUVEAU (first_seen = aujourd'hui).
"""
from typing import Dict, List
from . import identity

MIN_PCT = 2.0     # variation de prix minimale signalée (%)
MIN_EUR = 5000    # et en euros
from .models import Listing


def _idkey(x):
    """Tri robuste : ids numériques (portail) et alphanumériques (agences)."""
    xs = str(x)
    return (0, int(xs), "") if xs.isdigit() else (1, 0, xs)


def _canonical(group: List[Listing]) -> Listing:
    # annonce au plus petit id = la plus ancienne (id séquentiels)
    return min(group, key=lambda l: _idkey(l.id))


def build_properties(listings: List[Listing]) -> List[dict]:
    props = []
    for grp in identity.cluster(listings):
        c = _canonical(grp)
        prices = [l.price for l in grp if l.price]
        props.append({
            "canonical_id": c.id,
            "aliases": sorted({l.id for l in grp}, key=_idkey),
            "fingerprint": identity.fingerprint(c),
            "commune": identity.commune(c.quartier),
            "quartier": c.quartier,
            "title": c.title,
            "url": c.url,
            "surface": c.surface,
            "rooms": c.rooms,
            "price": (prices[len(prices) // 2] if prices else None),   # médiane, robuste
            "n_mandats": len(grp),
        })
    return props


def _find_prior(prop: dict, prev: List[dict], prev_listings: Dict[str, Listing]):
    # 1) recouvrement d'ID (alias déjà connu)
    alias_set = set(prop["aliases"])
    for p in prev:
        if alias_set & set(p.get("aliases", [])):
            return p
    # 2) même bien par empreinte floue (republication)
    a = Listing(id=prop["canonical_id"], source="", title=prop["title"],
                price=prop["price"], surface=prop["surface"],
                rooms=prop["rooms"], quartier=prop["quartier"])
    for p in prev:
        b = Listing(id=p["canonical_id"], source="", title=p.get("title", ""),
                    price=p.get("price"), surface=p.get("surface"),
                    rooms=p.get("rooms"), quartier=p.get("quartier", ""))
        if identity.same_property(a, b):
            return p
    return None


def chain(curr_props: List[dict], prev_props: List[dict], today: str) -> List[dict]:
    """Fusionne l'état courant avec l'état précédent en conservant first_seen."""
    out = []
    matched_prev = set()
    for prop in curr_props:
        prior = _find_prior(prop, prev_props, {})
        if prior is not None:
            matched_prev.add(id(prior))
            prop["first_seen"] = prior.get("first_seen", today)
            prop["first_seen_estimated"] = prior.get("first_seen_estimated", False)
            prop["aliases"] = sorted(set(prop["aliases"]) | set(prior.get("aliases", [])), key=_idkey)
            prop["price_prev"] = prior.get("price")
        else:
            prop["first_seen"] = today
            prop["first_seen_estimated"] = False
            prop["price_prev"] = None
        out.append(prop)
    return out


def diff_properties(curr: List[dict], prev: List[dict]) -> List[dict]:
    events = []
    prev_by_alias = {}
    for p in prev:
        for a in p.get("aliases", []):
            prev_by_alias[a] = p
    seen_prev = set()
    for prop in curr:
        prior = None
        for a in prop["aliases"]:
            if a in prev_by_alias:
                prior = prev_by_alias[a]; break
        if prior is None:
            prior = _find_prior(prop, prev, {})
        if prior is None:
            events.append({"type": "NOUVEAU", "id": prop["canonical_id"],
                           "title": prop["title"], "price": prop["price"]})
        else:
            seen_prev.add(prior["canonical_id"])
            op, np_ = prior.get("price"), prop.get("price")
            if op and np_ and op != np_:
                events.append({"type": "BAISSE" if np_ < op else "HAUSSE",
                               "id": prop["canonical_id"], "title": prop["title"],
                               "old_price": op, "price": np_,
                               "pct": round(100 * (np_ - op) / op, 1)})
    curr_aliases = set()
    for prop in curr:
        curr_aliases |= set(prop["aliases"])
    for p in prev:
        # présent si un alias subsiste OU si un bien courant lui correspond
        # (republication sous nouvel ID : ce n'est pas un retrait)
        if set(p.get("aliases", [])) & curr_aliases:
            continue
        if p["canonical_id"] in seen_prev:
            continue
        events.append({"type": "RETIRE", "id": p["canonical_id"],
                       "title": p.get("title", ""), "price": p.get("price")})
    return events


def _match_prior(prop, prev, used):
    alias_set = set(prop["aliases"])
    for p in prev:
        if id(p) in used:
            continue
        if alias_set & set(p.get("aliases", [])):
            return p
    a = Listing(id=prop["canonical_id"], source="", title=prop["title"], price=prop["price"],
                surface=prop["surface"], rooms=prop["rooms"], quartier=prop["quartier"])
    for p in prev:
        if id(p) in used:
            continue
        b = Listing(id=p["canonical_id"], source="", title=p.get("title", ""), price=p.get("price"),
                    surface=p.get("surface"), rooms=p.get("rooms"), quartier=p.get("quartier", ""))
        if identity.same_property(a, b):
            return p
    return None


def scan_grace(curr_props, prev_props, today, failed_communes=(), grace=2):
    """Chaînage FIABLE : hystérésis sur les retraits + gel des communes non collectées.

    - un bien courant retrouvé => conservé, misses=0, first_seen préservé ;
    - un bien courant inconnu => NOUVEAU (first_seen=today) ;
    - un bien précédent absent :
        * si sa commune n'a pas été collectée (source en échec) => gelé (conservé, inchangé) ;
        * sinon misses += 1 ; RETIRÉ seulement quand misses >= grace, sinon conservé « en sursis ».
    Retourne (nouvel_état, événements)."""
    failed = {identity.commune(c) if "," in c or " " in c else c for c in failed_communes}
    events, used, out = [], set(), []
    for cp in curr_props:
        prior = _match_prior(cp, prev_props, used)
        if prior is None:
            cp["first_seen"] = today; cp["first_seen_estimated"] = False
            cp["last_seen"] = today; cp["misses"] = 0
            events.append({"type": "NOUVEAU", "id": cp["canonical_id"], "title": cp["title"], "price": cp["price"]})
        else:
            used.add(id(prior))
            cp["first_seen"] = prior.get("first_seen", today)
            cp["first_seen_estimated"] = prior.get("first_seen_estimated", False)
            cp["last_seen"] = today; cp["misses"] = 0
            cp["aliases"] = sorted(set(cp["aliases"]) | set(prior.get("aliases", [])), key=_idkey)
            op, np_ = prior.get("price"), cp.get("price")
            if op and np_ and op != np_:
                pct = round(100 * (np_ - op) / op, 1)
                # seuil anti-bruit : on ignore les micro-variations (arrondis, honoraires)
                if abs(pct) >= MIN_PCT and abs(np_ - op) >= MIN_EUR:
                    events.append({"type": "BAISSE" if np_ < op else "HAUSSE",
                                   "id": cp["canonical_id"], "title": cp["title"],
                                   "old_price": op, "price": np_, "pct": pct,
                                   "url": cp.get("url", ""), "surface": cp.get("surface"),
                                   "rooms": cp.get("rooms"), "commune": cp.get("commune", ""),
                                   "n_mandats": cp.get("n_mandats", 1)})
        out.append(cp)
    for pp in prev_props:
        if id(pp) in used:
            continue
        commune = identity.commune(pp.get("quartier", "")) or pp.get("commune", "")
        if commune in failed:                       # source en échec => on gèle
            out.append(pp); continue
        misses = pp.get("misses", 0) + 1
        if misses >= grace:                          # retrait CONFIRMÉ
            events.append({"type": "RETIRE", "id": pp["canonical_id"],
                           "title": pp.get("title", ""), "price": pp.get("price")})
        else:                                        # en sursis : conservé, non signalé
            pp = dict(pp); pp["misses"] = misses; out.append(pp)
    return out, events
