"""Nettoyage one-shot des prix pollués d'un état persistant.

    python -m veille_immo.migrate_state data/state_chained.json

L'orchestrateur applique la même migration au chargement (run_veille.main) : ce
module ne sert qu'à assainir un fichier tout de suite, sans attendre le scan
suivant, et à voir le détail des corrections avant de committer l'état.
"""
import json
import pathlib
import sys

from . import chain, prices


def migrate_file(path, dry_run=False):
    """-> (corrigés, suspects, fusions). Réécrit le fichier sauf en dry-run."""
    p = pathlib.Path(path)
    st = json.loads(p.read_text(encoding="utf-8"))
    fixed = flagged = fusions = 0
    for cle in ("properties", "retired"):
        f, g = prices.migrate_properties(st.get(cle) or [])
        fixed += f
        flagged += g
        # doublons : deux entrées pour un même bien. L'orpheline n'étant jamais
        # réappariée, elle part en faux RETRAIT — ou survit indéfiniment sous gel.
        st[cle], n = chain.merge_duplicates(st.get(cle) or [])
        fusions += n
    # un bien ne peut pas être à la fois en ligne et au backlog des retraits
    vivants = {a for x in st.get("properties") or [] for a in chain.ids_annonces(x)}
    avant = len(st.get("retired") or [])
    st["retired"] = [b for b in st.get("retired") or [] if not (chain.ids_annonces(b) & vivants)]
    fusions += avant - len(st["retired"])
    if not dry_run and (fixed or fusions):
        p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return fixed, flagged, fusions


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    fichiers = [a for a in argv if not a.startswith("-")] or ["data/state_chained.json"]
    for f in fichiers:
        fixed, flagged, fusions = migrate_file(f, dry_run)
        print(f"[migrate] {f} : {fixed} prix corrigé(s), {flagged} à revérifier, "
              f"{fusions} doublon(s) fusionné(s)"
              + (" (dry-run, rien écrit)" if dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
