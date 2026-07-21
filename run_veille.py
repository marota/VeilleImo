#!/usr/bin/env python3
"""Orchestrateur veille (cloud) : collecte -> chaînage -> rapport -> email -> persistance.
  python run_veille.py --config config.gha.yaml
Identifiants email lus dans l'environnement (GMAIL_ADDRESS/GMAIL_APP_PASSWORD/MAIL_TO)."""
import argparse, json, datetime, pathlib, sys, yaml
from veille_immo.models import Listing
from veille_immo import chain, collector, report_html, mailer


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.gha.yaml")
    ap.add_argument("--state", default="data/state_chained.json")
    ap.add_argument("--no-email", action="store_true")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    today = datetime.date.today().isoformat()
    day = today

    prev = []
    sp = pathlib.Path(a.state)
    if sp.exists():
        prev = json.load(open(sp, encoding="utf-8")).get("properties", [])
    prev_max_id = max((int(a2) for p in prev for a2 in p.get("aliases", [])), default=274139959)

    rows, errors = collector.collect(cfg["sources"], delay=cfg.get("politeness", {}).get("delay_seconds", 6))
    if not rows:
        # collecte vide -> alerte, on ne touche pas à l'état
        subj = f"[Veille immo] ⚠ collecte vide le {today} (anti-robot ?)"
        body = "<p>Aucune annonce collectée — probable blocage DataDome en headless.</p><ul>" + \
               "".join(f"<li>{e}</li>" for e in errors) + "</ul>"
        if not a.no_email:
            try: mailer.send(subj, body, text_body="Collecte vide.")
            except Exception as e: print("email alert failed:", e)
        print("COLLECTE VIDE:", errors); return 2

    listings = [Listing(id=r["id"], source="bd", url=r["url"], title=r["title"], price=r["price"],
                        surface=r["surface"], rooms=r["rooms"], quartier=r["quartier"]) for r in rows]
    curr = chain.build_properties(listings)
    events = chain.diff_properties(curr, prev)
    curr = chain.chain(curr, prev, day)

    full_html, email_html, stats = report_html.build(curr, events, prev_max_id, today, errors)
    print(f"[veille] {stats}")

    # persistance
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
