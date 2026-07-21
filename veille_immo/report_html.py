"""Construit le rapport HTML (rapport complet + corps email) au niveau BIEN."""
import html, datetime
from .models import Listing
from . import scoring

CRIT = dict(pmin=700000, pmax=1200000, smin=90, rmin=4)
MOIS = ['', 'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
ANCHOR_ID = 274139959      # id max observé au 6 juillet 2026
ANCHOR_DATE = datetime.date(2026, 7, 6)


def _euro(v): return (f"{v:,} €".replace(",", " ")) if v else "n.c."
def _pdf(v): return "—" if v is None else (("+" if v >= 0 else "") + f"{v} %")
def _esc(s): return html.escape(str(s or ""))


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
    return (p["price"] and p["surface"] and CRIT["pmin"] <= p["price"] <= CRIT["pmax"]
            and p["surface"] >= CRIT["smin"] and (not p["rooms"] or p["rooms"] >= CRIT["rmin"]))


def _is_recent(p, prev_max_id):
    nums = _num_aliases(p)
    return (min(nums) > prev_max_id) if nums else False


def build(props, events, prev_max_id, today, errors=None):
    today_max = max((int(a) for p in props for a in p["aliases"] if str(a).isdigit()), default=ANCHOR_ID)
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
    n_multi = sum(1 for p in props if p["n_mandats"] > 1)
    n_new = sum(1 for e in events if e["type"] == "NOUVEAU")
    n_ret = sum(1 for e in events if e["type"] == "RETIRE")
    n_baisse = sum(1 for e in events if e["type"] == "BAISSE")

    def cdc_rows(inline):
        o = ""
        for r in cdc:
            p = r["p"]; rec = _is_recent(p, prev_max_id); lbl, _ = _online_label(p, today_max)
            badge = ('<span style="background:#2e7d32;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">RÉCENTE</span>'
                     if rec else '<span style="background:#8a8a8a;color:#fff;font-size:10px;padding:1px 6px;border-radius:8px;">déjà en ligne</span>')
            B = 'padding:7px 9px;border-bottom:1px solid #eee;'
            tr = ' style="background:#f0f7f0;"' if rec else ''
            o += (f'<tr{tr}><td style="{B}"><a href="{_esc(p["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{_esc(p["quartier"])}</a>'
                  f'<br><span style="color:#666;font-size:11px;">{_esc(p["title"])[:56]}</span></td>'
                  f'<td style="{B}font-weight:bold;white-space:nowrap;">{_euro(p["price"])}</td>'
                  f'<td style="{B}white-space:nowrap;">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td style="{B}text-align:center;">{p["n_mandats"]}</td>'
                  f'<td style="{B}">{r["total"]}/6</td>'
                  f'<td style="{B}color:#2e7d32;">{_pdf(r["pd"])}</td>'
                  f'<td style="{B}white-space:nowrap;">{lbl}</td>'
                  f'<td style="{B}">{badge}</td></tr>')
        return o

    def inb_rows():
        o = ""
        for r in inb:
            p = r["p"]; conf = f"{r['total']}/6" if r["total"] is not None else "—"; lbl, _ = _online_label(p, today_max)
            dot = '<span style="color:#2e7d32;font-weight:700;">●</span>' if _is_recent(p, prev_max_id) else '○'
            o += (f'<tr><td>{dot}</td><td style="font-weight:bold;">{_euro(p["price"])}</td><td>{p["surface"]:g}</td>'
                  f'<td>{p["rooms"] or "?"}</td><td style="text-align:center;">{p["n_mandats"]}</td><td>{conf}</td>'
                  f'<td style="color:{"#2e7d32" if (r["pd"] is not None and r["pd"]<0) else "#333"};">{_pdf(r["pd"])}</td>'
                  f'<td>{lbl}</td><td><a href="{_esc(p["url"])}">{_esc(p["quartier"])}</a></td></tr>')
        return o

    def multi_rows():
        o = ""
        for p in sorted([x for x in props if x["n_mandats"] > 1], key=lambda x: -x["n_mandats"]):
            al = ", ".join(f'<a href="{_esc(p["url"])}">{a}</a>' for a in p["aliases"])
            o += f'<tr><td style="text-align:center;">{p["n_mandats"]}×</td><td>{p["surface"]:g} m² · {p["rooms"] or "?"}p</td><td style="font-weight:bold;">{_euro(p["price"])}</td><td>{_esc(p["commune"])}</td><td style="font-size:11px;color:#777;">{al}</td></tr>'
        return o

    def ev_rows():
        o = ""
        for e in events:
            if e["type"] == "NOUVEAU":
                o += f'<li><b>NOUVEAU</b> [{e["id"]}] {_esc(e["title"])[:64]} — {_euro(e.get("price"))}</li>'
            elif e["type"] == "RETIRE":
                o += f'<li><b>RETIRÉ</b> [{e["id"]}] {_esc(e["title"])[:64]}</li>'
            else:
                o += f'<li><b>{e["type"]}</b> [{e["id"]}] {_euro(e.get("old_price"))} → {_euro(e.get("price"))} ({e.get("pct"):+}%)</li>'
        return o or "<li>Aucun mouvement.</li>"

    err_html = ("<div class='warn'><b>Sources non récupérées :</b><br>" + "<br>".join(_esc(x) for x in (errors or [])) + "</div>") if errors else ""
    synth = (f"{sum(len(p['aliases']) for p in props)} annonces → <b>{len(props)} biens uniques</b> · {n_multi} multi-mandats · "
             f"<b>{len(inb)} biens dans le budget</b> · <b>{len(cdc)} coups de cœur</b> · mouvements : {n_new} nouveaux, {n_baisse} baisses, {n_ret} retraits")

    STYLE = """<style>body{font-family:Georgia,'Times New Roman',serif;color:#2b2b2b;background:#f4f1ea;margin:0;}
.wrap{max-width:980px;margin:0 auto;background:#fff;padding:30px 38px;}h1{font-size:24px;color:#3a2f1c;margin:2px 0;}
h2{font-size:18px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:26px;}
.k{color:#8a6d1b;font-size:12px;letter-spacing:1px;margin:0;}.sub{color:#555;font-size:13px;margin:0 0 12px;}
.synth{background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;padding:11px 15px;font-size:14px;color:#5b4636;}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0;}th{background:#faf6ec;color:#5b4636;text-align:left;padding:7px 9px;border-bottom:2px solid #c9a24a;font-size:12px;}
td{padding:6px 9px;border-bottom:1px solid #eee;vertical-align:top;}a{color:#8a6d1b;text-decoration:none;}
.note{font-size:12px;color:#777;font-style:italic;margin:6px 0;}.warn{background:#fff7f2;border-left:4px solid #d08a4a;padding:9px 13px;font-size:12.5px;color:#7a4a1e;margin:12px 0;}</style>"""
    full = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">{STYLE}</head><body><div class="wrap">
<p class="k">VEILLE IMMOBILIÈRE — OUEST PARISIEN</p>
<h1>Maison à acheter — scan du {today}</h1>
<p class="sub">Sèvres · Ville-d'Avray · Meudon · Chaville · Viroflay (+ voisins) — source Belles Demeures (exécution GitHub Actions)</p>
<div class="synth"><b>Synthèse.</b> {synth}.</div>
<h2>★ Coups de cœur dans le budget ({len(cdc)})</h2>
<p class="note">Confort de zone ≥ 5/6 <b>et</b> prix ≤ moyenne maisons de la commune. « Mandats » = nb d'annonces pour le même bien.</p>
<table><tr><th>Bien (lien)</th><th>Prix</th><th>Surface</th><th>Mandats</th><th>Confort</th><th>vs moy.</th><th>En ligne (est.)</th><th>Statut</th></tr>{cdc_rows(True)}</table>
<h2>Biens dans vos critères ({len(inb)})</h2>
<p class="note">700 000–1 200 000 € · ≥ 90 m² · ≥ 4 p. — ● nouveau · ○ déjà suivi.</p>
<table><tr><th></th><th>Prix</th><th>Surf.</th><th>P.</th><th>Mandats</th><th>Conf.</th><th>vs moy.</th><th>En ligne (est.)</th><th>Quartier</th></tr>{inb_rows()}</table>
<h2>Mouvements depuis le dernier scan (chaînés par bien)</h2><ul style="font-size:13px;">{ev_rows()}</ul>
<h2>Biens en multi-mandats ({n_multi})</h2>
<table><tr><th>Mandats</th><th>Surface</th><th>Prix</th><th>Commune</th><th>Identifiants (alias)</th></tr>{multi_rows()}</table>
{err_html}
<p class="note">Scores de confort = scores de ZONE indicatifs ; confirmer le dénivelé réel au trajet piéton (≤ 20–25 m cumulés). « En ligne depuis » = first_seen chaîné, ou estimation par la séquence des identifiants tant que l'historique est court.</p>
</div></body></html>"""

    email = f"""<div style="font-family:Georgia,serif;color:#2b2b2b;max-width:960px;">
<p style="color:#8a6d1b;font-size:12px;letter-spacing:1px;margin:0;">VEILLE IMMOBILIÈRE — OUEST PARISIEN</p>
<h2 style="font-size:22px;color:#3a2f1c;margin:3px 0;">Maison à acheter — scan du {today}</h2>
<div style="background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;padding:11px 15px;font-size:14px;color:#5b4636;"><b>Synthèse.</b> {synth}.</div>
<h3 style="font-size:17px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:18px;">★ Coups de cœur dans le budget ({len(cdc)})</h3>
<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-family:Georgia,serif;font-size:13px;">
<tr style="background:#faf6ec;"><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Bien (lien)</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Prix</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Surface</th><th style="padding:8px 9px;text-align:center;border-bottom:2px solid #c9a24a;">Mandats</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Confort</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">vs moy.</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">En ligne (est.)</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Statut</th></tr>
{cdc_rows(True)}</table>
<p style="font-size:12px;color:#777;font-style:italic;">Rapport complet (biens du budget, multi-mandats, mouvements) en pièce jointe HTML. Scores de confort = scores de zone indicatifs.</p>
</div>"""
    stats = dict(biens=len(props), inb=len(inb), cdc=len(cdc), multi=n_multi, nouveaux=n_new, retraits=n_ret, baisses=n_baisse)
    return full, email, stats
