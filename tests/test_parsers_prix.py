"""Non-régression du prix **à travers les trois parsers**, pas seulement dans
`prices.parse_price`.

Le bug du 13/08/2026 n'était pas dans une fonction isolée : il sortait de
`parse_cards`, avec du HTML de carte réel. Les cas unitaires vivent dans
`test_prices.py` ; ici on vérifie le chemin complet HTML -> annonce, pour les trois
sources qui partagent désormais la même lecture de prix.
"""
from __future__ import annotations

import pytest

from veille_immo import bd_parse, collector_agences, prices, sl_parse

from tests.test_seloger import carte, page


# Textes de carte RÉELS du scan du 13/08/2026 : le compteur du carrousel est collé
# au prix, sans lettre DPE pour les séparer.
CARTES_POLLUEES = [
    ("https://www.seloger.com/annonces/achat/maison/meudon-92/le-centre/260740857.htm",
     "1 / 11 950 000 € 3 743 €/m² Maison à vendre 10 pièces · 3 chambres · 253,8 m² "
     "Le Centre, Meudon (92190)",
     950_000, 253.8),
    ("https://www.seloger.com/annonces/achat/maison/viroflay-78/272649319.htm",
     "1 / 3 911 000 € 7 840 €/m² Maison à vendre - neuf 5 pièces · 4 chambres · 116,2 m² "
     "Rive Gauche, Viroflay (78220)",
     911_000, 116.2),
    ("https://www.seloger.com/annonces/achat/maison/viroflay-78/272649320.htm",
     "1 / 10 990 000 € 7 920 €/m² Maison à vendre - neuf 5 pièces · 4 chambres · 125 m² "
     "Rive Gauche, Viroflay (78220)",
     990_000, 125.0),
]


@pytest.mark.parametrize("href, texte, prix, surface", CARTES_POLLUEES)
def test_seloger_le_compteur_ne_gonfle_plus_le_prix(href, texte, prix, surface):
    r = sl_parse.parse_cards(page(carte(href, texte)))[0]
    assert r["price"] == prix
    assert r["surface"] == surface      # le reste de la carte se lit toujours
    assert r["rooms"] == 5 or r["rooms"] == 10


def test_seloger_le_libelle_reste_brut_mais_saffiche_propre():
    """Le titre stocké n'est pas retouché — l'empreinte de chaînage en dépend ;
    c'est le RENDU qui nettoie (report_html), donc l'état reste comparable."""
    r = sl_parse.parse_cards(page(carte(CARTES_POLLUEES[0][0], CARTES_POLLUEES[0][1])))[0]
    assert r["title"].startswith("1 / 11 950 000 €")
    assert prices.clean_title(r["title"]).startswith("Maison à vendre 10 pièces")


BD_CARTE = """
<div class="item js_favoritesParent">
  <a href="/annonces/vente/chaville-92370/270387453/">voir</a>
  <div class="location">Chaville (92370)</div>
  <div class="price">1 / 14 1 190 000 €</div>
  <div class="desc">Maison à vendre 6 pièces · 4 chambres · 145 m²</div>
</div>"""


def test_belles_demeures_compteur_dans_le_bloc_prix():
    """Le prix de BD est lu dans `.price` en priorité : c'est là que le compteur
    apparaissait (141 190 000 € stockés pour un bien à 1 190 000 €)."""
    r = bd_parse.parse_cards(BD_CARTE)[0]
    assert r["id"] == "270387453"
    assert r["price"] == 1_190_000
    assert r["surface"] == 145.0 and r["rooms"] == 6


def test_belles_demeures_repli_sur_le_texte_de_carte():
    """Sans bloc `.price`, la lecture se rabat sur le texte complet — même garde."""
    sans_prix = BD_CARTE.replace('<div class="price">1 / 14 1 190 000 €</div>', "")
    r = bd_parse.parse_cards(sans_prix.replace(
        '<div class="desc">', '<div class="desc">1 / 14 1 190 000 € '))[0]
    assert r["price"] == 1_190_000


def test_agences_prix_colle_a_la_surface():
    """Gabarit des sites d'agences : « 230m² - 2 000 000 € ». Pas de compteur ici,
    mais la même lecture de prix — la surface ne doit pas être prise pour un prix."""
    rec = collector_agences._parse_link(
        "MEUDON Bellevue Maison 9 pièces sur un terrain de 1 425 m² 300m² - 3 200 000 €",
        "/fiches/4-40-26_60963076/maison", "https://www.aetm-immobilier.com")
    assert rec["price"] == 3_200_000
    assert rec["surface"] == 300.0 and rec["rooms"] == 9


def test_agences_compteur_devant_le_prix():
    rec = collector_agences._parse_link(
        "SEVRES Croix Bosset Maison 8 pièces 220m² 1 / 12 875 000 €",
        "/fiches/4-40-26_60647913/maison", "https://www.agenceprincipalesevres.com")
    assert rec["price"] == 875_000


def test_prix_au_m2_seul_ne_fait_pas_une_annonce():
    """Une carte sans prix de vente (seulement un €/m²) n'est pas exploitable :
    mieux vaut zéro annonce qu'une annonce à 3 743 €."""
    recs = sl_parse.parse_cards(page(carte(
        "/annonces/achat/maison/sevres-92/271000002.htm",
        "3 743 €/m² Maison à vendre 5 pièces · 120 m² Sèvres (92310)")))
    assert recs[0]["price"] is None
