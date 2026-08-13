#!/usr/bin/env python3
"""Orchestrateur veille (cloud) : collecte -> GARDE-FOU -> chaînage -> rapport -> email -> persistance."""
import argparse, importlib.util, json, datetime, pathlib, os, re, yaml
from veille_immo.models import Listing
from veille_immo.errors import QuotaExhausted
from veille_immo import chain, identity, prices, report_html, mailer

MIN_RATIO = 0.6      # en dessous de 60% des biens précédents (hors communes gelées) => suspect
FLOOR_RATIO = 0.3    # plancher absolu : sous 30% du parc connu, plus de rapport du tout

# Affichage des communes (identity.commune renvoie une forme normalisée sans accent).
NOMS = {"sevres": "Sèvres", "ville-d'avray": "Ville-d'Avray", "meudon": "Meudon",
        "chaville": "Chaville", "viroflay": "Viroflay", "versailles": "Versailles",
        "saint-cloud": "Saint-Cloud", "velizy-villacoublay": "Vélizy-Villacoublay"}


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


def _commune(p):
    return identity.commune(p.get("quartier", "")) or p.get("commune", "")


def _nom(commune):
    return NOMS.get(commune) or re.sub(r"(^|[-\s])(\w)",
                                       lambda m: m.group(1) + m.group(2).upper(), commune)


def collecte_suffisante(prev, collected, failed_communes, min_ratio=MIN_RATIO,
                        floor_ratio=FLOOR_RATIO, min_prev=20):
    """La collecte est-elle exploitable ? -> (ok, biens collectés, biens attendus, périmètre).

    Deux garde-fous complémentaires :
      - un PLANCHER global : sous 30 % du parc connu, on ne prétend rien savoir du
        marché — alerte, état conservé, pas de rapport ;
      - au-dessus, on ne compare que le périmètre réellement collecté : les communes
        gelées (source muette ou en chute de volume) sortent des deux côtés de la
        balance. Sinon une seule commune en panne faisait échouer tout le scan — donc
        supprimait le rapport, alors que le chaînage sait déjà geler cette commune
        sans fabriquer de faux retraits."""
    frozen = set(failed_communes)
    n_prev = sum(1 for p in prev if _commune(p) not in frozen)
    n_coll = sum(1 for p in collected if _commune(p) not in frozen)
    if len(prev) >= min_prev and len(collected) < floor_ratio * len(prev):
        return False, len(collected), len(prev), "global"
    ok = not (n_prev >= min_prev and n_coll < min_ratio * n_prev)
    return ok, n_coll, n_prev, "actif"


def garde_prix(rows):
    """Refuse les prix invraisemblables AVANT tout stockage. -> nb de prix écartés.

    Un montant hors plafond résidentiel est un accident de parsing (compteur de
    carrousel collé au prix, montant du prêt, prix d'un lot), pas une affaire :
    le laisser entrer, c'est polluer l'état, les moyennes de zone et les
    mouvements du scan suivant. Le bien est CONSERVÉ, seul son prix est écarté —
    le supprimer fabriquerait un faux retrait puis une fausse remise en ligne."""
    n = 0
    for r in rows:
        if not prices.is_sane(r.get("price")):
            print(f"[veille] WARN prix invraisemblable écarté [{r.get('id')}] "
                  f"{r['price']} € (plafond {prices.sanity_max()}) — {r.get('url', '')}")
            r["price"] = None
            n += 1
    return n


def resolve_render(cli=None, env=None):
    """Rendu JS côté scraper : CLI > SCRAPER_RENDER > défaut (activé).

    Le rendu JS coûte 25 crédits/page contre 10 sans — mais SeLoger est une SPA
    React : sans rendu, ses sources peuvent tomber à 0. Le défaut reste donc le
    rendu, et `--no-render` sert à mesurer l'économie une fois, à la main."""
    if cli is not None:
        return bool(cli)
    brut = os.environ.get("SCRAPER_RENDER") if env is None else env
    return (brut or "true").strip().lower() != "false"


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.gha.yaml")
    ap.add_argument("--state", default="data/state_chained.json")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--suppress-alert-email", action="store_true",
                    help="n'envoie pas l'email d'alerte (utile pour la 1re tentative éco avant fallback résidentiel)")
    ap.add_argument("--strict", action="store_true",
                    help="échoue dès qu'une commune manque, au lieu de produire un rapport partiel "
                         "(utilisé par la tentative éco pour déclencher le fallback résidentiel)")
    ap.add_argument("--local", action="store_true",
                    help="collecte depuis un navigateur local (Playwright headed) au lieu de l'API : "
                         "zéro crédit, à lancer à la main quand le quota scrape.do est épuisé")
    ap.add_argument("--render", action=argparse.BooleanOptionalAction, default=None,
                    help="rendu JS côté scraper (défaut : activé, ou SCRAPER_RENDER). "
                         "--no-render économise ~15 crédits/page mais peut vider les "
                         "sources SeLoger (SPA React) : à vérifier source par source.")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    # La précédence est portée par l'environnement : les trois collecteurs le lisent
    # eux-mêmes, inutile de faire descendre le réglage dans trois signatures.
    render = resolve_render(a.render)
    os.environ["SCRAPER_RENDER"] = "true" if render else "false"
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    today = datetime.date.today().isoformat()

    prev, backlog, frozen_prev = [], [], {}
    sp = pathlib.Path(a.state)
    if sp.exists():
        st = json.load(open(sp, encoding="utf-8"))
        prev = st.get("properties", [])
        backlog = st.get("retired", [])          # biens retirés en attente d'une éventuelle remise en ligne
        frozen_prev = st.get("frozen", {})       # communes gelées : nb de scans consécutifs
        # Migration au chargement : les états écrits avant le correctif du parser
        # portent des prix pollués (compteur de carrousel collé au prix). Les laisser
        # tels quels ferait une fausse BAISSE de −92 % au premier scan corrigé.
        fixed = sum(prices.migrate_properties(x)[0] for x in (prev, backlog))
        if fixed:
            print(f"[veille] état migré : {fixed} prix corrigé(s) au chargement")
    prev_n = len(prev)
    prev_max_id = max((int(x) for p in prev for x in p.get("aliases", []) if str(x).isdigit()), default=274139959)

    # Choix du collecteur : --local (navigateur réel, zéro crédit) > API (si une clé est
    # présente) > navigateur réel en dernier recours. DataDome bloque les IP datacenter,
    # d'où l'API à proxy résidentiel sur GitHub ; en local, un Chromium headed passe.
    provider = ((cfg.get("scraper") or {}).get("provider") or "scrapedo").lower()
    if a.local or not os.environ.get("SCRAPER_API_KEY"):
        # playwright est une dépendance optionnelle : on le vérifie AVANT de collecter,
        # sinon l'échec surviendrait au milieu du run avec un message obscur.
        if importlib.util.find_spec("playwright") is None:
            _alert(f"[Veille immo] ⚠ collecte impossible le {today} : ni API, ni navigateur local",
                   ["playwright absent — `pip install playwright && python -m playwright install chromium`"],
                   {}, a.no_email or a.suppress_alert_email)
            return 4
        from veille_immo import collector_local as col
        raison = "--local" if a.local else "pas de SCRAPER_API_KEY"
        print(f"[veille] collecteur : navigateur local (Playwright, {raison})")
    elif provider == "scrapingbee":
        from veille_immo import collector_scrapingbee as col
        print(f"[veille] collecteur : {provider} (API, super={os.environ.get('SCRAPER_SUPER','true')}, "
              f"rendu JS {'activé' if render else 'DÉSACTIVÉ (~10 crédits/page)'})")
    else:
        from veille_immo import collector_scrapedo as col
        print(f"[veille] collecteur : {provider} (API, super={os.environ.get('SCRAPER_SUPER','true')}, "
              f"rendu JS {'activé' if render else 'DÉSACTIVÉ (~10 crédits/page)'})")
    # Crédits épuisés en cours de route : on récupère la collecte partielle plutôt que
    # de tout perdre (les communes non atteintes seront gelées comme une source en panne).
    quota = ""
    try:
        rows, errors, per_source = col.collect(
            cfg["sources"], delay=cfg.get("politeness", {}).get("delay_seconds", 6))
    except QuotaExhausted as e:
        rows, errors, per_source = e.rows, e.errors, e.per_source
        quota = (f"Crédits du fournisseur de scraping épuisés en cours de collecte ({e}) : "
                 f"les communes non atteintes sont gelées.")
        print("[veille]", quota)

    # Sources AGENCES (sites directs, HTML simple, sans anti-robot => gratuit).
    # Objectif : capter les exclusivités / avant-premières absentes du portail.
    ag_sources = cfg.get("agences") or []
    if ag_sources:
        from veille_immo import collector_agences
        ag_rows, ag_errors, ag_per = collector_agences.collect(ag_sources)
        rows = rows + ag_rows
        errors = errors + ag_errors
        per_source.update(ag_per)
        print(f"[veille] + {len(ag_rows)} annonces via sites d'agences")
    print(f"[veille] collecté {len(rows)} annonces (état précédent: {prev_n} biens)")
    n_ecartes = garde_prix(rows)
    if n_ecartes:
        print(f"[veille] {n_ecartes} prix invraisemblable(s) écarté(s) à la collecte")

    listings = [Listing(id=r["id"], source=r.get("agency") or "bd", url=r["url"],
                        title=r["title"], price=r["price"], surface=r["surface"],
                        rooms=r["rooms"], quartier=r["quartier"],
                        agency=r.get("agency", "")) for r in rows]
    collected = chain.build_properties(listings)

    # --- GARDE-FOU : collecte vide => on n'écrase rien ---
    if not collected:
        _alert(f"[Veille immo] ⚠ collecte VIDE le {today}", errors, per_source, a.no_email or a.suppress_alert_email)
        return 2

    # communes dont la source a échoué (0 annonce) => gel (pas de faux retrait)
    src_commune = {s["name"]: s.get("commune") for s in cfg["sources"] if s.get("commune")}
    failed_communes = {src_commune[n] for n, cnt in per_source.items()
                       if cnt == 0 and src_commune.get(n)}
    # + communes dont le VOLUME collecté chute fortement (collecte partielle : même
    #   remède que l'échec total, on gèle pour ne pas fabriquer de faux retraits)
    dropped = chain.volume_drop_communes(prev, collected)
    if dropped:
        print(f"[veille] communes gelées (chute de volume, collecte partielle) : {sorted(dropped)}")
    failed_communes |= dropped
    grace = int(cfg.get("retrait_grace", 3))
    if failed_communes:
        print(f"[veille] communes gelées au total : {sorted(failed_communes)}")

    # --- GARDE-FOU : le périmètre RÉELLEMENT collecté s'est-il effondré ? ---
    ok, n_coll, n_att, scope = collecte_suffisante(prev, collected, failed_communes)
    if not ok:
        perim = "" if scope == "global" else " hors communes gelées"
        _alert(f"[Veille immo] ⚠ collecte partielle le {today} : {n_coll} biens vs {n_att} attendus"
               f"{perim} — état conservé",
               errors, per_source, a.no_email or a.suppress_alert_email)
        return 3
    # mode strict (tentative éco) : toute lacune doit déclencher le fallback résidentiel
    if a.strict and (failed_communes or quota):
        raison = f"communes gelées {sorted(failed_communes)}" if failed_communes else "crédits épuisés"
        print(f"[veille] mode strict : collecte incomplète ({raison}) — "
              f"on laisse la main à la tentative suivante")
        return 3

    # suivi du gel : une commune gelée plusieurs scans d'affilée signale un vrai
    # problème de source (URL morte, quota), pas un simple aléa réseau.
    frozen_streak = {c: int(frozen_prev.get(c, 0)) + 1 for c in sorted(failed_communes)}
    frozen_labels = [_nom(c) + (f" — {n}e scan consécutif" if n >= 2 else "")
                     for c, n in sorted(frozen_streak.items())]
    if frozen_labels:
        print(f"[veille] gel : {'; '.join(frozen_labels)}")

    # chaînage FIABLE : hystérésis retraits + gel des communes + backlog remise en ligne
    curr, events, backlog = chain.scan_grace(collected, prev, today,
                                             failed_communes=failed_communes, grace=grace,
                                             backlog=backlog)
    n_relist = sum(1 for e in events if e["type"] == "REMISE_EN_LIGNE")
    if n_relist:
        print(f"[veille] {n_relist} remise(s) en ligne détectée(s) depuis le backlog")
    print(f"[veille] backlog retraits : {len(backlog)} bien(s) suivi(s)")
    # nb de communes CIBLES (une commune peut être servie par plusieurs sources) :
    # c'est le dénominateur du bandeau « scan non frais ».
    n_communes = len({c for c in src_commune.values() if c})
    full_html, email_html, stats = report_html.build(curr, events, prev_max_id, today, errors,
                                                    frozen=frozen_labels, note=quota,
                                                    n_communes=n_communes)
    print(f"[veille] {stats}")
    # diagnostic : détail des NOUVEAUX (pour repérer d'éventuels doublons non fusionnés)
    moves = [e for e in events if e["type"] in ("BAISSE", "HAUSSE")]
    for e in moves:
        print(f"[veille] {e['type']} [{e['id']}] {e['title'][:45]} : "
              f"{e['old_price']:,} -> {e['price']:,} ({e['pct']:+}%)".replace(",", " "))
    news = [e for e in events if e["type"] == "NOUVEAU"]
    if news:
        by_id = {p["canonical_id"]: p for p in curr}
        print(f"[veille] détail des {len(news)} nouveaux biens :")
        for e in news:
            p = by_id.get(e["id"], {})
            print(f"    {e['id']:<20} {str(e.get('price') or '?'):>9}€ "
                  f"{str(p.get('surface') or '?'):>7}m² {str(p.get('rooms') or '?'):>3}p "
                  f"{p.get('commune','?'):<14} mandats={p.get('n_mandats','?')}")

    sp.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"schema": "chained-properties-v2", "updated_at": datetime.datetime.now().isoformat(),
               "properties": curr, "retired": backlog, "frozen": frozen_streak},
              open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep = pathlib.Path("data/reports"); rep.mkdir(parents=True, exist_ok=True)
    (rep / f"rapport_{today}.html").write_text(full_html, encoding="utf-8")

    if not a.no_email:
        relist = f", {stats['remises']} remises en ligne" if stats.get("remises") else ""
        partiel = " ⚠ partiel" if (frozen_labels or quota) else ""
        subj = (f"Veille immo{partiel} — {today} : {stats['cdc']} coups de cœur, "
                f"{stats['nouveaux']} nouveaux{relist}, {stats['baisses']} baisses, {stats['retraits']} retraits")
        to = mailer.send(subj, email_html, text_body="Rapport de veille — voir HTML/pièce jointe.",
                         attachments=[(f"rapport_veille_{today}.html", full_html, "text/html")])
        print("email envoyé à", to)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
