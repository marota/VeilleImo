"""Lecture du prix : le compteur de carrousel ne doit jamais se retrouver dedans."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from veille_immo import prices


# Les quatre premiers cas sont des textes de carte RÉELS du scan du 13/08/2026 :
# le compteur du carrousel (« 1 / 11 ») collé au prix le multipliait par 10 ou 100.
@pytest.mark.parametrize("texte, attendu", [
    ("NOUVEAU 1 / 11 950 000 €", 950_000),
    ("NOUVEAU 1 / 14 1 190 000 €", 1_190_000),
    ("HAUSSE 1 / 15 911 000 €", 911_000),
    ("HAUSSE 1 / 10 990 000 €", 990_000),
    ("1 / 15 850 000 €", 850_000),
    ("1 200 000 €", 1_200_000),
    ("990 000 €", 990_000),
    # compteur séparé du prix par le badge et la lettre DPE : déjà correct avant le fix
    ("1 / 17 Nouveau C 1 100 000 € 6 875 €/m² Maison à vendre 6 pièces", 1_100_000),
    ("1 / 14 D 1 200 000 € 4 762 €/m² Maison à vendre 8 pièces", 1_200_000),
    # prix au m² seul : ce n'est pas un prix de vente
    ("3 743 €/m² Maison à vendre", None),
    # agences : la surface précède le prix, séparée par un tiret
    ("MEUDON Bellevue Maison 9 pièces 230m² - 2 000 000 €", 2_000_000),
    # espaces insécables des portails
    ("1 100 000 €", 1_100_000),
])
def test_parse_price(texte, attendu):
    assert prices.parse_price(texte) == attendu


def test_un_vrai_montant_a_huit_chiffres_reste_lisible():
    """Sans compteur devant, un prix élevé n'est pas amputé — c'est la garde de
    sanité, pas la regex, qui décide qu'il est invraisemblable."""
    assert prices.parse_price("11 950 000 €") == 11_950_000


def test_une_date_nest_pas_un_compteur():
    assert prices.strip_photo_counter("13/08/2026 950 000 €") == "13/08/2026 950 000 €"


def test_sanite_et_plafond_parametrable(monkeypatch):
    assert prices.is_sane(1_200_000)
    assert prices.is_sane(None)          # prix inconnu : pas une anomalie
    assert not prices.is_sane(11_950_000)
    monkeypatch.setenv("VEILLEIMO_PRICE_SANITY_MAX", "20000000")
    assert prices.is_sane(11_950_000)
    monkeypatch.setenv("VEILLEIMO_PRICE_SANITY_MAX", "n'importe quoi")
    assert not prices.is_sane(11_950_000)   # valeur illisible -> défaut


def test_budget_bornes_incluses(monkeypatch):
    assert prices.in_budget(1_200_000)      # borne haute INCLUSE
    assert prices.in_budget(700_000)        # borne basse INCLUSE
    assert not prices.in_budget(1_200_001)
    assert not prices.in_budget(490_000)
    assert not prices.in_budget(None)
    monkeypatch.setenv("VEILLEIMO_PRICE_MAX", "1500000")
    assert prices.in_budget(1_500_000)


def test_migration_corrige_les_prix_pollues():
    props = [
        {"canonical_id": "260740857", "price": 11_950_000,
         "title": "1 / 11 950 000 € 3 743 €/m² Maison à vendre 10 pièces"},
        {"canonical_id": "270387453", "price": 141_190_000,
         "title": "1 / 14 1 190 000 € 8 207 €/m² Maison à vendre 6 pièces"},
        {"canonical_id": "ok", "price": 990_000, "title": "1 / 10 990 000 € Maison"},
    ]
    fixed, flagged = prices.migrate_properties(props)
    assert (fixed, flagged) == (2, 0)
    assert [p["price"] for p in props] == [950_000, 1_190_000, 990_000]


def test_migration_corrige_aussi_sous_le_plafond():
    """« 1 / 3 911 000 € » stocke 3 911 000 : sous le plafond de sanité, donc
    invisible pour lui. C'est la signature de l'ancienne regex qui le trahit."""
    props = [{"canonical_id": "272649319", "price": 3_911_000,
              "title": "1 / 3 911 000 € 7 840 €/m² Maison à vendre - neuf 5 pièces"}]
    assert prices.migrate_properties(props) == (1, 0)
    assert props[0]["price"] == 911_000


def test_migration_laisse_une_mediane_multi_mandats_tranquille():
    """La médiane d'un cluster diffère légitimement du prix du libellé canonique :
    l'ancienne regex ne la reproduit pas, donc on n'y touche pas."""
    props = [{"canonical_id": "x", "price": 995_000,
              "title": "1 / 12 D 990 000 € 6 000 €/m² Maison à vendre 6 pièces"}]
    assert prices.migrate_properties(props) == (0, 0)
    assert props[0]["price"] == 995_000


def test_migration_ne_touche_pas_un_bien_reellement_cher():
    """Un bien légitime au-dessus du plafond est marqué, jamais supprimé ni recalé."""
    props = [{"canonical_id": "x", "price": 5_200_000,
              "title": "A Ville d'Avray, propriété du XIXe entièrement restaurée"}]
    fixed, flagged = prices.migrate_properties(props)
    assert (fixed, flagged) == (0, 1)
    assert props[0]["price"] == 5_200_000
    assert props[0]["price_suspect"] is True


def test_migration_idempotente():
    props = [{"canonical_id": "a", "price": 11_950_000, "title": "1 / 11 950 000 € Maison"}]
    prices.migrate_properties(props)
    assert prices.migrate_properties(props) == (0, 0)
    assert props[0]["price"] == 950_000


@pytest.mark.parametrize("brut, attendu", [
    ("1 / 14 D 1 200 000 € 4 762 €/m² Maison à vendre 8 pièces · 4 chambres · 145 m²",
     "Maison à vendre 8 pièces · 4 chambres · 145 m²"),
    ("1 / 17 Nouveau C 1 100 000 € 6 875 €/m² Maison à vendre 6 pièces",
     "Maison à vendre 6 pièces"),
    ("MEUDON Centre Elégante meulière de 12 pièces sur un terrain de 492 m² 230m² - 2 000 000 €",
     "MEUDON Centre Elégante meulière de 12 pièces sur un terrain de 492 m²"),
    # une description sans bruit de carte n'est pas amputée
    ("A Ville d'Avray. Edifiée au milieu du XIXe siècle",
     "A Ville d'Avray. Edifiée au milieu du XIXe siècle"),
    ("", ""),
    (None, ""),
])
def test_clean_title(brut, attendu):
    assert prices.clean_title(brut) == attendu


def test_migration_fichier(tmp_path):
    import json
    from veille_immo import migrate_state
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "schema": "chained-properties-v2",
        "properties": [{"canonical_id": "a", "price": 15_911_000,
                        "title": "1 / 15 911 000 € Maison de ville"}],
        "retired": [{"canonical_id": "b", "price": 10_920_000,
                     "title": "1 / 10 920 000 € Maison neuve"}],
    }), encoding="utf-8")
    assert migrate_state.migrate_file(str(p)) == (2, 0)
    st = json.loads(p.read_text(encoding="utf-8"))
    assert st["properties"][0]["price"] == 911_000
    assert st["retired"][0]["price"] == 920_000
    assert st["schema"] == "chained-properties-v2"      # rien d'autre n'a bougé


def test_garde_prix_ecarte_sans_supprimer_le_bien(capsys):
    """Le prix invraisemblable est écarté à la collecte, le bien reste : le
    supprimer fabriquerait un faux retrait puis une fausse remise en ligne."""
    import run_veille
    rows = [{"id": "a", "price": 11_950_000, "url": "https://x/a"},
            {"id": "b", "price": 990_000, "url": "https://x/b"},
            {"id": "c", "price": None, "url": "https://x/c"}]
    assert run_veille.garde_prix(rows) == 1
    assert [r["price"] for r in rows] == [None, 990_000, None]
    assert len(rows) == 3
    assert "WARN prix invraisemblable" in capsys.readouterr().out


def test_mediane_ignore_les_prix_invraisemblables():
    """Filet de sécurité côté chaînage : deux annonces d'un même bien toutes deux
    polluées (« 1 / 10 990 000 » et « 1 / 10 960 000 ») passaient le contrôle de
    proximité de prix et donnaient une médiane à 10 975 000 €. Elles sont
    désormais écartées du calcul — le bien reste, sans prix."""
    from veille_immo import chain
    from veille_immo.models import Listing
    grp = [Listing(id="1", source="", title="Maison neuve", price=10_990_000, surface=125,
                   rooms=5, quartier="Rive Gauche, Viroflay"),
           Listing(id="2", source="", title="Maison neuve", price=10_960_000, surface=125,
                   rooms=5, quartier="Rive Gauche, Viroflay")]
    props = chain.build_properties(grp)
    assert len(props) == 1 and props[0]["n_mandats"] == 2
    assert props[0]["price"] is None
