"""Cas de bord du rendu et des réglages : événements orphelins, estimation de date
hors plage, libellés dégradés, et cohérence du workflow avec le défaut de rendu.

Ces chemins ne sortent pas d'un scan nominal — ils sortent des scans ratés, et c'est
précisément là qu'un rapport qui plante coûte le plus cher (la collecte est déjà
payée quand le rendu s'exécute).
"""
from __future__ import annotations

import datetime
import pathlib

import pytest

from veille_immo import prices, report_html

from tests.test_backlog_relisting import mkprop
from tests.test_filtres_rapport import _data_rows, _move, _section


# --------------------------------------------------------------------------- #
# Événements sans bien correspondant                                           #
# --------------------------------------------------------------------------- #
def test_evenement_orphelin_nest_ni_rendu_ni_compte():
    """Un événement dont le bien n'est plus dans l'état (fusionné dans un autre
    cluster entre-temps) ne peut pas produire de ligne : il ne doit pas non plus
    gonfler le compteur, sinon l'en-tête annonce des lignes qui n'existent pas."""
    props = [mkprop("connu", price=900_000)]
    events = [{"type": "NOUVEAU", "id": "fantome", "title": "Maison fantôme",
               "price": 900_000, "url": "", "surface": 100.0, "rooms": 5,
               "commune": "sèvres", "n_mandats": 1},
              _move("fantome", 950_000, 900_000)]
    full, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-08-13")
    assert "fantôme" not in email
    assert (stats["nouveaux"], stats["baisses"]) == (0, 0)
    assert "Aucun changement depuis le dernier scan." in email


def test_retrait_orphelin_reste_lui_affiche():
    """Un RETIRÉ est par construction absent de l'état courant : il porte tout ce
    qu'il faut dans l'événement, et doit rester visible."""
    events = [{"type": "RETIRE", "id": "parti", "title": "Maison partie",
               "price": 900_000, "url": "", "surface": 120.0, "rooms": 5,
               "commune": "sèvres", "quartier": "Brancas, Sèvres", "n_mandats": 1,
               "aliases": ["parti"], "first_seen": "2026-07-01"}]
    _, email, stats = report_html.build([], events, prev_max_id=10, today="2026-08-13")
    assert stats["retraits"] == 1
    assert "🚫 Retraits" in email and "Maison partie" in email


def test_anomalie_dun_bien_absent_reste_affichee():
    """Une anomalie porte l'essentiel de l'info dans l'événement lui-même : elle
    doit s'afficher même si le bien a disparu de l'état — c'est justement le cas
    où l'on veut aller vérifier l'annonce."""
    events = [_move("parti", 57_000, 990_000)]
    events[0].update(quartier="Brancas, Sèvres", first_seen="2026-07-01")
    full, _, stats = report_html.build([], events, prev_max_id=10, today="2026-08-13")
    assert stats["anomalies"] == 1
    bloc = _section(full, "Anomalies de prix")
    assert len(_data_rows(bloc)) == 1
    assert "990 000" in bloc and "57 000" in bloc          # ancien -> nouveau prix


# --------------------------------------------------------------------------- #
# Estimation « en ligne depuis » : bornes                                      #
# --------------------------------------------------------------------------- #
def test_est_date_ne_deborde_pas_hors_plage():
    """Quand le plus grand id collecté touche l'ancre, la pente vaut 1 et un id
    ancien projetait des millions de jours en arrière : OverflowError, et TOUT le
    rapport échouait après la collecte (crédits déjà dépensés)."""
    d = report_html._est_date(1, report_html.ANCHOR_ID)
    assert isinstance(d, datetime.date)
    assert d >= report_html.ANCHOR_DATE - datetime.timedelta(days=3650)


def test_est_date_reste_juste_dans_la_plage_normale():
    """La borne ne doit pas déformer l'estimation courante : avec une pente réaliste,
    un id un peu plus ancien que l'ancre reste à quelques jours de celle-ci."""
    today_max = report_html.ANCHOR_ID + 1_500_000        # ~40 j de production d'ids
    d = report_html._est_date(report_html.ANCHOR_ID, today_max)
    assert d == report_html.ANCHOR_DATE


def test_bien_dagence_sans_id_sequentiel():
    """Pas d'id numérique exploitable (site d'agence) : l'estimation retombe sur
    aujourd'hui plutôt que de tenter une extrapolation absurde."""
    p = mkprop("aetm_60963076", price=900_000, aliases=["aetm_60963076"])
    lbl, est = report_html._online_label(p | {"first_seen": None}, today_max=275_000_000)
    assert est is True
    assert lbl.startswith("~")


# --------------------------------------------------------------------------- #
# Libellés dégradés                                                            #
# --------------------------------------------------------------------------- #
def test_date_non_iso_ne_casse_pas_le_rendu():
    assert report_html._fr_date("date inconnue") == "date inconnue"
    assert report_html._fr_date(None) == ""
    assert report_html._fr_date("2026-07-15") == "15 juil. 2026"


@pytest.mark.parametrize("bien, attendu", [
    ({"quartier": "Pavé des Gardes, Chaville"}, "Chaville"),
    ({"quartier": "Viroflay"}, "Viroflay"),
    ({"quartier": "", "commune": "velizy-villacoublay"}, "Vélizy-Villacoublay"),
    ({"quartier": "", "commune": "ville-d'avray"}, "Ville-d'Avray"),
])
def test_commune_affichee_proprement(bien, attendu):
    assert report_html._commune_disp(bien) == attendu


def test_badge_agence_deduit_de_lid():
    """Les portails ont des ids numériques ; un id alphanumérique trahit un site
    d'agence même quand le champ `agency` n'a pas été renseigné."""
    assert report_html._agency_of({"canonical_id": "aetm_60963076", "aliases": []}) == "agence"
    assert report_html._agency_of({"canonical_id": "270387453", "aliases": ["270387453"]}) == ""
    assert report_html._agency_of({"agency": "A&M", "canonical_id": "1"}) == "A&M"


# --------------------------------------------------------------------------- #
# Réparation d'un prix : la branche « plafond » sans signature                 #
# --------------------------------------------------------------------------- #
def test_prix_hors_plafond_recale_sur_le_libelle():
    """Prix invraisemblable dont l'ancienne regex ne rend PAS compte (médiane d'un
    cluster de deux annonces polluées, par exemple) : on retombe sur le libellé,
    qui donne une valeur plausible."""
    neuf, statut = prices.repair_price(10_975_000, "1 / 10 990 000 € 7 920 €/m² Maison neuve")
    assert (neuf, statut) == (990_000, "corrige")


def test_prix_hors_plafond_sans_libelle_exploitable():
    neuf, statut = prices.repair_price(9_900_000, "Propriété d'exception, nous consulter")
    assert (neuf, statut) == (9_900_000, "suspect")


# --------------------------------------------------------------------------- #
# Workflow : le rendu JS ne doit se rallumer que sur demande explicite          #
# --------------------------------------------------------------------------- #
def _workflow():
    import yaml
    p = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/veille.yml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_le_reglage_du_rendu_est_au_niveau_du_job():
    """Porté par le job et non par une étape : la tentative éco (datacenter) hérite
    du même réglage. C'est ce qui la fait passer de 5 à 1 crédit/page."""
    wf = _workflow()
    job = wf["jobs"]["scan"]
    assert job["env"]["SCRAPER_RENDER"] == "${{ inputs.render && 'true' || 'false' }}"
    for step in job["steps"]:
        assert "SCRAPER_RENDER" not in (step.get("env") or {}), step.get("name")


def test_lentree_du_workflow_est_opt_in():
    """`render` (défaut false) et non plus `no_render` : le mode par défaut d'un run
    planifié est le mode économique, sans rien cocher."""
    entrees = _workflow()[True]["workflow_dispatch"]["inputs"]
    assert "no_render" not in entrees
    assert entrees["render"]["default"] is False
    assert entrees["eco_first"]["default"] is False
