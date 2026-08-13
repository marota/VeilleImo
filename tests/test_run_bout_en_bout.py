"""Un run complet, collecteur simulé : collecte -> garde-fous -> chaînage ->
rapport -> persistance. Vérifie que les nouveaux réglages (garde de sanité,
migration de l'état, bornes du rendu) tiennent ensemble dans main().
"""
from __future__ import annotations

import json
import sys
import types

import pytest

import veille_immo
import run_veille


CONFIG = """
retrait_grace: 3
sources:
  - name: sevres
    commune: sevres
    url: https://exemple.test/sevres
  - name: chaville
    commune: chaville
    url: https://exemple.test/chaville
"""


def _annonce(cid, price, commune="Sèvres", surface=140.0):
    return {"id": str(cid), "url": f"https://exemple.test/{cid}",
            "title": f"1 / 12 D {price} € 6 000 €/m² Maison à vendre 6 pièces",
            "price": price, "surface": surface, "rooms": 6,
            "quartier": f"Centre, {commune}", "agency": ""}


@pytest.fixture
def faux_collecteur(monkeypatch):
    """Injecte un collector_scrapedo qui rend des annonces au lieu d'appeler l'API."""
    lot = {}

    def collect(sources, delay=0):
        rows = lot["rows"]
        return rows, [], {"sevres": len(rows), "chaville": 1}

    from veille_immo import collector_scrapedo

    faux = types.ModuleType("veille_immo.collector_scrapedo")
    faux.collect = collect
    # le double doit exposer la même surface que le vrai module : l'orchestrateur y
    # lit aussi le réglage du rendu JS (SCRAPER_RENDER)
    faux.render_enabled = collector_scrapedo.render_enabled
    # `from veille_immo import collector_scrapedo` lit l'ATTRIBUT du paquet dès que
    # le vrai module a été importé une fois (par un autre test) : patcher sys.modules
    # seul laisserait passer un appel réseau.
    monkeypatch.setitem(sys.modules, "veille_immo.collector_scrapedo", faux)
    monkeypatch.setattr(veille_immo, "collector_scrapedo", faux, raising=False)
    monkeypatch.setenv("SCRAPER_API_KEY", "jeton")
    return lot


def _run(tmp_path, argv_extra=()):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    state = tmp_path / "state.json"
    code = run_veille.main(["--config", str(cfg), "--state", str(state), "--no-email",
                            *argv_extra])
    etat = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    return code, etat


def test_run_complet_ecrit_un_etat_sain(tmp_path, faux_collecteur, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    faux_collecteur["rows"] = [_annonce(270000001 + i, 900_000 + 10_000 * i,
                                        surface=120.0 + 9 * i) for i in range(6)]
    # une annonce dont le prix a été mal lu (compteur de carrousel) : elle doit
    # entrer dans l'état SANS son prix, pas être perdue.
    faux_collecteur["rows"].append(_annonce(270000099, 11_950_000, commune="Chaville",
                                            surface=210.0))
    code, etat = _run(tmp_path)
    assert code == 0
    sortie = capsys.readouterr().out
    assert "WARN prix invraisemblable" in sortie
    assert len(etat["properties"]) == 7
    pollue = [p for p in etat["properties"] if p["canonical_id"] == "270000099"]
    assert pollue and pollue[0]["price"] is None
    assert all(p["price"] is None or p["price"] <= 5_000_000 for p in etat["properties"])


def test_un_etat_pre_migration_se_charge_et_se_repare(tmp_path, faux_collecteur, monkeypatch, capsys):
    """Rétro-compat : un state_chained.json écrit avant le correctif doit se
    charger sans erreur et sortir migré, sans fabriquer de faux mouvement."""
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    state = tmp_path / "state.json"
    ancien = {"schema": "chained-properties-v2", "properties": [
        {"canonical_id": "270000001", "aliases": ["270000001"], "title":
         "1 / 11 950 000 € 6 000 €/m² Maison à vendre 6 pièces", "price": 11_950_000,
         "surface": 140.0, "rooms": 6, "quartier": "Centre, Sèvres", "commune": "sevres",
         "n_mandats": 1, "first_seen": "2026-07-01", "url": "https://exemple.test/270000001"}],
        "retired": [], "frozen": {}}
    state.write_text(json.dumps(ancien), encoding="utf-8")

    faux_collecteur["rows"] = [_annonce(270000001, 950_000, surface=140.0)] + [
        _annonce(270000010 + i, 900_000 + 10_000 * i, surface=170.0 + 9 * i)
        for i in range(5)]
    code = run_veille.main(["--config", str(cfg), "--state", str(state), "--no-email"])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "état migré" in sortie
    assert "BAISSE" not in sortie          # 11 950 000 -> 950 000 n'est pas une baisse
    etat = json.loads(state.read_text(encoding="utf-8"))
    migre = [p for p in etat["properties"] if p["canonical_id"] == "270000001"][0]
    assert migre["price"] == 950_000
    assert migre["first_seen"] == "2026-07-01"      # le bien n'a pas été recréé
