"""Corps email refactoré : les changements (nouveautés / mouvements / retraits)
en tête au format riche 8 colonnes, coups de cœur démotés en mémo.

Couvre le cas vide (0 changement), le cas partiel (un seul type d'événement) et
le cas complet, plus le contrat d'enrichissement de l'événement RETIRE dont
dépend le rendu riche des retraits.
"""
from __future__ import annotations

import re

from veille_immo import chain, report_html


def mkprop(cid, price=950_000, surface=100.0, rooms=5, quartier="Centre, Sèvres",
           first_seen="2025-01-01", aliases=None, n_mandats=1):
    return {"canonical_id": str(cid), "title": f"Maison {cid} pleine de charme",
            "price": price, "surface": surface, "rooms": rooms, "quartier": quartier,
            "commune": quartier.rsplit(",", 1)[-1].strip().lower(), "n_mandats": n_mandats,
            "aliases": aliases or [str(cid)], "first_seen": first_seen,
            "first_seen_estimated": False, "misses": 0,
            "url": f"https://www.bellesdemeures.com/annonces/{cid}"}


def ev_new(p):
    return {"type": "NOUVEAU", "id": p["canonical_id"], "title": p["title"], "price": p["price"],
            "url": p["url"], "surface": p["surface"], "rooms": p["rooms"],
            "commune": p["commune"], "n_mandats": p["n_mandats"]}


def ev_baisse(p, old_price):
    return {"type": "BAISSE", "id": p["canonical_id"], "title": p["title"],
            "old_price": old_price, "price": p["price"],
            "pct": round(100 * (p["price"] - old_price) / old_price, 1), "url": p["url"],
            "surface": p["surface"], "rooms": p["rooms"], "commune": p["commune"],
            "n_mandats": p["n_mandats"]}


def ev_ret(p):  # tel que chain.scan_grace le produit désormais
    return {"type": "RETIRE", "id": p["canonical_id"], "title": p["title"], "price": p["price"],
            "url": p["url"], "surface": p["surface"], "rooms": p["rooms"], "commune": p["commune"],
            "quartier": p["quartier"], "n_mandats": p["n_mandats"],
            "aliases": list(p["aliases"]), "first_seen": p["first_seen"]}


def _data_rows(table_html):
    return [r for r in re.findall(r"<tr[^>]*>.*?</tr>", table_html, re.S) if "<td" in r]


STATS_KEYS = {"biens", "inb", "cdc", "multi", "nouveaux", "retraits", "baisses"}


# --------------------------------------------------------------------------- #
# 1. Cas vide : aucun changement                                              #
# --------------------------------------------------------------------------- #
def test_email_zero_changes():
    props = [mkprop("a"), mkprop("b", quartier="Bas, Meudon")]
    full, email, stats = report_html.build(props, [], prev_max_id=10, today="2026-07-29")
    assert "Les changements" in email
    assert "Aucun changement depuis le dernier scan." in email
    assert "🆕 Nouveautés" not in email
    assert "🚫 Retraits" not in email
    assert (stats["nouveaux"], stats["baisses"], stats["retraits"]) == (0, 0, 0)
    assert STATS_KEYS.issubset(stats)


# --------------------------------------------------------------------------- #
# 2. Cas partiel : uniquement des nouveautés                                  #
# --------------------------------------------------------------------------- #
def test_email_partial_only_new():
    props = [mkprop(f"n{i}") for i in range(3)]
    events = [ev_new(p) for p in props]
    _, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-07-29")
    assert "🆕 Nouveautés" in email
    assert "⚡ Mouvements de prix" not in email
    assert "🚫 Retraits" not in email
    assert "Aucun changement" not in email
    assert stats["nouveaux"] == 3
    # chaque nouveauté = une ligne 8 colonnes
    block = email[email.find("🆕 Nouveautés"):email.find("mémo") if "mémo" in email else len(email)]
    for r in _data_rows(block):
        assert len(re.findall(r"<td[^>]*>", r)) == 8


# --------------------------------------------------------------------------- #
# 3. Cas complet : 5 nouveaux, 1 baisse, 3 retraits                           #
# --------------------------------------------------------------------------- #
def test_email_full_scenario():
    new = [mkprop(f"n{i}") for i in range(5)]
    moved = mkprop("m0", price=880_000)
    props = new + [moved]
    rets = [mkprop(f"r{i}", quartier="Vieux, Chaville", surface=110.0 + i) for i in range(3)]
    events = [ev_new(p) for p in new] + [ev_baisse(moved, 940_000)] + [ev_ret(p) for p in rets]

    _, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-07-29")

    for h in ("🆕 Nouveautés", "⚡ Mouvements de prix", "🚫 Retraits"):
        assert h in email
    # synthèse : vocabulaire « changements » et bons comptes
    assert "changements :" in email
    assert "5 nouveaux" in email and "1 baisse" in email and "3 retraits" in email
    # mouvement : la variation old → new figure dans la colonne Prix
    mv = email[email.find("⚡ Mouvements"):email.find("🚫 Retraits")]
    assert "→" in mv
    # retraits : 8 colonnes, Surface peuplée (le point dur du refactor)
    ret = email[email.find("🚫 Retraits"):email.find("mémo")]
    ret_rows = _data_rows(ret)
    assert len(ret_rows) == 3
    for r in ret_rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        assert len(tds) == 8
        assert "m²" in tds[2]           # Surface peuplée
        assert "retiré" in tds[7]       # Statut
    assert (stats["nouveaux"], stats["baisses"], stats["retraits"]) == (5, 1, 3)


# --------------------------------------------------------------------------- #
# 4. Coups de cœur démotés en mémo, avec indicateur récurrent                 #
# --------------------------------------------------------------------------- #
def test_cdc_demoted_memo(monkeypatch):
    monkeypatch.setattr(report_html.scoring, "score",
                        lambda listing: {"total": 6, "price_delta_pct": -8.0})
    recent = mkprop("300", aliases=["300"])      # id > prev_max_id -> récente
    old = mkprop("100", aliases=["100"])         # id < prev_max_id -> récurrent
    _, email, stats = report_html.build([recent, old], [], prev_max_id=200, today="2026-07-29")

    assert "mémo — coups de cœur dans le budget" in email
    assert "★ Coups de cœur dans le budget" not in email   # plus de titre proéminent
    assert ">récente<" in email and ">récurrent<" in email
    assert stats["cdc"] == 2


# --------------------------------------------------------------------------- #
# 5. Contrat : l'événement RETIRE porte l'état structurel du bien             #
# --------------------------------------------------------------------------- #
def test_retire_event_is_enriched():
    prev = [mkprop("z", surface=123.0, quartier="Parc, Meudon", first_seen="2025-03-03",
                   n_mandats=2, aliases=["z", "999"])]
    out, events, backlog = chain.scan_grace([], prev, today="2026-07-29", grace=1)
    ret = [e for e in events if e["type"] == "RETIRE"]
    assert len(ret) == 1
    e = ret[0]
    for k in ("surface", "rooms", "quartier", "commune", "url", "n_mandats", "aliases", "first_seen"):
        assert k in e, f"clé manquante dans l'event RETIRE : {k}"
    assert e["surface"] == 123.0
    assert e["quartier"] == "Parc, Meudon"
    assert e["first_seen"] == "2025-03-03"

    # et ce contrat suffit à rendre le retrait au format riche 8 colonnes
    _, email, _ = report_html.build([], events, prev_max_id=10, today="2026-07-29")
    ret_block = email[email.find("🚫 Retraits"):]
    rows = _data_rows(ret_block[:ret_block.find("mémo")] if "mémo" in ret_block else ret_block)
    assert rows and "m²" in re.findall(r"<td[^>]*>(.*?)</td>", rows[0], re.S)[2]
