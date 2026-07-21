#!/usr/bin/env python3
"""Orchestrateur veille (cloud) : collecte -> GARDE-FOU -> chaînage -> rapport -> email -> persistance."""
import argparse, json, datetime, pathlib, os, yaml
from veille_immo.models import Listing
from veille_immo import chain, report_html, mailer

MIN_RATIO = 0.6      # en dessous de 60% des biens précédents => collecte suspecte


def _alert(subject, errors, per_source, no_email):
    body = ("<p>La collecte semble bloquée/partielle (probable DataDome sur l'IP GitHub). "
            "<b>L'état n'a PAS été modifié</b> et le rapport normal n'a pas été envoyé.</p>"
            "<p>Par source : " + ", ".join(f"{k}={v}" for k, v in per_source.items()) + "</p>"
            "<ul>" + "".join(f"<li>{e}</li>" for e in errors) + "</ul>")
    print("ALERTE:", subject)
    if not no_email:
        try:
            mailer.send(subject, body, text_body="Collecte suspecte — état inchangé.")
        except Exception as e:
            print("alerte email échouée:", e)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.gha.yaml")
    ap.add_argument("--state", default="data/state_chained.json")
    ap.add_argument("--no-email", action="store_true")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    today = datetime.date.today().isoformat()

    prev = []
    sp = pathlib.Path(a.state)
    if sp.exists():
        prev = json.load(open(sp, encoding="utf-8")).get("properties", [])
    prev_n = len(prev)
    prev_max_id = max((int(x) for p in prev for x in p.get("aliases", [])), default=274139959)

    # Choix du collecteur : ScrapingBee si une clé est présente (fiable, IP résidentielle),
    # sinon Playwright headless (dépannage, souvent bloqué par DataDome sur IP GitHub).
    provider = ((cfg.get("scraper") or {}).get("provider") or "scrapedo").lower()
    if os.environ.get("SCRAPER_API_KEY"):
        if provider == "scrapingbee":
            from veille_immo import collector_scrapingbee as col
        else:
            from veille_immo import collector_scrapedo as col
        print(f"[veille] collecteur : {provider} (API, super={os.environ.get('SCRAPER_SUPER','true')})")
    else:
        try:
            from veille_immo import collector as col
            print("[veille] collecteur : Playwright headless (pas de SCRAPER_API_KEY)")
        except Exception:
            _alert(f"[Veille immo] ⚠ SCRAPER_API_KEY absent le {today} — collecte non effectuee",
                   ["SCRAPER_API_KEY non defini et collecteur headless indisponible"], {}, a.no_email)
            return 4
    rows, errors, per_source = col.collect(
        cfg["sources"], delay=cfg.get("politeness", {}).get("delay_seconds", 6))
    print(f"[veille] collecté {len(rows)} annonces (état précédent: {prev_n} biens)")

    listings = [Listing(id=r["id"], source="bd", url=r["url"], title=r["title"], price=r["price"],
                        surface=r["surface"], rooms=r["rooms"], quartier=r["quartier"]) for r in rows]
    collected = chain.build_properties(listings)

    # --- GARDE-FOU : collecte vide ou nettement inférieure => on n'écrase rien ---
    if not collected:
        _alert(f"[Veille immo] ⚠ collecte VIDE le {today}", errors, per_source, a.no_email)
        return 2
    if prev_n >= 20 and len(collected) < MIN_RATIO * prev_n:
        _alert(f"[Veille immo] ⚠ collecte partielle le {today} : "
               f"{len(collected)} biens vs {prev_n} attendus — état conservé",
               errors, per_source, a.no_email)
        return 3

    # communes dont la source a échoué (0 annonce) => gel (pas de faux retrait)
    src_commune = {s["name"]: s.get("commune") for s in cfg["sources"] if s.get("commune")}
    failed_communes = {src_commune[n] for n, cnt in per_source.items()
                       if cnt == 0 and src_commune.get(n)}
    grace = int(cfg.get("retrait_grace", 2))
    if failed_communes:
        print(f"[veille] communes gelées (source en échec) : {sorted(failed_communes)}")

    # chaînage FIABLE : hystérésis retraits + gel des communes non collectées
    curr, events = chain.scan_grace(collected, prev, today, failed_communes=failed_communes, grace=grace)
    full_html, email_html, stats = report_html.build(curr, events, prev_max_id, today, errors)
    print(f"[veille] {stats}")

    sp.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"schema": "chained-properties-v1", "updated_at": datetime.datetime.now().isoformat(),
               "properties": curr}, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = pathlib.Path("data/reports"); rep.mkdir(parents=True, exist_ok=True)
    (rep / f"rapport_{today}.html").write_text(full_html, encoding="utf-8")

    if not a.no_email:
        subj = (f"Veille immo — {today} : {stats['cdc']} coups de cœur, "
                f"{stats['nouveaux']} nouveaux, {stats['baisses']} baisses, {stats['retraits']} retraits")
        to = mailer.send(subj, email_html, text_body="Rapport de veille — voir HTML/pièce jointe.",
                         attachments=[(f"rapport_veille_{today}.html", full_html, "text/html")])
        print("email envoyé à", to)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
