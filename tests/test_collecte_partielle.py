"""Collecte partielle : le rapport doit continuer à partir, les communes muettes gelées.

Contexte (scans des 03 et 05/08/2026) : une ou deux communes muettes côté scrape.do
(HTTP 502, puis 401 « crédits épuisés ») faisaient tomber le total sous 60 % de l'état
précédent ; le garde-fou global annulait alors TOUT le scan et n'envoyait qu'une alerte,
alors que Chaville/Viroflay/agences avaient bien répondu. Le garde-fou ne juge plus que
le périmètre réellement collecté.
"""
from __future__ import annotations

import requests

from veille_immo import collector_agences, collector_local, collector_scrapedo, report_html
from veille_immo.errors import QuotaExhausted
import run_veille
from run_veille import collecte_suffisante

from tests.test_backlog_relisting import mkprop


def props(commune, n, start=0):
    return [mkprop(f"{commune}{i}", quartier=f"Centre, {commune}") for i in range(start, start + n)]


# --------------------------------------------------------------------------- #
# 1. Garde-fou : les communes gelées sortent des deux côtés de la balance      #
# --------------------------------------------------------------------------- #
def test_communes_gelees_exclues_du_ratio():
    # état précédent : 116 biens dont 42 sur deux communes muettes ce matin
    prev = props("Sevres", 34) + props("Ville-d'Avray", 21) + props("Meudon", 21) \
        + props("Chaville", 14) + props("Viroflay", 11) + props("Versailles", 15)
    # collecte du jour : tout sauf Ville-d'Avray et Meudon (59 biens, comme le 05/08)
    coll = props("Sevres", 25) + props("Chaville", 14) + props("Viroflay", 11) + props("Versailles", 9)
    assert len(prev) == 116 and len(coll) == 59

    # ancien comportement : 59 < 0,6 × 116 => scan annulé, aucun rapport
    assert len(coll) < 0.6 * len(prev)
    # nouveau : hors communes gelées, 59 sur 74 attendus => on continue
    ok, n_coll, n_prev, scope = collecte_suffisante(prev, coll, {"ville-d'avray", "meudon"})
    assert (ok, n_coll, n_prev, scope) == (True, 59, 74, "actif")


def test_effondrement_du_perimetre_collecte_declenche_toujours_l_alerte():
    prev = props("Sevres", 34) + props("Chaville", 14) + props("Viroflay", 11)
    coll = props("Sevres", 15) + props("Chaville", 5) + props("Viroflay", 5)   # 25 sur 59
    ok, n_coll, n_prev, scope = collecte_suffisante(prev, coll, set())
    assert len(coll) >= 0.3 * len(prev)                   # le plancher global tient…
    assert (ok, n_coll, n_prev, scope) == (False, 25, 59, "actif")   # …mais pas le ratio


def test_plancher_global_meme_si_tout_est_gele():
    # tout muet sauf Chaville : geler 5 communes ne doit pas transformer 14 biens
    # sur 116 en « rapport normal » — sous 30 % du parc connu, alerte.
    prev = props("Sevres", 34) + props("Ville-d'Avray", 21) + props("Meudon", 21) \
        + props("Chaville", 14) + props("Viroflay", 11) + props("Versailles", 15)
    coll = props("Chaville", 14)
    gelees = {"sevres", "ville-d'avray", "meudon", "viroflay", "versailles"}
    ok, n_coll, n_prev, scope = collecte_suffisante(prev, coll, gelees)
    assert (ok, n_coll, n_prev, scope) == (False, 14, 116, "global")


def test_historique_court_jamais_bloquant():
    # moins de 20 biens connus : aucun ratio n'est significatif
    ok, *_ = collecte_suffisante(props("Sevres", 12), props("Sevres", 3), set())
    assert ok


# --------------------------------------------------------------------------- #
# 2. scrape.do : 502 réessayé, 401 = crédits épuisés (arrêt + collecte partielle) #
# --------------------------------------------------------------------------- #
class FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


CARD = """<html><head><title>Maison de luxe à Chaville</title></head><body>
<div class="item js_favoritesParent"><a href="/annonces/vente/chaville/123456/">
<span class="location">Centre, Chaville</span><span class="price">950 000 €</span>
<span class="desc">Maison familiale 180 m² 7 Pièces</span></a></div></body></html>"""


def test_502_est_reessaye(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["url"])
        return FakeResp(502) if len(calls) == 1 else FakeResp(200, CARD)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(collector_scrapedo.time, "sleep", lambda *_: None)
    rows, errors, per_source = collector_scrapedo.collect(
        [{"name": "chaville", "commune": "chaville", "expect": "Chaville",
          "urls": ["https://www.bellesdemeures.com/x"]}], delay=0, api_key="tok")
    assert len(calls) == 2 and errors == []          # le 2e essai sauve la commune
    assert per_source == {"chaville": 1} and len(rows) == 1


def test_401_arrete_la_collecte_en_conservant_le_deja_collecte(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "chaville" in params["url"]:
            return FakeResp(200, CARD, {"Scrape.do-Request-Cost": "25",
                                        "Scrape.do-Remaining-Credits": "25"})
        return FakeResp(401)                          # crédits épuisés

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(collector_scrapedo.time, "sleep", lambda *_: None)
    sources = [{"name": "chaville", "commune": "chaville", "expect": "Chaville",
                "urls": ["https://www.bellesdemeures.com/chaville"]},
               {"name": "meudon", "commune": "meudon", "expect": "Meudon",
                "urls": ["https://www.bellesdemeures.com/meudon"]},
               {"name": "viroflay", "commune": "viroflay", "expect": "Viroflay",
                "urls": ["https://www.bellesdemeures.com/viroflay"]}]
    try:
        collector_scrapedo.collect(sources, delay=0, api_key="tok")
        raise AssertionError("QuotaExhausted attendu")
    except QuotaExhausted as e:
        assert len(e.rows) == 1                       # Chaville est conservée
        # les sources non atteintes restent à 0 => leurs communes seront gelées
        assert e.per_source == {"chaville": 1, "meudon": 0, "viroflay": 0}
        assert any("crédits" in x for x in e.errors)


# --------------------------------------------------------------------------- #
# 3. Sites d'agences : un timeout sur une page ne vide plus l'agence           #
# --------------------------------------------------------------------------- #
AG_HTML = """<html><body><a href="/fiches/4-40-maison-sevres_12345.html">
Maison SEVRES 6 pièces 190 m² - 1 050 000 €</a></body></html>"""


def test_une_page_agence_en_timeout_ne_perd_pas_les_autres(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("page=2"):
            raise requests.exceptions.ReadTimeout("Read timed out")
        return type("R", (), {"text": AG_HTML, "encoding": "utf-8", "apparent_encoding": "utf-8",
                              "raise_for_status": lambda self: None})()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(collector_agences.time, "sleep", lambda *_: None)
    rows, errors, per_source = collector_agences.collect(
        [{"name": "aetm", "agency": "A&M", "base": "https://www.aetm-immobilier.com",
          "href_filter": "/fiches/4-40-", "id_regex": r"_(\d{5,})",
          "urls": ["https://www.aetm-immobilier.com/v.html",
                   "https://www.aetm-immobilier.com/v.html?page=2"]}])
    assert per_source == {"aetm": 1} and len(rows) == 1
    assert len(errors) == 1 and "ReadTimeout" in errors[0]


# --------------------------------------------------------------------------- #
# 4. L'email dit clairement qu'il est partiel                                  #
# --------------------------------------------------------------------------- #
def test_bandeau_communes_gelees_dans_l_email():
    p = mkprop("1", quartier="Centre, Chaville")
    _, email, _ = report_html.build([p], [], prev_max_id=10, today="2026-08-05",
                                    frozen=["Meudon — 2e scan consécutif", "Ville-d'Avray"])
    assert "Collecte partielle" in email and "communes gelées" in email
    assert "Meudon — 2e scan consécutif" in email
    assert report_html._esc("Ville-d'Avray") in email      # apostrophe échappée
    # sans gel, aucun bandeau
    _, email_ok, _ = report_html.build([p], [], prev_max_id=10, today="2026-08-05")
    assert "Collecte partielle" not in email_ok


# --------------------------------------------------------------------------- #
# 5. Mode --local : collecte navigateur, aucune clé d'API requise               #
# --------------------------------------------------------------------------- #
def test_local_court_circuite_l_api_meme_avec_une_cle(monkeypatch, tmp_path):
    """`--local` doit primer sur SCRAPER_API_KEY (dépannage quand le quota est épuisé)."""
    vus = {}

    def fake_local(sources, **kw):
        vus["local"] = True
        return [], [], {s["name"]: 0 for s in sources}

    def interdit(*a, **kw):
        raise AssertionError("l'API ne doit pas être appelée en mode --local")

    monkeypatch.setenv("SCRAPER_API_KEY", "une-cle-valide")
    monkeypatch.setattr(collector_local, "collect", fake_local)
    monkeypatch.setattr(collector_scrapedo, "collect", interdit)
    monkeypatch.setattr(collector_agences, "collect", lambda *a, **kw: ([], [], {}))
    alertes = []
    monkeypatch.setattr(run_veille, "_alert", lambda subj, *a, **kw: alertes.append(subj))

    code = run_veille.main(["--config", "config.gha.yaml", "--no-email",
                            "--state", str(tmp_path / "state.json"), "--local"])
    assert vus.get("local") and code == 2          # collecte vide ici => garde-fou, pas de crash
    assert alertes and "collecte VIDE" in alertes[0]


def test_local_signale_playwright_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    monkeypatch.setattr(run_veille.importlib.util, "find_spec", lambda name: None)
    alertes = []
    monkeypatch.setattr(run_veille, "_alert", lambda subj, errs, *a, **kw: alertes.append((subj, errs)))
    code = run_veille.main(["--config", "config.gha.yaml", "--no-email",
                            "--state", str(tmp_path / "state.json")])
    assert code == 4 and "playwright absent" in alertes[0][1][0]


def test_note_quota_dans_l_email_sans_commune_gelee():
    p = mkprop("1", quartier="Centre, Chaville")
    _, email, _ = report_html.build([p], [], prev_max_id=10, today="2026-08-05",
                                    note="Crédits du fournisseur de scraping épuisés.")
    assert "Collecte partielle" in email and "Crédits" in email
