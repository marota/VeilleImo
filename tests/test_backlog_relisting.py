"""Backlog des retraits + détection des remises en ligne, et durcissement
anti-faux-retrait (grace=3 par défaut, gel des communes en chute de volume).

Contexte : des biens encore en ligne étaient signalés « retirés » lors d'un scan
à collecte partielle. On trace désormais les retraits dans un backlog (180 j) pour
signaler les remises en ligne, et on gèle les communes dont le volume s'effondre.
"""
from __future__ import annotations

import re

from veille_immo import chain, report_html


def mkprop(cid, price=950_000, surface=100.0, rooms=5, quartier="Centre, Sèvres",
           first_seen="2025-01-01", aliases=None, n_mandats=1, misses=0):
    return {"canonical_id": str(cid), "title": f"Maison {cid} pleine de charme",
            "price": price, "surface": surface, "rooms": rooms, "quartier": quartier,
            "commune": quartier.rsplit(",", 1)[-1].strip().lower(), "n_mandats": n_mandats,
            "aliases": aliases or [str(cid)], "first_seen": first_seen,
            "first_seen_estimated": False, "misses": misses,
            "url": f"https://www.bellesdemeures.com/annonces/{cid}"}


# --------------------------------------------------------------------------- #
# 1. Un retrait confirmé est versé au backlog                                 #
# --------------------------------------------------------------------------- #
def test_retrait_verse_au_backlog():
    prev = [mkprop("z", price=1_075_000, surface=183.0, quartier="Picardie, Versailles",
                   first_seen="2026-07-01", misses=2)]     # +1 ce scan => misses 3 >= grace
    out, events, backlog = chain.scan_grace([], prev, today="2026-07-29")  # grace=3 par défaut
    assert [e["type"] for e in events] == ["RETIRE"]
    assert len(backlog) == 1
    b = backlog[0]
    assert b["canonical_id"] == "z"
    assert b["retired_on"] == "2026-07-29"
    assert b["price"] == 1_075_000 and b["surface"] == 183.0
    assert "misses" not in b


# --------------------------------------------------------------------------- #
# 2. grace=3 : deux scans manqués ne retirent pas encore                       #
# --------------------------------------------------------------------------- #
def test_grace_3_deux_manques_en_sursis():
    prev = [mkprop("s", misses=1)]                 # +1 => misses 2 < 3
    out, events, backlog = chain.scan_grace([], prev, today="2026-07-29")
    assert events == [] and backlog == []
    assert len(out) == 1 and out[0]["misses"] == 2  # conservé en sursis


# --------------------------------------------------------------------------- #
# 3. Remise en ligne détectée depuis le backlog (recouvrement d'ID)            #
# --------------------------------------------------------------------------- #
def test_remise_en_ligne_par_id():
    backlog = [dict(mkprop("r", price=1_000_000, first_seen="2025-02-02"),
                    retired_on="2026-06-15")]
    curr = [mkprop("r", price=1_000_000, first_seen="ignoré")]   # revient sous le même id
    out, events, new_backlog = chain.scan_grace(curr, [], today="2026-07-29", backlog=backlog)
    types = [e["type"] for e in events]
    assert types == ["REMISE_EN_LIGNE"]             # pas NOUVEAU
    e = events[0]
    assert e["retired_on"] == "2026-06-15" and e["retired_price"] == 1_000_000
    assert e.get("pct") is None                     # prix inchangé
    assert new_backlog == []                         # retiré du backlog
    assert out[0]["first_seen"] == "2025-02-02"      # historique préservé


# --------------------------------------------------------------------------- #
# 4. Remise en ligne sous un NOUVEL id (même bien) + prix revu                 #
# --------------------------------------------------------------------------- #
def test_remise_en_ligne_republication_prix_revu():
    backlog = [dict(mkprop("old1", price=1_000_000, surface=120.0, rooms=5,
                           quartier="Brancas, Sèvres", first_seen="2025-01-10"),
                    retired_on="2026-05-01")]
    curr = [mkprop("new9", price=950_000, surface=120.0, rooms=5,
                   quartier="Brancas, Sèvres")]      # même bien, id différent, -5 %
    out, events, new_backlog = chain.scan_grace(curr, [], today="2026-07-29", backlog=backlog)
    assert [e["type"] for e in events] == ["REMISE_EN_LIGNE"]
    e = events[0]
    assert e["retired_price"] == 1_000_000 and e["price"] == 950_000
    assert e["pct"] == -5.0
    assert new_backlog == []
    assert "old1" in out[0]["aliases"] and "new9" in out[0]["aliases"]  # alias fusionnés


# --------------------------------------------------------------------------- #
# 5. Purge du backlog au-delà de la rétention (180 j)                          #
# --------------------------------------------------------------------------- #
def test_backlog_purge_retention():
    backlog = [
        dict(mkprop("vieux"), retired_on="2025-01-01"),   # > 180 j avant 2026-07-29
        dict(mkprop("recent"), retired_on="2026-06-01"),  # < 180 j -> conservé
    ]
    out, events, new_backlog = chain.scan_grace([], [], today="2026-07-29", backlog=backlog)
    ids = {b["canonical_id"] for b in new_backlog}
    assert ids == {"recent"}


# --------------------------------------------------------------------------- #
# 6. Détection des communes en chute de volume                                 #
# --------------------------------------------------------------------------- #
def test_volume_drop_communes():
    prev = ([mkprop(f"sv{i}", quartier="Q, Sèvres") for i in range(6)]
            + [mkprop(f"md{i}", quartier="Q, Meudon") for i in range(6)])
    curr = ([mkprop("sv0", quartier="Q, Sèvres")]                     # 6 -> 1 : chute
            + [mkprop(f"md{i}", quartier="Q, Meudon") for i in range(5)])  # 6 -> 5 : stable
    drop = chain.volume_drop_communes(prev, curr)
    assert "sevres" in drop and "meudon" not in drop


# --------------------------------------------------------------------------- #
# 7. Commune gelée : pas de retrait même si le bien est absent du scan         #
# --------------------------------------------------------------------------- #
def test_commune_gelee_pas_de_retrait():
    prev = [mkprop("g", quartier="Q, Sèvres", misses=2)]   # sinon retiré ce scan
    out, events, backlog = chain.scan_grace([], prev, today="2026-07-29",
                                            failed_communes={"sevres"})
    assert events == [] and backlog == []
    assert len(out) == 1 and out[0]["canonical_id"] == "g"  # gelé, inchangé


# --------------------------------------------------------------------------- #
# 8. Rendu email : bloc « Remises en ligne » + rappel retrait + synthèse       #
# --------------------------------------------------------------------------- #
def test_report_remise_en_ligne_rendu():
    props = [mkprop("back1", price=930_000, surface=118.0, quartier="Rive Droite, Viroflay")]
    events = [{"type": "REMISE_EN_LIGNE", "id": "back1", "title": props[0]["title"],
               "price": 930_000, "url": props[0]["url"], "surface": 118.0, "rooms": 5,
               "commune": "viroflay", "quartier": "Rive Droite, Viroflay",
               "n_mandats": 1, "first_seen": "2025-03-01",
               "retired_on": "2026-06-15", "retired_price": 990_000, "pct": -6.1}]
    _, email, stats = report_html.build(props, events, prev_max_id=10, today="2026-07-29")
    assert stats["remises"] == 1
    assert "🔄 Remises en ligne" in email
    assert "de retour" in email
    assert "remise en ligne" in email               # présent dans la synthèse
    # rappel de la date et du prix de retrait
    assert "retiré le 15 juin 2026" in email
    assert "990 000" in email                        # prix de retrait rappelé
    # la ligne est au format riche 8 colonnes
    block = email[email.find("🔄 Remises en ligne"):email.find("mémo") if "mémo" in email else len(email)]
    rows = [r for r in re.findall(r"<tr[^>]*>.*?</tr>", block, re.S) if "<td" in r]
    assert rows and len(re.findall(r"<td[^>]*>", rows[0])) == 8
