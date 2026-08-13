"""Bornes du rapport : budget sur toutes les vues, variations aberrantes à part,
bandeau de fraîcheur, libellés nettoyés.

Contexte (rapport du 13/08/2026) : la table multi-mandats affichait des biens à
490 000 € et à 2 700 000 € alors que le budget est 700 000–1 200 000 €, et des
mouvements à +1 629 % (prix pollué) passaient pour de vraies hausses.
"""
from __future__ import annotations

import re

import pytest

from veille_immo import report_html

from tests.test_backlog_relisting import mkprop


def _data_rows(html_table):
    return [r for r in re.findall(r"<tr[^>]*>.*?</tr>", html_table, re.S) if "<td" in r]


def _section(full, titre):
    """HTML de la table qui suit un <h2> donné."""
    m = re.search(re.escape(titre) + r".*?<table[^>]*>(.*?)</table>", full, re.S)
    return m.group(1) if m else ""


def _move(cid, old, new, type_=None):
    pct = round(100 * (new - old) / old, 1)
    return {"type": type_ or ("HAUSSE" if new > old else "BAISSE"), "id": str(cid),
            "title": f"Maison {cid} pleine de charme", "old_price": old, "price": new,
            "pct": pct, "url": "https://x/" + str(cid), "surface": 100.0, "rooms": 5,
            "commune": "sèvres", "n_mandats": 1}


# --------------------------------------------------------------------------- #
# Budget : toutes les vues, bornes incluses                                    #
# --------------------------------------------------------------------------- #
def test_multi_mandats_borne_au_budget():
    props = [mkprop("bas", price=490_000, n_mandats=2, aliases=["bas", "bas2"]),
             mkprop("haut", price=2_700_000, n_mandats=3, aliases=["h", "h2", "h3"]),
             mkprop("dedans", price=1_150_000, n_mandats=2, aliases=["d", "d2"])]
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    table = _section(full, "Biens en multi-mandats")
    assert len(_data_rows(table)) == 1
    assert stats["multi"] == 1
    assert "2 700 000" not in table and "490 000" not in table


def test_multi_mandats_entete_et_lignes_saccordent():
    """Le nombre annoncé dans le titre est celui des lignes affichées."""
    props = [mkprop(f"m{i}", price=900_000, n_mandats=2, aliases=[f"m{i}", f"m{i}b"])
             for i in range(5)] + [mkprop("solo", price=900_000)]
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    entete = int(re.search(r"Biens en multi-mandats \((\d+)\)", full).group(1))
    assert entete == stats["multi"] == len(_data_rows(_section(full, "Biens en multi-mandats"))) == 5


@pytest.mark.parametrize("prix, affiche", [
    (1_200_000, True),     # borne haute INCLUSE
    (1_200_001, False),
    (700_000, True),       # borne basse INCLUSE
    (699_999, False),
])
def test_bornes_incluses(prix, affiche):
    props = [mkprop("x", price=prix, surface=120.0)]
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    assert (stats["inb"] == 1) is affiche
    lignes = _data_rows(_section(full, "Biens dans vos critères"))
    assert (len(lignes) == 1) is affiche


def test_seuil_parametrable(monkeypatch):
    monkeypatch.setenv("VEILLEIMO_PRICE_MAX", "1500000")
    props = [mkprop("x", price=1_450_000, surface=120.0)]
    _, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    assert stats["inb"] == 1


def test_mouvement_hors_budget_absent_des_changements():
    props = [mkprop("cher", price=2_495_000)]
    events = [_move("cher", 2_700_000, 2_495_000)]
    _, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-08-13")
    assert stats["baisses"] == 0
    assert "⚡ Mouvements de prix" not in email


def test_bien_hors_budget_reste_dans_letat():
    """Le filtre est au RENDU : l'état n'est pas amputé, sinon un bien qui repasse
    sous le seuil réapparaîtrait en « nouveau » (ou pire, en remise en ligne)."""
    props = [mkprop("cher", price=2_495_000), mkprop("ok", price=900_000)]
    _, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    assert stats["biens"] == 2 and stats["inb"] == 1


# --------------------------------------------------------------------------- #
# Variations aberrantes : partitionnées, jamais masquées                       #
# --------------------------------------------------------------------------- #
# Les deux prix restent dans le budget : c'est le POURCENTAGE qu'on teste ici.
@pytest.mark.parametrize("old, new, anormal", [
    (900_000, 1_079_100, False),      # +19,9 %
    (900_000, 1_080_000, False),      # +20,0 % : borne INCLUSE dans le bloc standard
    (900_000, 1_080_900, True),       # +20,1 %
    (1_000_000, 801_000, False),      # −19,9 %
    (1_000_000, 800_000, False),      # −20,0 %
    (1_000_000, 799_000, True),       # −20,1 %
])
def test_bornes_de_variation(old, new, anormal):
    props = [mkprop("x", price=new)]
    _, email, stats = report_html.build(props, [_move("x", old, new)], prev_max_id=10,
                                        today="2026-08-13")
    assert ("Anomalies de prix" in email) is anormal
    assert (stats["anomalies"] == 1) is anormal
    mouvements = stats["baisses"] + stats["hausses"]
    assert (mouvements == 0) is anormal


def test_anomalie_affichee_mais_hors_synthese():
    props = [mkprop("pollue", price=990_000), mkprop("vrai", price=900_000)]
    events = [_move("pollue", 57_000, 990_000),      # +1 636 % : prix précédent pollué
              _move("vrai", 950_000, 900_000)]       # −5,3 % : vraie baisse
    full, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-08-13")
    assert stats["anomalies"] == 1 and stats["baisses"] == 1 and stats["hausses"] == 0
    assert "🚨 Anomalies de prix (à vérifier) (1)" in full     # rien n'est masqué
    assert "Maison pollue" in email
    assert "1 baisse" in full and "hausse" not in full.split("changements :")[1][:60]


def test_seuil_de_variation_parametrable(monkeypatch):
    monkeypatch.setenv("VEILLEIMO_DELTA_MAX_PCT", "50")
    props = [mkprop("x", price=1_200_000)]
    _, _, stats = report_html.build(props, [_move("x", 1_000_000, 1_200_000)],
                                    prev_max_id=10, today="2026-08-13")
    assert stats["anomalies"] == 0 and stats["hausses"] == 1


def test_la_colonne_vs_moyenne_nest_pas_concernee():
    """−50 % vs la moyenne de la commune est un écart de POSITIONNEMENT, pas un
    mouvement temporel : il doit rester affiché tel quel."""
    props = [mkprop("x", price=700_000, surface=200.0, rooms=7,
                    quartier="Centre, Chaville")]       # 3 500 €/m² vs 6 500 de moyenne
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13")
    assert stats["anomalies"] == 0
    ecarts = [float(x) for x in re.findall(r">([-+]?\d+(?:\.\d+)?) %<", full)]
    assert any(x <= -20 for x in ecarts), ecarts


# --------------------------------------------------------------------------- #
# Bandeau de fraîcheur                                                         #
# --------------------------------------------------------------------------- #
def test_bandeau_scan_non_frais_au_dela_de_80_pct():
    props = [mkprop("a")]
    gelees = ["Sèvres", "Meudon", "Chaville", "Viroflay"]
    full, email, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13",
                                           frozen=gelees, n_communes=5)
    assert stats["stale"] is True
    assert "SCAN NON FRAIS — 4/5 communes cibles gelées" in full
    assert "SCAN NON FRAIS" in email


def test_pas_de_bandeau_sous_le_seuil():
    props = [mkprop("a")]
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-13",
                                       frozen=["Sèvres", "Meudon", "Chaville"], n_communes=5)
    assert stats["stale"] is False
    assert "SCAN NON FRAIS" not in full
    assert "Collecte partielle" in full          # l'avertissement habituel reste


def test_pas_de_bandeau_sans_perimetre_connu():
    """Appel sans n_communes (compat ascendante) : pas de dénominateur, pas de bandeau."""
    full, _, stats = report_html.build([mkprop("a")], [], prev_max_id=10, today="2026-08-13",
                                       frozen=["Sèvres", "Meudon"])
    assert stats["stale"] is False and "SCAN NON FRAIS" not in full


# --------------------------------------------------------------------------- #
# Libellés                                                                     #
# --------------------------------------------------------------------------- #
def test_libelle_debarrasse_du_bruit_de_carte():
    p = mkprop("x", price=1_200_000, surface=252.0, rooms=8)
    p["title"] = ("1 / 14 D 1 200 000 € 4 762 €/m² Maison à vendre 8 pièces · "
                  "4 chambres · 252 m² Chaville (92370)")
    full, _, _ = report_html.build([p], [], prev_max_id=10, today="2026-08-13")
    assert "Maison à vendre 8 pièces" in full
    assert "1 / 14 D" not in full
    assert "4 762" not in full
