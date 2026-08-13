"""Rendu JS côté scraper : précédence CLI > SCRAPER_RENDER > défaut DÉSACTIVÉ.

L'essai a été fait le 06/08/2026 (run GHA 31107448276) et tranché : sans rendu, les
10 sources répondent — SeLoger compris, malgré la SPA React — pour 100 crédits au
lieu de 250. Depuis, le rendu fait carrément PERDRE des sources : les cinq URL
Belles Demeures tombent en HTTP 502 (13/08). Le défaut a donc basculé.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

import run_veille
from veille_immo import collector_scrapedo


def test_defaut_sans_rendu(monkeypatch):
    """Le défaut de production : rien à régler pour payer 10 crédits/page."""
    monkeypatch.delenv("SCRAPER_RENDER", raising=False)
    assert run_veille.resolve_render(None) is False
    assert collector_scrapedo.render_enabled() is False


def test_env_seul(monkeypatch):
    monkeypatch.setenv("SCRAPER_RENDER", "true")
    assert run_veille.resolve_render(None) is True
    monkeypatch.setenv("SCRAPER_RENDER", "false")
    assert run_veille.resolve_render(None) is False


@pytest.mark.parametrize("brut, attendu", [
    ("true", True), ("TRUE", True), ("1", True), ("oui", True),
    ("false", False), ("", False), ("   ", False), ("n'importe quoi", False),
])
def test_lecture_de_la_variable(brut, attendu):
    """Une valeur non reconnue retombe sur le défaut plutôt que d'allumer le rendu
    par accident — c'est le sens coûteux (25 crédits/page)."""
    assert collector_scrapedo.render_enabled(brut) is attendu


def test_cli_prime_sur_env(monkeypatch):
    monkeypatch.setenv("SCRAPER_RENDER", "false")
    assert run_veille.resolve_render(True) is True
    monkeypatch.setenv("SCRAPER_RENDER", "true")
    assert run_veille.resolve_render(False) is False


def test_les_deux_flags_existent():
    ap = run_veille.build_parser()
    assert ap.parse_args([]).render is None            # rien de forcé : l'env décide
    assert ap.parse_args(["--render"]).render is True
    assert ap.parse_args(["--no-render"]).render is False


@pytest.mark.parametrize("cli, attendu_requete", [(None, False), (False, False), (True, True)])
def test_le_collecteur_suit_le_reglage(monkeypatch, cli, attendu_requete):
    """L'orchestrateur transmet le réglage par l'environnement : c'est ce que le
    collecteur lit pour décider d'ajouter (ou non) `render=true` à la requête."""
    vus = {}

    def faux_fetch(url, token, super_proxy=True, render=False, wait_selector=None):
        vus["render"] = render
        raise RuntimeError("stop")

    monkeypatch.setattr(collector_scrapedo, "_fetch", faux_fetch)
    monkeypatch.setattr(collector_scrapedo.time, "sleep", lambda *_: None)
    monkeypatch.setenv("SCRAPER_API_KEY", "jeton")
    monkeypatch.delenv("SCRAPER_RENDER", raising=False)
    monkeypatch.setenv("SCRAPER_RENDER", "true" if run_veille.resolve_render(cli) else "false")
    src = [{"name": "s", "url": "https://exemple.test/", "parser": "bd"}]
    try:
        collector_scrapedo.collect(src, delay=0)
    except Exception:
        pass
    assert vus["render"] is attendu_requete


def test_le_workflow_ne_force_pas_le_rendu():
    """Garde-fou : le job GHA ne doit pas remettre SCRAPER_RENDER à 'true' en dur —
    c'est la case « render » du Run workflow qui le fait, et elle vaut false."""
    import pathlib
    wf = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/veille.yml"
    texte = wf.read_text(encoding="utf-8")
    assert "SCRAPER_RENDER: ${{ inputs.render && 'true' || 'false' }}" in texte
    assert "no_render" not in texte
