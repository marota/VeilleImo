"""Parsing des cartes SeLoger.

SeLoger partage le back-office et les identifiants de Belles Demeures, mais pas son
filtre « luxe » : c'est la source du segment 700 k–1,2 M €. Le balisage est une SPA
React (data-testid), et le texte de carte mêle prix de vente, prix au m², surface
habitable ET surface de terrain — d'où ces cas de non-régression.
"""
from __future__ import annotations

import yaml

from veille_immo import sl_parse
from veille_immo.collector_scrapedo import PARSERS


def carte(href, txt):
    return (f'<div data-testid="serp-core-classified-card-testid">'
            f'<a href="{href}">{txt}</a></div>')


def page(*cartes):
    return "<html><body>" + "".join(cartes) + "</body></html>"


# texte réel relevé sur la SERP Chaville du 06/08/2026
REEL = ("1 / 14 C 945 000 € 6 300 €/m² Simuler mon crédit immobilier "
        "Maison de plain-pied à vendre 7 pièces · 5 chambres · 150 m² · 217 m² de terrain "
        "Pavé des Gardes, Chaville (92370)")


def test_carte_reelle():
    recs = sl_parse.parse_cards(page(carte(
        "https://www.seloger.com/annonces/achat/maison/chaville-92/pave-des-gardes/271067259.htm?se=1",
        REEL)))
    assert len(recs) == 1
    r = recs[0]
    assert r["id"] == "271067259"
    assert r["price"] == 945_000            # et non 6 300 (le prix au m²)
    assert r["surface"] == 150.0            # et non 217 (le terrain)
    assert r["rooms"] == 7
    assert r["quartier"] == "Pavé des Gardes, Chaville"
    assert r["url"].endswith("271067259.htm") and "?" not in r["url"]
    assert r["title"].startswith("Maison de plain-pied à vendre")
    assert r["agency"] == ""                # pas un site d'agence : pas de badge


def test_sans_quartier_on_garde_la_commune():
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/viroflay-78/276120375.htm",
        "740 000 € 5 692 €/m² Maison à vendre 6 pièces · 4 chambres · 130 m² Viroflay (78220)")))
    assert recs[0]["quartier"] == "Viroflay"
    assert recs[0]["price"] == 740_000 and recs[0]["surface"] == 130.0
    assert recs[0]["url"].startswith("https://www.seloger.com/")   # href relatif complété


def test_terrain_seul_ne_devient_pas_la_surface():
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/sevres-92/271000001.htm",
        "1 100 000 € Maison à vendre 6 pièces · 4 chambres · 400 m² de terrain Sèvres (92310)")))
    assert recs[0]["surface"] is None       # aucune surface habitable annoncée
    assert recs[0]["price"] == 1_100_000


def test_surface_decimale_ne_coupe_pas_le_lieu():
    """Vu en prod (275232481) : « 103,4 m² Chaville » — la virgule décimale passait
    pour le séparateur quartier/commune, d'où une commune « 4 m² chaville »."""
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/chaville-92/275232481.htm",
        "780 000 € Maison de ville à vendre 5 pièces · 4 chambres · 103,4 m² Chaville (92370) "
        "Nichée dans un environnement calme")))
    assert recs[0]["quartier"] == "Chaville"
    assert recs[0]["surface"] == 103.4

    # même piège, mais avec un quartier bien présent
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/chaville-92/275232482.htm",
        "980 000 € Maison à vendre 6 pièces · 103,4 m² Pavé des Gardes, Chaville (92370)")))
    assert recs[0]["quartier"] == "Pavé des Gardes, Chaville"


def test_nombre_coupe_par_le_balisage_ne_devient_pas_une_commune():
    """Vu en prod : « 13 » et « 4 m² » dans deux spans → lieu « 4 m² Chaville ».

    identity.commune() prend le segment après la dernière virgule : sans nettoyage,
    ce bien serait rattaché à une commune fantôme « 4 m² chaville »."""
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/chaville-92/271000002.htm",
        "980 000 € Maison à vendre 6 pièces · 4 chambres · 13 4 m² Chaville (92370)")))
    assert recs[0]["quartier"] == "Chaville"


def test_doublons_et_cartes_sans_lien_ignores():
    html = page(carte("/a/271067259.htm", REEL), carte("/b/271067259.htm", REEL),
                '<div data-testid="serp-core-classified-card-testid">sans lien</div>')
    assert len(sl_parse.parse_cards(html)) == 1


def test_config_seloger_coherente():
    """Chaque source SeLoger doit déclarer son parser, sa commune et ses filtres."""
    cfg = yaml.safe_load(open("config.gha.yaml", encoding="utf-8"))
    sl = [s for s in cfg["sources"] if s.get("parser") == "seloger"]
    assert len(sl) == 5
    for s in sl:
        assert s["commune"] and s["expect"] and s["urls"]
        for u in s["urls"]:
            assert "priceMin=700000" in u and "priceMax=1200000" in u
            assert "roomCountMin=4" in u and "squareMeterMin=90" in u
    # les communes couvertes par SeLoger sont celles de la veille
    bd = {s["commune"] for s in cfg["sources"] if s.get("parser", "bd") == "bd"}
    assert {s["commune"] for s in sl} == bd


def test_parser_par_defaut_reste_belles_demeures():
    assert PARSERS["bd"][1] == "div.item.js_favoritesParent"
    assert PARSERS["seloger"][1] == sl_parse.CARD
