"""Migration one-shot en ligne de commande.

`python -m veille_immo.migrate_state` sert à assainir un état tout de suite, sans
attendre le scan suivant — et à REGARDER ce qui serait changé avant de committer.
Le mode --dry-run doit donc être vraiment sans écriture.
"""
from __future__ import annotations

import json

from veille_immo import migrate_state


ETAT = {
    "schema": "chained-properties-v2",
    "properties": [
        {"canonical_id": "a", "price": 11_950_000,
         "title": "1 / 11 950 000 € 3 743 €/m² Maison à vendre 10 pièces"},
        {"canonical_id": "b", "price": 990_000, "title": "1 / 10 990 000 € Maison"},
        {"canonical_id": "c", "price": 5_200_000,
         "title": "A Ville d'Avray, propriété du XIXe entièrement restaurée"},
    ],
    "retired": [{"canonical_id": "d", "price": 15_911_000,
                 "title": "1 / 15 911 000 € Maison de ville"}],
}


def _etat(tmp_path, nom="state.json"):
    p = tmp_path / nom
    p.write_text(json.dumps(ETAT), encoding="utf-8")
    return p


def test_dry_run_necrit_rien(tmp_path, capsys):
    p = _etat(tmp_path)
    avant = p.read_text(encoding="utf-8")
    assert migrate_state.main([str(p), "--dry-run"]) == 0
    assert p.read_text(encoding="utf-8") == avant
    sortie = capsys.readouterr().out
    assert "2 prix corrigé(s), 1 à revérifier" in sortie
    assert "dry-run, rien écrit" in sortie


def test_ecriture_effective_et_idempotence(tmp_path, capsys):
    p = _etat(tmp_path)
    assert migrate_state.main([str(p)]) == 0
    st = json.loads(p.read_text(encoding="utf-8"))
    assert st["properties"][0]["price"] == 950_000
    assert st["retired"][0]["price"] == 911_000
    assert st["properties"][1]["price"] == 990_000          # déjà sain : intact
    assert st["properties"][2]["price"] == 5_200_000        # bien réel : conservé
    assert st["properties"][2]["price_suspect"] is True
    capsys.readouterr()
    # deuxième passage : plus rien à corriger, le fichier ne bouge plus
    apres = p.read_text(encoding="utf-8")
    assert migrate_state.main([str(p)]) == 0
    assert p.read_text(encoding="utf-8") == apres
    assert "0 prix corrigé(s)" in capsys.readouterr().out


def test_plusieurs_fichiers(tmp_path, capsys):
    a, b = _etat(tmp_path, "a.json"), _etat(tmp_path, "b.json")
    assert migrate_state.main([str(a), str(b)]) == 0
    for p in (a, b):
        assert json.loads(p.read_text(encoding="utf-8"))["properties"][0]["price"] == 950_000
    assert capsys.readouterr().out.count("prix corrigé(s)") == 2


def test_chemin_par_defaut(tmp_path, monkeypatch, capsys):
    """Sans argument : data/state_chained.json, le fichier de production."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _etat(tmp_path / "data", "state_chained.json")
    assert migrate_state.main([]) == 0
    assert "data/state_chained.json" in capsys.readouterr().out
    st = json.loads((tmp_path / "data/state_chained.json").read_text(encoding="utf-8"))
    assert st["properties"][0]["price"] == 950_000


def test_le_reste_de_letat_est_preserve(tmp_path):
    """Rien d'autre que les prix pollués ne doit bouger : la migration n'est pas
    une réécriture de schéma."""
    p = _etat(tmp_path)
    migrate_state.main([str(p)])
    st = json.loads(p.read_text(encoding="utf-8"))
    assert st["schema"] == "chained-properties-v2"
    assert [x["canonical_id"] for x in st["properties"]] == ["a", "b", "c"]
    assert st["properties"][0]["title"].startswith("1 / 11 950 000 €")   # libellé brut gardé
