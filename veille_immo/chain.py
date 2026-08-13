"""Chaînage des scans au niveau BIEN (et non annonce), anti-republication.

Un bien = un cluster d'annonces (voir identity.cluster). L'état persistant
stocke, par bien : un id canonique, la liste des id-alias rencontrés, l'empreinte,
la date de première apparition (first_seen) et le dernier prix vu.

Au scan suivant, chaque bien courant est rattaché à un bien connu :
  1. par recouvrement d'ID (un alias déjà vu), sinon
  2. par identity.same_property (republication sous nouvel ID).
Le first_seen est alors conservé ; sinon le bien est NOUVEAU (first_seen = aujourd'hui).
"""
import datetime
from typing import List
from . import identity
from .prices import is_sane

MIN_PCT = 2.0     # variation de prix minimale signalée (%)
MIN_EUR = 5000    # et en euros
RETENTION_DAYS = 180   # durée pendant laquelle un bien retiré reste comparé aux scans
from .models import Listing


def _listing_of(p: dict) -> Listing:
    """Vue Listing d'un dict de bien (pour identity.same_property)."""
    return Listing(id=p.get("canonical_id"), source="", title=p.get("title", ""),
                   price=p.get("price"), surface=p.get("surface"),
                   rooms=p.get("rooms"), quartier=p.get("quartier", ""))


def volume_drop_communes(prev_props, curr_props, min_prev=4, ratio=0.5):
    """Communes dont le VOLUME collecté chute fortement d'un scan à l'autre.

    Un lot de biens qui « disparaît » d'un coup sur une commune trahit une collecte
    partielle (pagination, anti-robot, résultats mouvants) bien plus qu'un vrai
    déstockage : on gèle alors la commune pour ne pas fabriquer de faux retraits.
    Seuil : volume courant < `ratio` × volume précédent, avec au moins `min_prev`
    biens auparavant (sous ce seuil, la variation n'est pas significative)."""
    from collections import Counter
    def _c(props):
        return Counter(identity.commune(p.get("quartier", "")) or p.get("commune", "")
                       for p in props)
    pc, cc = _c(prev_props), _c(curr_props)
    return {comm for comm, pn in pc.items()
            if pn >= min_prev and cc.get(comm, 0) < ratio * pn}


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
        # un prix invraisemblable est écarté de la médiane : dans un cluster à deux
        # mandats, il la déplace entièrement (10 975 000 € pour une maison à 990 000).
        prices = [l.price for l in grp if l.price and is_sane(l.price)]
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
            # agence d'origine (site direct) : sert au badge et au repérage des exclusivités
            "agency": next((l.agency for l in grp if getattr(l, "agency", "")), ""),
        })
    return props


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


def _match_backlog(prop, backlog, used):
    """Retrouve un bien courant dans le backlog des retraits (recouvrement d'ID ou
    même bien par empreinte floue), pour le signaler « remis en ligne »."""
    alias_set = set(prop["aliases"])
    for b in backlog:
        if id(b) in used:
            continue
        if alias_set & set(b.get("aliases", [])):
            return b
    a = _listing_of(prop)
    for b in backlog:
        if id(b) in used:
            continue
        if identity.same_property(a, _listing_of(b)):
            return b
    return None


def scan_grace(curr_props, prev_props, today, failed_communes=(), grace=3,
               backlog=None, retention_days=RETENTION_DAYS):
    """Chaînage FIABLE : hystérésis sur les retraits, gel des communes non collectées,
    backlog des retraits pour détecter les remises en ligne.

    - un bien courant retrouvé (état précédent) => conservé, misses=0, first_seen préservé ;
    - un bien courant inconnu de l'état MAIS présent au backlog des retraits
      => REMISE_EN_LIGNE (rappel date + prix de retrait), retiré du backlog ;
    - un bien courant inconnu partout => NOUVEAU (first_seen=today) ;
    - un bien précédent absent :
        * commune non collectée / en chute de volume (source en échec) => gelé ;
        * sinon misses += 1 ; RETIRÉ + versé au backlog quand misses >= grace, sinon « en sursis ».

    Le backlog est purgé des entrées de plus de `retention_days` jours.
    Retourne (nouvel_état, événements, nouveau_backlog)."""
    failed = {identity.commune(c) if "," in c or " " in c else c for c in failed_communes}
    backlog = list(backlog or [])
    events, used, used_back, out = [], set(), set(), []
    for cp in curr_props:
        prior = _match_prior(cp, prev_props, used)
        if prior is None:
            back = _match_backlog(cp, backlog, used_back)
            if back is not None:                     # RETOUR d'un bien retiré
                used_back.add(id(back))
                cp["first_seen"] = back.get("first_seen", today)
                cp["first_seen_estimated"] = back.get("first_seen_estimated", False)
                cp["last_seen"] = today; cp["misses"] = 0
                cp["aliases"] = sorted(set(cp["aliases"]) | set(back.get("aliases", [])), key=_idkey)
                rp, np_ = back.get("price"), cp.get("price")
                ev = {"type": "REMISE_EN_LIGNE", "id": cp["canonical_id"], "title": cp["title"],
                      "price": np_, "url": cp.get("url", ""), "surface": cp.get("surface"),
                      "rooms": cp.get("rooms"), "commune": cp.get("commune", ""),
                      "quartier": cp.get("quartier", ""), "n_mandats": cp.get("n_mandats", 1),
                      "first_seen": cp["first_seen"],
                      "retired_on": back.get("retired_on"), "retired_price": rp}
                if rp and np_ and rp != np_:
                    ev["pct"] = round(100 * (np_ - rp) / rp, 1)
                events.append(ev)
            else:                                    # vrai NOUVEAU
                cp["first_seen"] = today; cp["first_seen_estimated"] = False
                cp["last_seen"] = today; cp["misses"] = 0
                events.append({"type": "NOUVEAU", "id": cp["canonical_id"], "title": cp["title"],
                               "price": cp["price"], "url": cp.get("url", ""),
                               "surface": cp.get("surface"), "rooms": cp.get("rooms"),
                               "commune": cp.get("commune", ""), "n_mandats": cp.get("n_mandats", 1)})
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
    freshly_retired = []
    for pp in prev_props:
        if id(pp) in used:
            continue
        commune = identity.commune(pp.get("quartier", "")) or pp.get("commune", "")
        if commune in failed:                       # source en échec => on gèle
            out.append(pp); continue
        misses = pp.get("misses", 0) + 1
        if misses >= grace:                          # retrait CONFIRMÉ
            # on porte l'état structurel du bien retiré (il n'est plus dans l'état
            # courant, donc le rapport ne peut plus le retrouver) : de quoi le
            # rendre au même format riche que les nouveautés/mouvements.
            events.append({"type": "RETIRE", "id": pp["canonical_id"],
                           "title": pp.get("title", ""), "price": pp.get("price"),
                           "url": pp.get("url", ""), "surface": pp.get("surface"),
                           "rooms": pp.get("rooms"), "commune": pp.get("commune", ""),
                           "quartier": pp.get("quartier", ""),
                           "n_mandats": pp.get("n_mandats", 1),
                           "aliases": list(pp.get("aliases", [])),
                           "first_seen": pp.get("first_seen")})
            entry = dict(pp); entry.pop("misses", None); entry["retired_on"] = today
            freshly_retired.append(entry)
        else:                                        # en sursis : conservé, non signalé
            pp = dict(pp); pp["misses"] = misses; out.append(pp)

    # backlog : on retire les biens revenus en ligne, on purge les trop anciens,
    # on dédoublonne par ID canonique, puis on verse les retraits du jour.
    try:
        cutoff = (datetime.date.fromisoformat(today)
                  - datetime.timedelta(days=retention_days)).isoformat()
    except ValueError:
        cutoff = ""
    fresh_ids = {e["canonical_id"] for e in freshly_retired}
    new_backlog = [b for b in backlog
                   if id(b) not in used_back
                   and (not b.get("retired_on") or b["retired_on"] >= cutoff)
                   and b.get("canonical_id") not in fresh_ids]
    new_backlog.extend(freshly_retired)
    return out, events, new_backlog
