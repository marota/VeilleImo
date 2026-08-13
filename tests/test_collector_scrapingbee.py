"""Provider ScrapingBee : chemin alternatif sélectionnable par `scraper.provider`.

Il n'avait aucun test. Ce qui compte ici : il doit produire EXACTEMENT les mêmes
annonces que scrape.do — même parseur, donc même lecture de prix. Un provider qui
lit les prix autrement, c'est le bug du compteur de carrousel qui revient par la
porte de derrière.
"""
from __future__ import annotations

import pytest
import requests

from veille_immo import collector_scrapingbee as bee


CARTE = """<html><head><title>Maisons à vendre Chaville — Belles Demeures</title></head><body>
<div class="item js_favoritesParent">
  <a href="/annonces/vente/chaville-92370/270387453/">voir</a>
  <div class="location">Chaville (92370)</div>
  <div class="price">1 / 14 1 190 000 €</div>
  <div class="desc">Maison à vendre 6 pièces · 4 chambres · 145 m²</div>
</div></body></html>"""


class _Reponse:
    def __init__(self, texte="", code=200):
        self.text, self.status_code = texte, code


@pytest.fixture(autouse=True)
def _pas_dattente(monkeypatch):
    monkeypatch.setattr(bee.time, "sleep", lambda *_: None)


def test_le_prix_est_lu_comme_chez_scrapedo(monkeypatch):
    monkeypatch.setattr(bee, "_fetch", lambda *a, **k: _Reponse(CARTE))
    rows, errors, per_source = bee.collect(
        [{"name": "chaville", "url": "https://x/", "expect": "Belles Demeures"}], delay=0,
        api_key="jeton")
    assert errors == [] and per_source == {"chaville": 1}
    assert rows[0]["price"] == 1_190_000        # et non 141 190 000
    assert rows[0]["surface"] == 145.0


def test_titre_inattendu_ignore_la_source(monkeypatch):
    """Redirection vers la recherche nationale : mieux vaut 0 annonce (commune
    gelée) qu'un lot d'annonces hors périmètre versé dans l'état."""
    monkeypatch.setattr(bee, "_fetch", lambda *a, **k: _Reponse(
        CARTE.replace("Maisons à vendre Chaville", "Toutes les annonces")))
    rows, errors, per_source = bee.collect(
        [{"name": "chaville", "url": "https://x/", "expect": "Chaville"}], delay=0,
        api_key="jeton")
    assert rows == [] and per_source == {"chaville": 0}
    assert "titre inattendu" in errors[0]


def test_http_en_erreur_est_reessaye_puis_signale(monkeypatch):
    appels = []
    monkeypatch.setattr(bee, "_fetch", lambda *a, **k: appels.append(1) or _Reponse("", 502))
    rows, errors, per_source = bee.collect(
        [{"name": "chaville", "url": "https://x/"}], delay=0, api_key="jeton")
    assert len(appels) == 2                     # une seconde tentative
    assert rows == [] and per_source == {"chaville": 0}
    assert "HTTP 502" in errors[0]


def test_exception_reseau_ne_fait_pas_tomber_la_collecte(monkeypatch):
    def boum(*a, **k):
        raise requests.ConnectionError("réseau coupé")

    monkeypatch.setattr(bee, "_fetch", boum)
    rows, errors, _ = bee.collect([{"name": "chaville", "url": "https://x/"}], delay=0,
                                  api_key="jeton")
    assert rows == [] and "ConnectionError" in errors[0]


def test_cle_absente(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_API_KEY"):
        bee.collect([{"name": "x", "url": "https://x/"}])
