"""Gel : une commune n'est gelée que si TOUTES ses sources sont muettes, et une
source muette laisse une trace même quand sa commune reste couverte.

Contexte (scan du 16/08/2026) : Chaville et Viroflay étaient déclarées « gelées »
alors que SeLoger y avait ramené 25 et 27 annonces — 22 des 29 biens de Chaville
avaient bien été revus. Seule leur source Belles Demeures était tombée (HTTP 502).
Le rapport affichait donc une panne là où la couverture était à 75 %, et le bandeau
rouge se déclenchait à tort.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

import veille_immo
import run_veille
from veille_immo import chain, report_html

from tests.test_backlog_relisting import mkprop


BD = "https://www.bellesdemeures.com/annonces/vente/chaville/{}/"
SL = "https://www.seloger.com/annonces/achat/maison/chaville-92/{}.htm"


CONFIG = """
retrait_grace: 3
sources:
  - name: chaville
    commune: chaville
    urls: ["https://www.bellesdemeures.com/recherche?ci=920022"]
  - name: seloger_chaville
    commune: chaville
    parser: seloger
    urls: ["https://www.seloger.com/list.htm?locations=36607"]
  - name: meudon
    commune: meudon
    urls: ["https://www.bellesdemeures.com/vente/meudon/maison-luxe/tt-2-tb-2-pl-38328/"]
"""


def _prop(cid, url, commune="Chaville", **kw):
    p = mkprop(cid, quartier=f"Centre, {commune}", **kw)
    p["url"] = url.format(cid)
    return p


# --------------------------------------------------------------------------- #
# Gel ciblé sur la source, pas sur la commune                                  #
# --------------------------------------------------------------------------- #
def test_une_source_muette_ne_gele_que_ses_biens():
    """Belles Demeures muet, SeLoger debout : les biens SeLoger revus suivent leur
    cours, les biens que seul BD publie sont protégés du retrait."""
    prev = [_prop("bd1", BD, misses=2), _prop("sl1", SL, misses=2)]
    curr = [_prop("sl1", SL)]                       # seul SeLoger a ramené le sien
    out, events, _ = chain.scan_grace(curr, prev, "2026-08-16", failed_communes=(),
                                      grace=3, degraded={("chaville", "bellesdemeures.com")})
    assert [e["type"] for e in events] == []        # aucun retrait signalé
    garde = {p["canonical_id"]: p for p in out}
    assert set(garde) == {"bd1", "sl1"}
    assert garde["bd1"]["misses"] == 2              # gelé : le compteur n'avance pas
    assert garde["sl1"]["misses"] == 0


def test_un_bien_dune_source_vivante_reste_soumis_au_retrait():
    """Le gel ciblé ne doit pas protéger toute la commune : un bien SeLoger absent
    alors que SeLoger a répondu part bien en retrait au 3e manque."""
    # deux biens franchement distincts : sinon l'appariement flou les confond et
    # traite l'absent comme une republication de l'autre.
    prev = [_prop("sl_parti", SL, misses=2, price=1_150_000, surface=210.0)]
    curr = [_prop("sl_present", SL, price=790_000, surface=95.0)]
    out, events, backlog = chain.scan_grace(curr, prev, "2026-08-16", failed_communes=(),
                                            grace=3, degraded={("chaville", "bellesdemeures.com")})
    retraits = [e for e in events if e["type"] == "RETIRE"]
    assert [e["id"] for e in retraits] == ["sl_parti"]
    assert len(backlog) == 1


def test_commune_totalement_muette_gele_tout():
    """Quand aucune source ne répond, le gel commune reste le bon régime."""
    prev = [_prop("bd1", BD, misses=2), _prop("sl1", SL, misses=2)]
    out, events, _ = chain.scan_grace([], prev, "2026-08-16",
                                      failed_communes={"chaville"}, grace=3)
    assert events == []
    assert all(p["misses"] == 2 for p in out)


@pytest.mark.parametrize("url, attendu", [
    ("https://www.bellesdemeures.com/x/1/", "bellesdemeures.com"),
    ("http://seloger.com/y", "seloger.com"),
    ("https://www.aetm-immobilier.com/../fiches/1", "aetm-immobilier.com"),
    ("", ""), (None, ""),
])
def test_domaine(url, attendu):
    assert chain.domaine(url) == attendu


# --------------------------------------------------------------------------- #
# Calcul du gel côté orchestrateur                                             #
# --------------------------------------------------------------------------- #
@pytest.fixture
def faux_collecteur(monkeypatch):
    lot = {}

    def collect(sources, delay=0):
        return lot["rows"], [], lot["per_source"]

    faux = types.ModuleType("veille_immo.collector_scrapedo")
    faux.collect = collect
    from veille_immo import collector_scrapedo
    faux.render_enabled = collector_scrapedo.render_enabled
    monkeypatch.setitem(sys.modules, "veille_immo.collector_scrapedo", faux)
    monkeypatch.setattr(veille_immo, "collector_scrapedo", faux, raising=False)
    monkeypatch.setenv("SCRAPER_API_KEY", "jeton")
    return lot


def _annonce(cid, url, commune="Chaville", prix=900_000, surface=140.0):
    return {"id": str(cid), "url": url.format(cid), "title": f"Maison {cid} de charme",
            "price": prix, "surface": surface, "rooms": 6,
            "quartier": f"Centre, {commune}", "agency": ""}


def _run(tmp_path, monkeypatch, faux, etat=None):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "config.yaml"; cfg.write_text(CONFIG, encoding="utf-8")
    state = tmp_path / "state.json"
    if etat is not None:
        state.write_text(json.dumps(etat), encoding="utf-8")
    code = run_veille.main(["--config", str(cfg), "--state", str(state), "--no-email"])
    return code, (json.loads(state.read_text(encoding="utf-8")) if state.exists() else {})


def test_commune_couverte_par_une_seule_de_ses_deux_sources(tmp_path, monkeypatch,
                                                            faux_collecteur, capsys):
    """Le cas du 16/08 : chaville (BD) muette, seloger_chaville debout."""
    faux_collecteur["rows"] = [_annonce(f"sl{i}", SL, surface=120.0 + 9 * i) for i in range(6)]
    faux_collecteur["per_source"] = {"chaville": 0, "seloger_chaville": 6, "meudon": 3}
    code, etat = _run(tmp_path, monkeypatch, faux_collecteur)
    assert code == 0
    sortie = capsys.readouterr().out
    assert "sources muettes, commune couverte par ailleurs" in sortie
    assert "chaville (bellesdemeures.com, Chaville)" in sortie
    assert "communes gelées au total" not in sortie      # la commune n'est PAS gelée
    assert etat["frozen_sources"] == {"chaville": 1}
    assert etat["frozen"] == {}


def test_les_deux_sources_muettes_gelent_la_commune(tmp_path, monkeypatch,
                                                    faux_collecteur, capsys):
    faux_collecteur["rows"] = [_annonce(f"m{i}", BD, commune="Meudon", surface=120.0 + 9 * i)
                               for i in range(6)]
    faux_collecteur["per_source"] = {"chaville": 0, "seloger_chaville": 0, "meudon": 6}
    code, etat = _run(tmp_path, monkeypatch, faux_collecteur)
    assert code == 0
    assert "communes gelées au total : ['chaville']" in capsys.readouterr().out
    assert etat["frozen"] == {"chaville": 1}
    assert etat["frozen_sources"] == {}                  # gel commune, pas gel source


def test_la_serie_dune_source_muette_sincremente(tmp_path, monkeypatch, faux_collecteur, capsys):
    faux_collecteur["rows"] = [_annonce(f"sl{i}", SL, surface=120.0 + 9 * i) for i in range(6)]
    faux_collecteur["per_source"] = {"chaville": 0, "seloger_chaville": 6, "meudon": 3}
    _run(tmp_path, monkeypatch, faux_collecteur)
    capsys.readouterr()
    etat = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    etat["frozen_sources"] = {"chaville": 3}             # comme si 3 scans avaient échoué
    (tmp_path / "state.json").write_text(json.dumps(etat), encoding="utf-8")
    _, etat2 = _run(tmp_path, monkeypatch, faux_collecteur)
    assert etat2["frozen_sources"] == {"chaville": 4}
    assert "4e scan consécutif" in capsys.readouterr().out


def test_etat_sans_frozen_sources_se_charge(tmp_path, monkeypatch, faux_collecteur):
    """Rétro-compat : un état écrit avant ce correctif n'a pas la clé."""
    ancien = {"schema": "chained-properties-v2",
              "properties": [_prop("sl0", SL)], "retired": [], "frozen": {}}
    faux_collecteur["rows"] = [_annonce(f"sl{i}", SL, surface=120.0 + 9 * i) for i in range(6)]
    faux_collecteur["per_source"] = {"chaville": 0, "seloger_chaville": 6, "meudon": 3}
    code, etat = _run(tmp_path, monkeypatch, faux_collecteur, etat=ancien)
    assert code == 0 and etat["frozen_sources"] == {"chaville": 1}


# --------------------------------------------------------------------------- #
# Rendu : bandeau et formulation                                               #
# --------------------------------------------------------------------------- #
def test_le_bandeau_ne_compte_que_les_communes_cibles():
    """Le 16/08, le bandeau annonçait « 4/5 » en comptant Saint-Cloud et Versailles,
    qui ne sont pas des communes cibles : le vrai ratio était 2/5."""
    props = [mkprop("a", price=900_000)]
    frozen = ["Chaville", "Saint-Cloud", "Versailles", "Viroflay"]
    full, _, stats = report_html.build(props, [], prev_max_id=10, today="2026-08-16",
                                       frozen=frozen, n_communes=5, n_frozen_cibles=2)
    assert stats["stale"] is False and stats["gelees"] == 2
    assert "SCAN NON FRAIS" not in full
    assert "Saint-Cloud" in full            # l'info reste, elle ne pilote plus le bandeau


def test_le_bandeau_se_declenche_toujours_sur_de_vraies_communes_cibles():
    full, _, stats = report_html.build([mkprop("a", price=900_000)], [], prev_max_id=10,
                                       today="2026-08-16", frozen=["A", "B", "C", "D"],
                                       n_communes=5, n_frozen_cibles=4)
    assert stats["stale"] is True and "SCAN NON FRAIS — 4/5" in full


def test_source_muette_signalee_a_part_des_communes_gelees():
    full, email, stats = report_html.build([mkprop("a", price=900_000)], [], prev_max_id=10,
                                           today="2026-08-16",
                                           degraded=["chaville (bellesdemeures.com, Chaville)"])
    assert stats["sources_muettes"] == 1
    for rendu in (full, email):
        assert "source muette, commune couverte par ailleurs" in rendu
        assert "chaville (bellesdemeures.com, Chaville)" in rendu
        assert "le reste de la commune suit son cours normal" in rendu


def test_la_formulation_du_gel_ne_promet_plus_le_silence_total():
    """L'ancienne phrase disait « ni mouvement de prix n'est signalé » — c'était faux
    dès qu'une source répondait encore (une HAUSSE a bien été rendue à Viroflay le
    16/08). Le gel commune ne s'applique désormais qu'aux communes muettes."""
    full, _, _ = report_html.build([mkprop("a", price=900_000)], [], prev_max_id=10,
                                   today="2026-08-16", frozen=["Chaville"])
    assert "Aucune de leurs sources n'a répondu" in full
    assert "ni mouvement de prix n'est signalé" not in full
