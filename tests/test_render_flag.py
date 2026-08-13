"""Rendu JS côté scraper : précédence CLI > SCRAPER_RENDER > défaut activé.

Le défaut reste le rendu : sans lui, scrape.do facture 10 crédits/page au lieu de
25, mais SeLoger est une SPA React et ses sources peuvent tomber à 0. Le flag sert
à mesurer l'économie une fois, à la main — le workflow GHA reste inchangé.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import run_veille
from veille_immo import collector_scrapedo


def test_defaut_le_rendu_reste_actif(monkeypatch):
    monkeypatch.delenv("SCRAPER_RENDER", raising=False)
    assert run_veille.resolve_render(None) is True


def test_env_seul(monkeypatch):
    monkeypatch.setenv("SCRAPER_RENDER", "false")
    assert run_veille.resolve_render(None) is False
    monkeypatch.setenv("SCRAPER_RENDER", "true")
    assert run_veille.resolve_render(None) is True


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


def test_le_collecteur_lit_la_meme_variable(monkeypatch):
    """L'orchestrateur transmet le réglage par l'environnement : c'est ce que le
    collecteur lit pour décider d'ajouter (ou non) `render=true` à la requête."""
    vus = {}

    def faux_fetch(url, token, super_proxy=True, render=True, wait_selector=None):
        vus["render"] = render
        raise RuntimeError("stop")

    monkeypatch.setattr(collector_scrapedo, "_fetch", faux_fetch)
    monkeypatch.setattr(collector_scrapedo.time, "sleep", lambda *_: None)
    monkeypatch.setenv("SCRAPER_API_KEY", "jeton")
    monkeypatch.setenv("SCRAPER_RENDER", "true" if run_veille.resolve_render(False) else "false")
    src = [{"name": "s", "url": "https://exemple.test/", "parser": "bd"}]
    try:
        collector_scrapedo.collect(src, delay=0)
    except Exception:
        pass
    assert vus["render"] is False
