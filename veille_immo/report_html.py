"""Construit le rapport HTML (rapport complet + corps email) au niveau BIEN."""
import html, datetime
from .models import Listing
from . import prices, scoring

# Budget : bornes INCLUSES, surchargeables par VEILLEIMO_PRICE_MIN / _MAX (cf. prices).
CRIT = dict(pmin=prices.PRICE_MIN, pmax=prices.PRICE_MAX, smin=90, rmin=4)
# Part des communes cibles gelées à partir de laquelle le scan n'est plus « frais ».
STALE_RATIO = 0.8
MOIS = ['', 'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
ANCHOR_ID = 274139959      # id max observé au 6 juillet 2026
ANCHOR_DATE = datetime.date(2026, 7, 6)


def _euro(v): return (f"{v:,} €".replace(",", " ")) if v else "n.c."
def _pdf(v): return "—" if v is None else (("+" if v >= 0 else "") + f"{v} %")
def _esc(s): return html.escape(str(s or ""))


def _fr_date(iso):
    """'2026-07-15' -> '15 juil. 2026' ; renvoie la chaîne telle quelle si non ISO."""
    try:
        d = datetime.date.fromisoformat(iso)
    except (ValueError, TypeError):
        return _esc(iso)
    return f"{d.day} {MOIS[d.month]} {d.year}"


_COMMUNE_PRETTY = {
    "sevres": "Sèvres", "sèvres": "Sèvres",
    "ville-d'avray": "Ville-d'Avray", "ville d'avray": "Ville-d'Avray",
    "meudon": "Meudon", "chaville": "Chaville", "viroflay": "Viroflay",
    "saint-cloud": "Saint-Cloud", "versailles": "Versailles",
    "velizy-villacoublay": "Vélizy-Villacoublay",
}


def _commune_disp(p):
    """Commune en casse propre : segment après la virgule du quartier, sinon la
    table de correspondance (le quartier stocké garde la casse ; le champ commune
    n'est qu'un slug minuscule)."""
    q = (p.get("quartier") or "").strip()
    if "," in q:
        return q.rsplit(",", 1)[-1].strip()
    if q:
        return q
    slug = (p.get("commune") or "").strip()
    return _COMMUNE_PRETTY.get(slug.lower(), slug.title())


def _quartier_short(p):
    """Quartier sans la ville : segment avant la dernière virgule. Vide si le
    quartier se réduit à la commune (annonces qui ne donnent que la ville)."""
    q = (p.get("quartier") or "").strip()
    if "," in q:
        return q.rsplit(",", 1)[0].strip()
    return ""


def _agency_of(p):
    """Nom de l'agence si l'annonce vient d'un site d'agence, sinon ''. Repli sur
    l'id non numérique (les portails ont des id numériques ; les agences non)."""
    ag = (p.get("agency") or "").strip()
    if ag:
        return ag
    ids = [p.get("canonical_id")] + list(p.get("aliases", []))
    if any(i is not None and not str(i).isdigit() for i in ids):
        return "agence"
    return ""


_BADGE_AG = ('<span style="background:#5b4636;color:#fff;font-size:9px;padding:1px 5px;'
             'border-radius:8px;margin-left:5px;vertical-align:middle;">AGENCE</span>')


def _est_date(id_int, today_max):
    span = max((datetime.date.today() - ANCHOR_DATE).days, 1)
    slope = max((today_max - ANCHOR_ID) / span, 1)
    return ANCHOR_DATE + datetime.timedelta(days=(id_int - ANCHOR_ID) / slope)


def _num_aliases(prop):
    return [int(x) for x in prop.get("aliases", []) if str(x).isdigit()]


def _online_label(prop, today_max):
    fs = prop.get("first_seen")
    try:
        d = datetime.date.fromisoformat(fs) if fs else None
    except Exception:
        d = None
    if d and d < datetime.date.today():
        est = False
    else:                      # pas encore d'historique -> estimation par ID
        nums = _num_aliases(prop)
        if nums:
            d = _est_date(min(nums), today_max); est = True
        else:                       # annonce d'agence : pas d'ID séquentiel exploitable
            d = datetime.date.today(); est = True
    lbl = f"~{MOIS[d.month]} {d.year}" if d < datetime.date(2026, 6, 1) else f"~{d.day} {MOIS[d.month]}"
    return lbl, est


def _matches(p):
    return (p["price"] and p["surface"] and prices.in_budget(p["price"])
            and p["surface"] >= CRIT["smin"] and (not p["rooms"] or p["rooms"] >= CRIT["rmin"]))


def _titre(p):
    """Libellé affichable : le texte de carte brut mélange compteur, DPE, prix et
    prix/m² à la description, alors que le tableau a déjà des colonnes pour ça."""
    return prices.clean_title(p.get("title") if isinstance(p, dict) else p)


def _is_recent(p, prev_max_id):
    nums = _num_aliases(p)
    return (min(nums) > prev_max_id) if nums else False


def _score_of(p):
    """(total /6, écart au prix moyen de zone) pour un bien, ou (None, None)."""
    l = Listing(id=p.get("canonical_id"), source="", title=p.get("title", ""),
                price=p.get("price"), surface=p.get("surface"),
                rooms=p.get("rooms"), quartier=p.get("quartier", ""))
    sc = scoring.score(l) or {}
    return sc.get("total"), sc.get("price_delta_pct")


def _badge(text, bg):
    return (f'<span style="background:{bg};color:#fff;font-size:10px;padding:1px 6px;'
            f'border-radius:8px;white-space:nowrap;">{text}</span>')


# En-tête des tableaux de changements/coups de cœur : 8 colonnes homogènes.
_TH8 = 'style="padding:8px 9px;border-bottom:2px solid #c9a24a;text-align:left;font-size:12px;color:#5b4636;"'
_TH8C = 'style="padding:8px 9px;border-bottom:2px solid #c9a24a;text-align:center;font-size:12px;color:#5b4636;"'
_THEAD8 = (f'<tr style="background:#faf6ec;"><th {_TH8}>Bien (lien)</th><th {_TH8}>Prix</th>'
           f'<th {_TH8}>Surface</th><th {_TH8C}>Mandats</th><th {_TH8}>Confort</th>'
           f'<th {_TH8}>vs&nbsp;moy.</th><th {_TH8}>En ligne (est.)</th><th {_TH8}>Statut</th></tr>')


def _rich_row(p, total, pd, statut, today_max, old_price=None, highlight=False, note=None):
    """Une ligne au format riche 8 colonnes, partagée par les nouveautés, les
    mouvements, les retraits, les remises en ligne et les coups de cœur.
    `old_price` fait afficher la variation dans la colonne Prix ; `statut` est le
    contenu HTML de la dernière colonne (badge propre à chaque bloc) ; `note` est
    une ligne de rappel optionnelle sous le titre (ex : date/prix de retrait)."""
    B = 'padding:7px 9px;border-bottom:1px solid #eee;vertical-align:top;'
    lbl, _ = _online_label(p, today_max)
    tr = ' style="background:#f0f7f0;"' if highlight else ''
    ag = _BADGE_AG if _agency_of(p) else ""
    url = p.get("url") or ""
    lien_txt = _esc(p.get("quartier") or _commune_disp(p))
    bien = (f'<a href="{_esc(url)}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{lien_txt}</a>'
            if url else f'<b style="color:#8a6d1b;">{lien_txt}</b>')
    price_cell = (f'<span style="color:#999;">{_euro(old_price)}</span> → <b>{_euro(p.get("price"))}</b>'
                  if old_price else f'<b>{_euro(p.get("price"))}</b>')
    surf = p.get("surface")
    surf_cell = f'{surf:g} m² · {p.get("rooms") or "?"}p' if surf else "—"
    conf = f'{total}/6' if total is not None else "—"
    pd_col = "#2e7d32" if (pd is not None and pd < 0) else "#333"
    note_html = f'<br><span style="color:#8a6d1b;font-size:11px;font-style:italic;">{note}</span>' if note else ""
    return (
        f'<tr data-commune="{_esc(_commune_disp(p))}"{tr}>'
        f'<td style="{B}">{bien}{ag}<br><span style="color:#666;font-size:11px;">{_esc(_titre(p))[:56]}</span>{note_html}</td>'
        f'<td style="{B}white-space:nowrap;">{price_cell}</td>'
        f'<td style="{B}white-space:nowrap;">{surf_cell}</td>'
        f'<td style="{B}text-align:center;">{p.get("n_mandats") or 1}</td>'
        f'<td style="{B}">{conf}</td>'
        f'<td style="{B}color:{pd_col};">{_pdf(pd)}</td>'
        f'<td style="{B}white-space:nowrap;">{lbl}</td>'
        f'<td style="{B}">{statut}</td></tr>')


def _table8(body):
    return (f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;'
            f'font-family:Georgia,serif;font-size:13px;margin:6px 0 4px;">{_THEAD8}{body}</table>')


def build(props, events, prev_max_id, today, errors=None, frozen=(), note="",
          n_communes=0):
    today_max = max((int(a) for p in props for a in p["aliases"] if str(a).isdigit()), default=ANCHOR_ID)
    by_id = {p["canonical_id"]: p for p in props}

    # --- Budget : borne de TOUTES les vues, pas seulement des « biens dans vos
    # critères ». Un bien hors budget reste dans l'état (jamais retiré, donc ni faux
    # retrait ni fausse remise en ligne s'il y revient) : il n'est pas affiché, c'est
    # tout. Le filtrage est au RENDU et non à la collecte — le collecteur ramène des
    # pages de résultats entières, filtrer plus tôt n'économiserait aucun crédit.
    def _prix_evt(e):
        return e.get("price") or (by_id.get(e["id"]) or {}).get("price")

    events = [e for e in events if prices.in_budget(_prix_evt(e))]

    # --- Variations de prix aberrantes : partitionnées, jamais masquées. Ne concerne
    # que les mouvements TEMPORELS (prix précédent -> prix courant) ; la colonne
    # « vs moy. » compare à la moyenne de la commune et atteint légitimement −50 %.
    dmax = prices.delta_max_pct()

    def _anormal(e):
        return abs(e.get("pct") or 0) > dmax

    anomalies = [e for e in events if e["type"] in ("BAISSE", "HAUSSE") and _anormal(e)]
    ecartes = {id(e) for e in anomalies}
    events = [e for e in events if id(e) not in ecartes]

    scored = []
    for p in props:
        if not _matches(p):
            continue
        l = Listing(id=p["canonical_id"], source="", title=p["title"], price=p["price"],
                    surface=p["surface"], rooms=p["rooms"], quartier=p["quartier"])
        sc = scoring.score(l) or {}
        scored.append(dict(p=p, total=sc.get("total"), pd=sc.get("price_delta_pct")))
    inb = sorted(scored, key=lambda r: r["p"]["price"] or 0)
    cdc = sorted([r for r in inb if r["total"] and r["total"] >= 5 and r["pd"] is not None and r["pd"] <= 0],
                 key=lambda r: (-r["total"], r["pd"]))
    # biens attractifs en prix mais SANS score de zone (typiquement annonces d'agence
    # qui ne donnent que la commune) : ils ne peuvent pas être coups de cœur.
    anoter = sorted([r for r in inb if r["total"] is None and r["pd"] is not None and r["pd"] <= 0],
                    key=lambda r: r["pd"])
    multi = sorted([p for p in props if p["n_mandats"] > 1 and prices.in_budget(p.get("price"))],
                   key=lambda x: -x["n_mandats"])
    n_multi = len(multi)
    n_new = sum(1 for e in events if e["type"] == "NOUVEAU")
    n_ret = sum(1 for e in events if e["type"] == "RETIRE")
    n_baisse = sum(1 for e in events if e["type"] == "BAISSE")
    n_hausse = sum(1 for e in events if e["type"] == "HAUSSE")
    n_relist = sum(1 for e in events if e["type"] == "REMISE_EN_LIGNE")

    # --- lignes riches 8 colonnes pilotées par les événements (corps email) -----
    def new_rows():
        o = ""
        for e in [x for x in events if x["type"] == "NOUVEAU"]:
            p = by_id.get(e["id"])
            if not p:
                continue
            total, pd = _score_of(p)
            o += _rich_row(p, total, pd, _badge("🆕 nouveau", "#2e7d32"), today_max,
                           highlight=_is_recent(p, prev_max_id))
        return o

    def move_rows_rich():
        o = ""
        for e in [x for x in events if x["type"] in ("BAISSE", "HAUSSE")]:
            p = by_id.get(e["id"])
            if not p:
                continue
            total, pd = _score_of(p)
            up = e["type"] == "HAUSSE"
            st = _badge(f'{"↗" if up else "↘"} {e["pct"]:+} %', "#b00" if up else "#2e7d32")
            o += _rich_row(p, total, pd, st, today_max, old_price=e.get("old_price"))
        return o

    def anomalies_rows():
        o = ""
        for e in anomalies:
            p = by_id.get(e["id"]) or {
                "canonical_id": e["id"], "title": e.get("title", ""),
                "quartier": e.get("quartier", ""), "commune": e.get("commune", ""),
                "price": e.get("price"), "surface": e.get("surface"), "rooms": e.get("rooms"),
                "n_mandats": e.get("n_mandats", 1), "url": e.get("url", ""),
                "aliases": [e["id"]], "first_seen": e.get("first_seen")}
            total, pd = _score_of(p)
            st = _badge(f'🚨 {e["pct"]:+} %', "#b00")
            o += _rich_row(p, total, pd, st, today_max, old_price=e.get("old_price"))
        return o

    def ret_rows():
        o = ""
        for e in [x for x in events if x["type"] == "RETIRE"]:
            p = {"canonical_id": e["id"], "title": e.get("title", ""),
                 "quartier": e.get("quartier", ""), "commune": e.get("commune", ""),
                 "price": e.get("price"), "surface": e.get("surface"), "rooms": e.get("rooms"),
                 "n_mandats": e.get("n_mandats", 1), "url": e.get("url", ""),
                 "aliases": e.get("aliases", []), "first_seen": e.get("first_seen")}
            total, pd = _score_of(p)
            o += _rich_row(p, total, pd, _badge("retiré", "#8a8a8a"), today_max)
        return o

    def relist_rows():
        o = ""
        for e in [x for x in events if x["type"] == "REMISE_EN_LIGNE"]:
            p = by_id.get(e["id"]) or {
                "canonical_id": e["id"], "title": e.get("title", ""),
                "quartier": e.get("quartier", ""), "commune": e.get("commune", ""),
                "price": e.get("price"), "surface": e.get("surface"), "rooms": e.get("rooms"),
                "n_mandats": e.get("n_mandats", 1), "url": e.get("url", ""),
                "aliases": [e["id"]], "first_seen": e.get("first_seen")}
            total, pd = _score_of(p)
            rp = e.get("retired_price")
            ret_on = e.get("retired_on")
            date_txt = _fr_date(ret_on) if ret_on else "date inconnue"
            note = f"↩ retiré le {date_txt} à {_euro(rp)}"
            # si le prix a changé depuis le retrait, on l'affiche comme un mouvement
            old = rp if (rp and e.get("price") and rp != e.get("price")) else None
            o += _rich_row(p, total, pd, _badge("🔄 de retour", "#8a6d1b"), today_max,
                           old_price=old, highlight=True, note=note)
        return o

    def cdc_rows_email():
        o = ""
        for r in cdc:
            p = r["p"]; rec = _is_recent(p, prev_max_id)
            st = _badge("récente", "#2e7d32") if rec else _badge("récurrent", "#8a8a8a")
            o += _rich_row(p, r["total"], r["pd"], st, today_max, highlight=rec)
        return o

    def cdc_rows(inline):
        o = ""
        for r in cdc:
            p = r["p"]; rec = _is_recent(p, prev_max_id); lbl, _ = _online_label(p, today_max)
            badge = ('<span style="background:#2e7d32;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">RÉCENTE</span>'
                     if rec else '<span style="background:#8a8a8a;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">déjà en ligne</span>')
            B = 'padding:7px 9px;border-bottom:1px solid #eee;'
            tr = ' style="background:#f0f7f0;"' if rec else ''
            ag = _BADGE_AG if _agency_of(p) else ""
            o += (f'<tr data-commune="{_esc(_commune_disp(p))}"{tr}><td style="{B}"><a href="{_esc(p["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{_esc(p["quartier"])}</a>{ag}'
                  f'<br><span style="color:#666;font-size:11px;">{_esc(_titre(p))[:56]}</span></td>'
                  f'<td data-sort="{p["price"] or 0}" style="{B}font-weight:bold;white-space:nowrap;">{_euro(p["price"])}</td>'
                  f'<td data-sort="{p["surface"] or 0}" style="{B}white-space:nowrap;">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{p["n_mandats"]}" style="{B}text-align:center;">{p["n_mandats"]}</td>'
                  f'<td data-sort="{r["total"] if r["total"] is not None else -1}" style="{B}">{r["total"]}/6</td>'
                  f'<td data-sort="{r["pd"] if r["pd"] is not None else 9999}" style="{B}color:#2e7d32;">{_pdf(r["pd"])}</td>'
                  f'<td data-sort="{(p.get("first_seen") or "").replace("-", "")}" style="{B}white-space:nowrap;">{lbl}</td>'
                  f'<td style="{B}">{badge}</td></tr>')
        return o

    def inb_rows():
        o = ""
        for r in inb:
            p = r["p"]; conf = f"{r['total']}/6" if r["total"] is not None else "—"; lbl, _ = _online_label(p, today_max)
            dot = '<span style="color:#2e7d32;font-weight:700;">●</span>' if _is_recent(p, prev_max_id) else '○'
            comm = _commune_disp(p); quart = _quartier_short(p)
            badge = _BADGE_AG if _agency_of(p) else ""
            lien = f'<a href="{_esc(p["url"])}">{_esc(quart) if quart else "voir la fiche"}</a>'
            surf = p["surface"] or 0
            o += (f'<tr data-commune="{_esc(comm)}"><td>{dot}</td>'
                  f'<td data-sort="{p["price"] or 0}" style="font-weight:bold;">{_euro(p["price"])}</td>'
                  f'<td data-sort="{surf}">{p["surface"]:g}</td>'
                  f'<td data-sort="{p["rooms"] or 0}">{p["rooms"] or "?"}</td>'
                  f'<td data-sort="{p["n_mandats"]}" style="text-align:center;">{p["n_mandats"]}</td>'
                  f'<td data-sort="{r["total"] if r["total"] is not None else -1}">{conf}</td>'
                  f'<td data-sort="{r["pd"] if r["pd"] is not None else 9999}" style="color:{"#2e7d32" if (r["pd"] is not None and r["pd"]<0) else "#333"};">{_pdf(r["pd"])}</td>'
                  f'<td data-sort="{(p.get("first_seen") or "").replace("-", "")}">{lbl}</td>'
                  f'<td style="font-weight:bold;">{_esc(comm)}{badge}</td>'
                  f'<td>{lien}</td></tr>')
        return o

    def multi_rows():
        o = ""
        for p in multi:
            al = ", ".join(f'<a href="{_esc(p["url"])}">{a}</a>' for a in p["aliases"])
            comm = _commune_disp(p)
            o += (f'<tr data-commune="{_esc(comm)}"><td data-sort="{p["n_mandats"]}" style="text-align:center;">{p["n_mandats"]}×</td>'
                  f'<td data-sort="{p["surface"] or 0}">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{p["price"] or 0}" style="font-weight:bold;">{_euro(p["price"])}</td>'
                  f'<td>{_esc(comm)}</td><td style="font-size:11px;color:#777;">{al}</td></tr>')
        return o

    def anoter_rows():
        B = 'padding:6px 9px;border-bottom:1px solid #eee;'
        o = ""
        for r in anoter:
            p = r["p"]
            lieu = _esc(p["quartier"]) if p["quartier"] else _esc(_commune_disp(p))
            o += (f'<tr data-commune="{_esc(_commune_disp(p))}"><td style="{B}"><a href="{_esc(p["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{lieu}</a>'
                  f'<div style="color:#777;font-size:11px;">{_esc(_titre(p))[:56]}</div></td>'
                  f'<td data-sort="{p["price"] or 0}" style="{B}font-weight:bold;white-space:nowrap;">{_euro(p["price"])}</td>'
                  f'<td data-sort="{p["surface"] or 0}" style="{B}white-space:nowrap;">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{r["pd"] if r["pd"] is not None else 9999}" style="{B}color:#2e7d32;">{_pdf(r["pd"])}</td>'
                  f'<td style="{B}">{_esc(_agency_of(p)) or "—"}</td></tr>')
        return o

    def ev_rows():
        o = ""
        for e in events:
            t = e["type"]
            titre = _esc(_titre(e.get("title")))[:64] or "voir l" + chr(39) + "annonce"
            url = e.get("url")
            # lien direct vers l'annonce pour tout mouvement encore en ligne (pas les retraits)
            corps = f'<a href="{_esc(url)}">{titre}</a>' if (url and t != "RETIRE") else titre
            if t == "NOUVEAU":
                o += f'<li><b style="color:#2e7d32;">NOUVEAU</b> {corps} — {_euro(e.get("price"))}</li>'
            elif t == "RETIRE":
                o += f'<li><b style="color:#8a8a8a;">RETIRÉ</b> {titre}</li>'
            elif t == "REMISE_EN_LIGNE":
                var = (f' ({_euro(e.get("retired_price"))} → {_euro(e.get("price"))})'
                       if e.get("pct") is not None else f' — {_euro(e.get("price"))}')
                o += (f'<li><b style="color:#8a6d1b;">REMISE EN LIGNE</b> {corps}{var} '
                      f'<span style="color:#777;">· retiré le {_fr_date(e.get("retired_on"))}</span></li>')
            else:
                col = "#2e7d32" if t == "BAISSE" else "#b00"
                o += (f'<li><b style="color:{col};">{t}</b> {corps} — '
                      f'{_euro(e.get("old_price"))} → <b>{_euro(e.get("price"))}</b> ({e.get("pct"):+}%)</li>')
        return o or "<li>Aucun mouvement.</li>"

    # Bloc à part, en fin de rapport : au-delà de ±dmax % d'un scan à l'autre, un
    # « mouvement » est plus souvent un défaut de lecture (prix pollué, mandat
    # changé, honoraires basculés) qu'une vraie renégociation. Rien n'est masqué,
    # mais ces lignes ne comptent pas dans la synthèse.
    _pct_txt = f"{dmax:g}"
    anomalies_block = ("" if not anomalies else
        f'<h3 style="font-size:17px;color:#3a2f1c;border-bottom:2px solid #b00;padding-bottom:5px;'
        f'margin-top:22px;">🚨 Anomalies de prix (à vérifier) ({len(anomalies)})</h3>'
        f'<p style="font-size:12px;color:#777;font-style:italic;margin:5px 0;">'
        f'Variation de plus de ±{_pct_txt} % depuis le scan précédent : à confirmer sur l\'annonce '
        f'avant d\'y voir une négociation. Ces lignes ne sont pas comptées dans la synthèse.</p>'
        f'{_table8(anomalies_rows())}')

    # Bandeau ROUGE : quand la quasi-totalité des communes cibles est gelée, le
    # rapport ne décrit plus le marché du jour — le dire fort, pas dans le corps.
    stale = bool(n_communes) and len(frozen) >= STALE_RATIO * n_communes
    stale_html = ("" if not stale else
        f'<div style="background:#b00020;color:#fff;font-weight:bold;font-size:15px;'
        f'padding:12px 16px;border-radius:6px;margin:12px 0;letter-spacing:.3px;">'
        f'⚠ SCAN NON FRAIS — {len(frozen)}/{n_communes} communes cibles gelées, '
        f'les mouvements affichés sont potentiellement obsolètes.</div>')

    err_html = ("<div class='warn'><b>Sources non récupérées :</b><br>" + "<br>".join(_esc(x) for x in (errors or [])) + "</div>") if errors else ""

    def _plur(n, sing, plur=None):
        return f"{n} {sing if n <= 1 else (plur or sing + 's')}"

    # Collecte partielle : les communes dont la source n'a pas répondu sont GELÉES
    # (biens conservés en l'état, aucun retrait signalé) — il faut le dire, sinon un
    # rapport incomplet passerait pour un rapport complet.
    frozen_txt = ""
    if frozen:
        frozen_txt = (f"<b>Collecte partielle — {_plur(len(frozen), 'commune gelée', 'communes gelées')} : </b>"
                      + ", ".join(_esc(x) for x in frozen)
                      + ". Leurs biens sont conservés tels quels : ni nouveauté, ni retrait, "
                        "ni mouvement de prix n'est signalé sur ces communes tant que la source ne répond pas.")
    if note:
        frozen_txt = (frozen_txt + " " if frozen_txt else "<b>Collecte partielle.</b> ") + _esc(note)
    frozen_html = f"<div class='warn'>{frozen_txt}</div>" if frozen_txt else ""
    frozen_mail = (f'<div style="background:#fff6e5;border:1px solid #e0b96a;border-left:4px solid #c9822a;'
                   f'border-radius:6px;padding:10px 14px;font-size:13px;color:#6b4a12;margin:8px 0;">'
                   f'⚠ {frozen_txt}</div>') if frozen_txt else ""

    chg_parts = [_plur(n_new, "nouveau", "nouveaux")]
    if n_relist:
        chg_parts.append(_plur(n_relist, "remise en ligne", "remises en ligne"))
    chg_parts.append(_plur(n_baisse, "baisse"))
    if n_hausse:
        chg_parts.append(_plur(n_hausse, "hausse"))
    chg_parts.append(_plur(n_ret, "retrait"))
    if anomalies:
        chg_parts.append(f"{len(anomalies)} anomalie" + ("s" if len(anomalies) > 1 else "")
                         + " de prix (hors décompte)")
    synth = (f"{sum(len(p['aliases']) for p in props)} annonces → <b>{len(props)} biens uniques</b> · "
             f"{n_multi} multi-mandats dans le budget · "
             f"<b>{len(inb)} biens dans le budget</b> · <b>{len(cdc)} coups de cœur</b> · changements : {', '.join(chg_parts)}")

    moves = [e for e in events if e["type"] in ("BAISSE", "HAUSSE")]
    TH2 = 'style="padding:7px 9px;text-align:left;color:#5b4636;border-bottom:2px solid #c9a24a;background:#faf6ec;"'

    # « Les changements » : nouveautés / mouvements / retraits, tous au format riche
    # 8 colonnes, promus en tête de l'email (au même niveau, chacun une sous-table).
    def _sub(title, count, body, subtitle):
        if not body:
            return ""
        return (f'<h4 style="font-size:15px;color:#5b4636;margin:14px 0 2px;font-weight:normal;">'
                f'<b>{title}</b> <span style="color:#999;">({count})</span></h4>'
                f'<p style="font-size:12px;color:#777;font-style:italic;margin:3px 0;">{subtitle}</p>'
                f'{_table8(body)}')

    changes_body = (
        _sub("🆕 Nouveautés", n_new, new_rows(), "Biens apparus depuis le dernier scan.")
        + _sub("🔄 Remises en ligne", n_relist, relist_rows(),
               "Biens réapparus après un retrait : rappel de la date et du prix de retrait. "
               "Une republication à prix revu est un signal de négociation.")
        + _sub("⚡ Mouvements de prix", len(moves), move_rows_rich(),
               "Le signal le plus actionnable : une baisse ouvre une fenêtre de négociation.")
        + _sub("🚫 Retraits", n_ret, ret_rows(),
               "Biens disparus des annonces (vendus, retirés ou momentanément suspendus)."))
    changes_block = (
        f'<h3 style="font-size:18px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:20px;">'
        f'Les changements</h3>'
        + (changes_body or '<p style="font-size:13px;color:#777;font-style:italic;margin:6px 0;">'
                           'Aucun changement depuis le dernier scan.</p>'))
    anoter_block = ("" if not anoter else
        f'<h3 style="font-size:17px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:20px;">'
        f'À noter — bien placés en prix, quartier à préciser ({len(anoter)})</h3>'
        f'<p style="font-size:12px;color:#777;font-style:italic;margin:5px 0;">Dans le budget et sous la moyenne de la commune, mais sans quartier précis (annonces d\'agence) : '
        f'pas de score de confort, donc absents des coups de cœur. À qualifier manuellement (dénivelé, distance gare).</p>'
        f'<table class="sortable filterable" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-family:Georgia,serif;font-size:13px;">'
        f'<tr><th {TH2}>Bien (lien)</th><th {TH2}>Prix</th><th {TH2}>Surface</th><th {TH2}>vs moy.</th><th {TH2}>Agence</th></tr>{anoter_rows()}</table>')

    STYLE = """<style>body{font-family:Georgia,'Times New Roman',serif;color:#2b2b2b;background:#f4f1ea;margin:0;}
.wrap{max-width:980px;margin:0 auto;background:#fff;padding:30px 38px;}h1{font-size:24px;color:#3a2f1c;margin:2px 0;}
h2{font-size:18px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:26px;}
.k{color:#8a6d1b;font-size:12px;letter-spacing:1px;margin:0;}.sub{color:#555;font-size:13px;margin:0 0 12px;}
.synth{background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;padding:11px 15px;font-size:14px;color:#5b4636;}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0;}th{background:#faf6ec;color:#5b4636;text-align:left;padding:7px 9px;border-bottom:2px solid #c9a24a;font-size:12px;}
td{padding:6px 9px;border-bottom:1px solid #eee;vertical-align:top;}a{color:#8a6d1b;text-decoration:none;}
.note{font-size:12px;color:#777;font-style:italic;margin:6px 0;}.warn{background:#fff7f2;border-left:4px solid #d08a4a;padding:9px 13px;font-size:12.5px;color:#7a4a1e;margin:12px 0;}
.toolbar{position:sticky;top:0;z-index:5;margin:14px 0;padding:9px 13px;background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;font-size:13px;color:#5b4636;}
.toolbar label{font-weight:bold;margin-right:6px;}
.toolbar select{font-family:inherit;font-size:13px;padding:3px 7px;border:1px solid #c9a24a;border-radius:4px;background:#fff;color:#3a2f1c;}
.toolbar .count{color:#7a5f2a;font-style:italic;margin-left:12px;}
.toolbar .hint{color:#999;font-style:italic;margin-left:12px;font-size:12px;}
table.sortable th:not(.nosort){cursor:pointer;}table.sortable th:not(.nosort):hover{background:#f1e6c9;}
table.sortable th.sort-asc::after{content:" \\2191";color:#8a6d1b;}table.sortable th.sort-desc::after{content:" \\2193";color:#8a6d1b;}</style>"""
    SCRIPT = """<script>
(function(){
  function dataRows(t){return Array.prototype.filter.call(t.querySelectorAll('tr'),function(r){return r.getElementsByTagName('th').length===0;});}
  function val(tr,i){var c=tr.children[i];if(!c)return '';var d=c.getAttribute('data-sort');return d!==null?d:(c.textContent||'').trim();}
  function sortTable(t,i,th){
    var rows=dataRows(t),asc=!th.classList.contains('sort-asc');
    Array.prototype.forEach.call(t.querySelectorAll('th'),function(h){h.classList.remove('sort-asc','sort-desc');});
    th.classList.add(asc?'sort-asc':'sort-desc');
    rows.sort(function(a,b){
      var x=val(a,i),y=val(b,i),nx=parseFloat(x),ny=parseFloat(y),
          num=(x!==''&&y!==''&&!isNaN(nx)&&!isNaN(ny)),
          c=num?(nx-ny):x.localeCompare(y,'fr',{numeric:true});
      return asc?c:-c;});
    var p=rows[0]&&rows[0].parentNode;if(p)rows.forEach(function(r){p.appendChild(r);});
  }
  Array.prototype.forEach.call(document.querySelectorAll('table.sortable'),function(t){
    var head=t.querySelector('tr');if(!head)return;
    Array.prototype.forEach.call(head.children,function(th,i){
      if(th.classList.contains('nosort'))return;
      th.addEventListener('click',function(){sortTable(t,i,th);});});
  });
  var sel=document.getElementById('communeFilter');
  if(sel){
    var seen={};
    Array.prototype.forEach.call(document.querySelectorAll('table.filterable tr[data-commune]'),function(tr){
      var c=tr.getAttribute('data-commune');if(c)seen[c]=true;});
    Object.keys(seen).sort(function(a,b){return a.localeCompare(b,'fr');}).forEach(function(c){
      var o=document.createElement('option');o.value=c;o.textContent=c;sel.appendChild(o);});
    sel.addEventListener('change',function(){
      var v=sel.value,n=0;
      Array.prototype.forEach.call(document.querySelectorAll('table.filterable tr[data-commune]'),function(tr){
        var ok=(!v||tr.getAttribute('data-commune')===v);tr.style.display=ok?'':'none';if(ok)n++;});
      var cnt=document.getElementById('filterCount');
      if(cnt)cnt.textContent=v?(n+' bien(s) affiché(s) à '+v):'';});
  }
})();
</script>"""
    full = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">{STYLE}</head><body><div class="wrap">
<p class="k">VEILLE IMMOBILIÈRE — OUEST PARISIEN</p>
<h1>Maison à acheter — scan du {today}</h1>
<p class="sub">Sèvres · Ville-d'Avray · Meudon · Chaville · Viroflay (+ voisins) — source Belles Demeures (exécution GitHub Actions)</p>
{stale_html}
<div class="synth"><b>Synthèse.</b> {synth}.</div>
{frozen_html}
<div class="toolbar"><label for="communeFilter">Filtrer par commune :</label>
<select id="communeFilter"><option value="">Toutes les communes</option></select>
<span id="filterCount" class="count"></span>
<span class="hint">↕ cliquez un en-tête de colonne pour trier.</span></div>
<h2>★ Coups de cœur dans le budget ({len(cdc)})</h2>
<p class="note">Confort de zone ≥ 5/6 <b>et</b> prix ≤ moyenne maisons de la commune. « Mandats » = nb d'annonces pour le même bien.</p>
<table class="sortable filterable"><tr><th>Bien (lien)</th><th>Prix</th><th>Surface</th><th>Mandats</th><th>Confort</th><th>vs moy.</th><th>En ligne (est.)</th><th>Statut</th></tr>{cdc_rows(True)}</table>
{anoter_block}
<h2>Biens dans vos critères ({len(inb)})</h2>
<p class="note">{_euro(prices.price_min())}–{_euro(prices.price_max())} (bornes incluses) · ≥ {CRIT["smin"]} m² · ≥ {CRIT["rmin"]} p. — ● nouveau · ○ déjà suivi. <span style="background:#5b4636;color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;">AGENCE</span> = annonce d'un site d'agence.</p>
<table class="sortable filterable"><tr><th class="nosort"></th><th>Prix</th><th>Surf.</th><th>P.</th><th>Mandats</th><th>Conf.</th><th>vs moy.</th><th>En ligne (est.)</th><th>Commune</th><th>Quartier</th></tr>{inb_rows()}</table>
<h2>Mouvements depuis le dernier scan (chaînés par bien)</h2><ul style="font-size:13px;">{ev_rows()}</ul>
<h2>Biens en multi-mandats ({n_multi})</h2>
<table class="sortable filterable"><tr><th>Mandats</th><th>Surface</th><th>Prix</th><th>Commune</th><th class="nosort">Identifiants (alias)</th></tr>{multi_rows()}</table>
{anomalies_block}
{err_html}
<p class="note">Scores de confort = scores de ZONE indicatifs ; confirmer le dénivelé réel au trajet piéton (≤ 20–25 m cumulés). « En ligne depuis » = first_seen chaîné, ou estimation par la séquence des identifiants tant que l'historique est court.</p>
{SCRIPT}
</div></body></html>"""

    cdc_memo = ("" if not cdc else
        f'<p style="font-size:11px;color:#8a8a8a;letter-spacing:1.5px;text-transform:uppercase;'
        f'margin:24px 0 2px;border-top:1px solid #e6d9b8;padding-top:13px;">'
        f'mémo — coups de cœur dans le budget ({len(cdc)})</p>'
        f'<p style="font-size:12px;color:#777;font-style:italic;margin:2px 0;">Rappel des biens au meilleur '
        f'rapport confort/prix — souvent les mêmes d\'un scan à l\'autre ; « récurrent » = déjà présent au scan précédent.</p>'
        f'{_table8(cdc_rows_email())}')

    email = f"""<div style="font-family:Georgia,serif;color:#2b2b2b;max-width:960px;">
<p style="color:#8a6d1b;font-size:12px;letter-spacing:1px;margin:0;">VEILLE IMMOBILIÈRE — OUEST PARISIEN</p>
<h2 style="font-size:22px;color:#3a2f1c;margin:3px 0;">Maison à acheter — scan du {today}</h2>
<div style="background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;padding:11px 15px;font-size:14px;color:#5b4636;"><b>Synthèse.</b> {synth}.</div>
{stale_html}
{frozen_mail}
{changes_block}
{cdc_memo}
{anoter_block}
{anomalies_block}
<p style="font-size:12px;color:#777;font-style:italic;margin-top:14px;">Rapport complet (biens du budget, multi-mandats, mouvements) en pièce jointe HTML. Scores de confort = scores de zone indicatifs.</p>
</div>"""
    stats = dict(biens=len(props), inb=len(inb), cdc=len(cdc), multi=n_multi, nouveaux=n_new,
                 retraits=n_ret, baisses=n_baisse, hausses=n_hausse, remises=n_relist,
                 anomalies=len(anomalies), stale=stale)
    return full, email, stats
