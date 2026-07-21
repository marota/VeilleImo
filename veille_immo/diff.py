"""Comparaison entre l'état précédent (state.json) et le scan courant.

Événements produits :
- NOUVEAU  : annonce inconnue jusqu'ici
- BAISSE / HAUSSE : variation de prix sur une annonce connue
- RETIRE   : annonce disparue (vendu, sous compromis, ou republication à venir)

`duplicate_clusters` regroupe les annonces au couple (surface, prix) quasi
identique : signature typique d'un même bien diffusé par plusieurs agences.
"""
from typing import Dict, List
from .models import Listing


def compare(prev: Dict[str, dict], curr: Dict[str, Listing]) -> List[dict]:
    events: List[dict] = []
    for lid, lst in sorted(curr.items()):
        if lid not in prev:
            events.append({
                "type": "NOUVEAU", "id": lid, "title": lst.title,
                "price": lst.price, "surface": lst.surface, "url": lst.url,
            })
        else:
            old_price = prev[lid].get("price")
            if lst.price and old_price and lst.price != old_price:
                delta = lst.price - old_price
                events.append({
                    "type": "BAISSE" if delta < 0 else "HAUSSE",
                    "id": lid, "title": lst.title,
                    "old_price": old_price, "price": lst.price,
                    "delta": delta, "pct": round(100 * delta / old_price, 1),
                    "url": lst.url,
                })
    for lid, old in sorted(prev.items()):
        if lid not in curr:
            events.append({
                "type": "RETIRE", "id": lid, "title": old.get("title", ""),
                "price": old.get("price"),
                "note": "vendu, sous compromis, mandat expiré ou republication à venir",
            })
    return events


def duplicate_clusters(curr: Dict[str, Listing]) -> List[List[Listing]]:
    groups: Dict[tuple, List[Listing]] = {}
    for lst in curr.values():
        if not (lst.price and lst.surface):
            continue
        key = (round(lst.surface / 5) * 5, round(lst.price, -3))
        groups.setdefault(key, []).append(lst)
    return [g for g in groups.values() if len(g) > 1]
