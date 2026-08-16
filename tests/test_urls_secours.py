"""URL de secours : plan B quand la page nominale d'une source ne rend rien.

Le 16/08/2026, les deux seules sources en `recherche?ci=` (Chaville, Viroflay) sont
tombées en HTTP 502 pendant que les trois sources en `/vente/…/tt-2-tb-2-pl-…/`
répondaient. La corrélation n'est pas une preuve — Meudon, en forme `pl-`, avait
échoué les 07 et 10/08 — d'où un repli plutôt qu'un remplacement : on garde `ci=`
en nominal et on ne paie la forme SEO que le jour où `ci=` tombe.
"""
from __future__ import annotations

import pytest
import yaml

from veille_immo import collector_scrapedo as sd


CARTE = """<html><head><title>Maisons Chaville — Belles Demeures</title></head><body>
<div class="item js_favoritesParent">
  <a href="/annonces/vente/chaville-92370/{id}/">voir</a>
  <div class="location">Chaville (92370)</div><div class="price">1 190 000 €</div>
  <div class="desc">Maison 6 pièces · 145 m²</div>
</div></body></html>"""


@pytest.fixture
def sans_attente(monkeypatch):
    monkeypatch.setattr(sd.time, "sleep", lambda *_: None)
    monkeypatch.setenv("SCRAPER_API_KEY", "jeton")


class _R:
    def __init__(self, texte="", code=200):
        self.text, self.status_code, self.headers = texte, code, {}


def _source(**kw):
    base = {"name": "chaville", "commune": "chaville", "parser": "bd",
            "urls": ["https://bd.test/recherche?ci=920022"]}
    base.update(kw)
    return base


def test_le_secours_nest_pas_appele_si_le_nominal_repond(sans_attente, monkeypatch):
    appels = []

    def faux(url, token, super_proxy=True, render=False, wait_selector=None):
        appels.append(url)
        return _R(CARTE.format(id=270000001))

    monkeypatch.setattr(sd, "_fetch", faux)
    rows, errors, per = sd.collect([_source(urls_secours=["https://bd.test/pl-38315/"])], delay=0)
    assert len(appels) == 1 and "recherche?ci=" in appels[0]      # coût inchangé
    assert per == {"chaville": 1} and errors == []


def test_le_secours_prend_le_relais_quand_le_nominal_est_muet(sans_attente, monkeypatch, capsys):
    appels = []

    def faux(url, token, super_proxy=True, render=False, wait_selector=None):
        appels.append(url)
        return _R("", 502) if "recherche?ci=" in url else _R(CARTE.format(id=270000002))

    monkeypatch.setattr(sd, "_fetch", faux)
    rows, errors, per = sd.collect([_source(urls_secours=["https://bd.test/pl-38315/"])], delay=0)
    assert per == {"chaville": 1}                    # la commune n'est plus muette
    assert appels[-1].endswith("pl-38315/")
    assert any("HTTP 502" in e for e in errors)      # l'échec reste signalé
    assert "URL de secours" in capsys.readouterr().out


def test_toutes_les_url_de_secours_sont_appelees(sans_attente, monkeypatch):
    """Les 4 pages de Viroflay sont ses quartiers : complémentaires, pas
    interchangeables — il faut donc les prendre toutes, pas s'arrêter à la première."""
    appels = []

    def faux(url, token, super_proxy=True, render=False, wait_selector=None):
        appels.append(url)
        if "recherche?ci=" in url:
            return _R("", 502)
        return _R(CARTE.format(id=270000000 + len(appels)))

    monkeypatch.setattr(sd, "_fetch", faux)
    secours = [f"https://bd.test/pl-4580{i}/" for i in range(4)]
    _, _, per = sd.collect([_source(name="viroflay", urls_secours=secours)], delay=0)
    assert set(appels) == {"https://bd.test/recherche?ci=920022", *secours}
    assert sorted(u for u in appels if "pl-" in u) == secours   # chacune une seule fois
    assert per == {"viroflay": 4}


def test_sans_url_de_secours_le_comportement_ne_change_pas(sans_attente, monkeypatch):
    monkeypatch.setattr(sd, "_fetch",
                        lambda *a, **k: _R("", 502))
    _, errors, per = sd.collect([_source()], delay=0)
    assert per == {"chaville": 0} and any("HTTP 502" in e for e in errors)


def test_les_url_principales_multiples_restent_toutes_appelees(sans_attente, monkeypatch):
    """`urls` = pages complémentaires (toutes appelées) ; `urls_secours` = plan B."""
    appels = []

    def faux(url, token, super_proxy=True, render=False, wait_selector=None):
        appels.append(url)
        return _R(CARTE.format(id=270000000 + len(appels)))

    monkeypatch.setattr(sd, "_fetch", faux)
    src = _source(urls=["https://bd.test/a/", "https://bd.test/b/"],
                  urls_secours=["https://bd.test/secours/"])
    _, _, per = sd.collect([src], delay=0)
    assert len(appels) == 2 and per == {"chaville": 2}    # secours non appelé


def test_config_de_production_coherente():
    cfg = yaml.safe_load(open("config.gha.yaml", encoding="utf-8"))
    par_nom = {s["name"]: s for s in cfg["sources"]}
    for nom in ("chaville", "viroflay"):
        src = par_nom[nom]
        assert "recherche?ci=" in src["urls"][0], nom
        assert src.get("urls_secours"), f"{nom} sans plan B"
        assert all("maison-luxe/tt-2-tb-2-pl-" in u for u in src["urls_secours"]), nom
    # les sources qui répondaient déjà n'ont pas été touchées
    for nom in ("sevres_brancas", "ville_davray", "meudon"):
        assert not par_nom[nom].get("urls_secours"), nom
