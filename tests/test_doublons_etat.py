"""Doublons de l'état : deux entrées pour un même bien.

Constaté le 16/08/2026 : 3 `canonical_id` en double et 7 alias partagés. Le bien
270362135 existait deux fois — une copie à jour (last_seen 16/08) et une figée au
10/08 — ce qui produisait une HAUSSE signalée sur un bien dont la fiche disait qu'il
n'avait pas été vu depuis six jours. L'historique montre le défaut dès le 07/08 :
il est antérieur au correctif des prix.

Mécanisme : le clustering finit par réunir deux annonces que deux scans successifs
avaient enregistrées séparément ; le scan suivant n'apparie qu'une des deux entrées,
l'autre reste orpheline. Elle part alors en faux RETRAIT — ou devient immortelle si
sa commune gèle, ce qui gonfle le compte de « biens uniques ».
"""
from __future__ import annotations

from veille_immo import chain

from tests.test_backlog_relisting import mkprop


def _copie(cid, aliases, last_seen, **kw):
    p = mkprop(cid, aliases=aliases, **kw)
    p["last_seen"] = last_seen
    return p


# --------------------------------------------------------------------------- #
# Fusion d'un état déjà pollué                                                 #
# --------------------------------------------------------------------------- #
def test_fusion_de_deux_copies_du_meme_bien():
    props = [_copie("270362135", ["270362135", "274504929", "275262967"], "2026-08-16",
                    price=950_000, first_seen="2026-07-19"),
             _copie("270362135", ["270362135"], "2026-08-10",
                    price=930_000, first_seen="2026-07-22", misses=1)]
    out, fusions = chain.merge_duplicates(props)
    assert fusions == 1 and len(out) == 1
    b = out[0]
    assert b["price"] == 950_000                       # la copie la plus fraîche gagne
    assert b["last_seen"] == "2026-08-16"
    assert b["first_seen"] == "2026-07-19"             # mais on garde la plus ancienne mise en ligne
    assert b["aliases"] == ["270362135", "274504929", "275262967"]
    assert b["misses"] == 0


def test_fusion_par_alias_partage_sans_meme_canonical():
    """Deux biens de canonical différents mais qui partagent une annonce : un id
    d'annonce n'appartient qu'à un seul bien, donc c'est le même."""
    props = [_copie("100", ["100", "300"], "2026-08-16"),
             _copie("200", ["200", "300"], "2026-08-13")]
    out, fusions = chain.merge_duplicates(props)
    assert fusions == 1
    assert out[0]["canonical_id"] == "100"             # le plus petit id = le plus ancien
    assert out[0]["aliases"] == ["100", "200", "300"]


def test_trois_copies_en_chaine():
    props = [_copie("1", ["1", "2"], "2026-08-10"),
             _copie("3", ["2", "3"], "2026-08-16"),
             _copie("4", ["4"], "2026-08-16")]
    out, fusions = chain.merge_duplicates(props)
    assert fusions == 1 and len(out) == 2
    fusionne = [p for p in out if p["canonical_id"] == "1"][0]
    assert fusionne["aliases"] == ["1", "2", "3"]


def test_aucun_doublon_rien_ne_bouge():
    props = [mkprop("a"), mkprop("b", aliases=["b"]), mkprop("c", aliases=["c"])]
    out, fusions = chain.merge_duplicates(props)
    assert fusions == 0 and [p["canonical_id"] for p in out] == ["a", "b", "c"]


def test_fusion_idempotente():
    props = [_copie("1", ["1", "2"], "2026-08-16"), _copie("1", ["1"], "2026-08-10")]
    out, _ = chain.merge_duplicates(props)
    assert chain.merge_duplicates(out) == (out, 0)


# --------------------------------------------------------------------------- #
# Prévention : le scan absorbe les doublons au lieu d'en laisser un orphelin   #
# --------------------------------------------------------------------------- #
def test_le_scan_absorbe_les_deux_copies():
    """Sans ça, l'entrée non appariée restait dans l'état et partait en faux RETRAIT
    trois scans plus tard — ou survivait indéfiniment sous gel."""
    prev = [_copie("100", ["100"], "2026-08-13", first_seen="2026-07-19"),
            _copie("200", ["200"], "2026-08-13", first_seen="2026-07-22", misses=1)]
    # le clustering a réuni les deux annonces : un seul bien courant les porte
    curr = [mkprop("100", aliases=["100", "200"])]
    out, events, backlog = chain.scan_grace(curr, prev, "2026-08-16", grace=3)
    assert len(out) == 1                               # plus d'orphelin dans l'état
    assert [e["type"] for e in events] == []           # ni retrait, ni nouveauté
    assert backlog == []
    assert out[0]["first_seen"] == "2026-07-19"        # la plus ancienne des deux
    assert out[0]["misses"] == 0


def test_labsorption_ne_signale_pas_de_faux_mouvement():
    """Les deux copies ont des prix différents : le mouvement doit être calculé sur
    la plus fraîche, pas sur la copie périmée."""
    prev = [_copie("100", ["100"], "2026-08-13", price=950_000),
            _copie("200", ["200"], "2026-07-20", price=1_100_000)]
    curr = [mkprop("100", aliases=["100", "200"], price=950_000)]
    _, events, _ = chain.scan_grace(curr, prev, "2026-08-16", grace=3)
    assert events == []


def test_deux_biens_distincts_ne_sont_pas_absorbes():
    prev = [mkprop("100", aliases=["100"], price=800_000, surface=95.0),
            mkprop("200", aliases=["200"], price=1_150_000, surface=210.0, misses=2)]
    curr = [mkprop("100", aliases=["100"], price=800_000, surface=95.0)]
    out, events, _ = chain.scan_grace(curr, prev, "2026-08-16", grace=3)
    assert [e["type"] for e in events] == ["RETIRE"]
    assert [e["id"] for e in events] == ["200"]
