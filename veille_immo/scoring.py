"""Notation des annonces selon les critères de confort (ajoutés le 6/07/2026)
et positionnement prix par rapport à la moyenne de la commune.

Trois critères notés 0–2 chacun (total /6), à l'échelle de la ZONE :
- green  : entrée d'espace vert à ≤ 10 min à pied
- center : centre-ville, commerces et écoles à ≤ 10 min à pied
- slope  : dénivelé du trajet vers la gare (2 = fond de vallée plat,
           1 = pente modérée / à vérifier rue par rue, 0 = coteau marqué)

IMPORTANT : ce sont des scores de zone, indicatifs, calibrés sur la topographie
du secteur (fond de vallée du ru de Marivel = plat ; coteaux de Sèvres,
Bellevue, montée de Ville-d'Avray = pentus). Le dénivelé réel du bien doit
toujours être confirmé par le profil altimétrique du trajet piéton exact
(Géoportail ou Google Maps) : seuil retenu ≤ 20–25 m de dénivelé cumulé,
sans pente soutenue (> 6–8 %).
"""
from typing import Optional

from .models import Listing

# Moyennes maisons par commune (mi-2026, sources croisées SeLoger/MeilleursAgents/DVF)
COMMUNE_REFS = {
    "sèvres": 7270, "sevres": 7270,
    "ville-d'avray": 7700, "ville d'avray": 7700,
    "chaville": 6500,
    "viroflay": 7500,
    "meudon": 7650,
    "saint-cloud": 8950,
}

# Zones, de la plus spécifique à la plus générale (premier match retenu)
ZONES = [
    {"name": "Triangle parc de Lesser / Côte d'Argent", "keywords": ["lesser", "côte d'argent", "cote d'argent", "triangle d'or"],
     "green": 2, "center": 1, "slope": 1,
     "note": "parc de Lesser et parc de Saint-Cloud au contact ; pente vers la gare variable : vérifier rue par rue"},
    {"name": "Sèvres – Brancas / rive droite", "keywords": ["brancas", "fontenelles", "beauregard"],
     "green": 2, "center": 1, "slope": 1,
     "note": "parc de Saint-Cloud immédiat ; hauts de Brancas pentus, bas proche gare plus doux"},
    {"name": "Sèvres – Rive Gauche (fond de vallée)", "keywords": ["rive gauche", "croix-bosset", "croix bosset", "beau site", "pont de sèvres", "bellevue/pont"],
     "green": 1, "center": 2, "slope": 1,
     "note": "plat en fond de vallée (gare N, T2, commerces) mais coteau marqué dès Croix-Bosset/Beau Site : discriminer à l'adresse"},
    {"name": "Meudon – Bellevue", "keywords": ["bellevue"],
     "green": 2, "center": 1, "slope": 0,
     "note": "forêt de Meudon et terrasse proches, mais accès gare en pente : réservé aux rues du plateau proches de la gare"},
    {"name": "Chaville – bande entre les gares", "keywords": ["chaville"],
     "green": 2, "center": 2, "slope": 2,
     "note": "fond de vallée plat entre les deux gares, deux forêts à ≤ 10 min ; pondérer si le bien est sur les plateaux"},
    {"name": "Viroflay – bande entre les gares", "keywords": ["viroflay"],
     "green": 2, "center": 2, "slope": 2,
     "note": "même configuration bi-rive plate que Chaville ; pentes sur les hauteurs seulement"},
    {"name": "Ville-d'Avray – centre / étangs", "keywords": ["ville-d'avray", "ville d'avray", "étangs", "corot", "thierry"],
     "green": 2, "center": 2, "slope": 0,
     "note": "cadre exceptionnel mais gares en contrebas : trajet à pied en pente longue, critère dénivelé pénalisant"},
]


def score(listing: Listing) -> Optional[dict]:
    """Retourne le score confort de zone et le positionnement prix, ou None."""
    haystack = f"{listing.quartier} {listing.title}".lower()
    zone = next((z for z in ZONES if any(k in haystack for k in z["keywords"])), None)

    price_delta = None
    ref = next((v for k, v in COMMUNE_REFS.items() if k in haystack), None)
    if ref and listing.price_per_m2:
        price_delta = round(100 * (listing.price_per_m2 - ref) / ref, 1)

    if zone is None and price_delta is None:
        return None
    result = {"price_delta_pct": price_delta}
    if zone:
        result.update({
            "zone": zone["name"], "green": zone["green"], "center": zone["center"],
            "slope": zone["slope"], "total": zone["green"] + zone["center"] + zone["slope"],
            "zone_note": zone["note"],
        })
    return result


def render_score(listing: Listing) -> str:
    """Ligne de notation prête à insérer dans le rapport."""
    data = score(listing)
    if not data:
        return "  Notation : zone non reconnue — vérifier manuellement (espace vert, centre ≤ 10 min, dénivelé gare)"
    parts = []
    if "total" in data:
        parts.append(f"Confort {data['total']}/6 (vert {data['green']}/2 · centre/écoles {data['center']}/2 · "
                     f"dénivelé {data['slope']}/2) — {data['zone']}")
    if data.get("price_delta_pct") is not None:
        sign = "+" if data["price_delta_pct"] >= 0 else ""
        parts.append(f"prix {sign}{data['price_delta_pct']} % vs moyenne maisons de la commune")
    line = "  Notation : " + " · ".join(parts)
    if "zone_note" in data:
        line += f"\n  ↳ {data['zone_note']}"
    return line
