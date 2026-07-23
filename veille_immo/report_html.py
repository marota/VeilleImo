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
    # biens attractifs en prix mais SANS score de zone (typiquement annonces d'agence
    # qui ne donnent que la commune) : ils ne peuvent pas être coups de cœur.
    anoter = sorted([r for r in inb if r["total"] is None and r["pd"] is not None and r["pd"] <= 0],
                    key=lambda r: r["pd"])
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
            ag = _BADGE_AG if _agency_of(p) else ""
            o += (f'<tr data-commune="{_esc(_commune_disp(p))}"{tr}><td style="{B}"><a href="{_esc(p["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{_esc(p["quartier"])}</a>{ag}'
                  f'<br><span style="color:#666;font-size:11px;">{_esc(p["title"])[:56]}</span></td>'
                  f'<td data-sort="{p["price"] or 0}" style="{B}font-weight:bold;white-space:nowrap;">{_euro(p["price"])}</td>'
                  f'<td data-sort="{p["surface"] or 0}" style="{B}white-space:nowrap;">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{p["n_mandats"]}" style="{B}text-align:center;">{p["n_mandats"]}</td>'
                  f'<td data-sort="{r["total"] if r["total"] is not None else -1}" style="{B}">{r["total"]}/6</td>'
                  f'<td data-sort="{r["pd"] if r["pd"] is not None else 9999}" style="{B}color:#2e7d32;">{_pdf(r["pd"])}</td>'
                  f'<td data-sort="{_esc(p.get("first_seen") or "")}" style="{B}white-space:nowrap;">{lbl}</td>'
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
                  f'<td data-sort="{_esc(p.get("first_seen") or "")}">{lbl}</td>'
                  f'<td style="font-weight:bold;">{_esc(comm)}{badge}</td>'
                  f'<td>{lien}</td></tr>')
        return o

    def multi_rows():
        o = ""
        for p in sorted([x for x in props if x["n_mandats"] > 1], key=lambda x: -x["n_mandats"]):
            al = ", ".join(f'<a href="{_esc(p["url"])}">{a}</a>' for a in p["aliases"])
            comm = _commune_disp(p)
            o += (f'<tr data-commune="{_esc(comm)}"><td data-sort="{p["n_mandats"]}" style="text-align:center;">{p["n_mandats"]}×</td>'
                  f'<td data-sort="{p["surface"] or 0}">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{p["price"] or 0}" style="font-weight:bold;">{_euro(p["price"])}</td>'
                  f'<td>{_esc(comm)}</td><td style="font-size:11px;color:#777;">{al}</td></tr>')
        return o

    def moves_rows(inline=False):
        B = 'padding:6px 9px;border-bottom:1px solid #eee;'
        o = ""
        for e in [x for x in events if x["type"] in ("BAISSE", "HAUSSE")]:
            col = "#2e7d32" if e["type"] == "BAISSE" else "#b00"
            surf = f'{e["surface"]:g} m²' if e.get("surface") else "?"
            rooms = f'{e["rooms"]}p' if e.get("rooms") else "?"
            lieu = _esc(e.get("commune") or "")
            label = lieu or "voir l" + chr(39) + "annonce"
            if e.get("url"):
                lien = f'<a href="{_esc(e["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{label}</a>'
            else:
                lien = f'<b>{label}</b>'

            nm = e.get("n_mandats", 1)
            o += (f'<tr><td style="{B}"><b style="color:{col}">{e["type"]}</b></td>'
                  f'<td style="{B}">{lien} <span style="color:#555;">· {surf} · {rooms}</span>'
                  f'<div style="color:#777;font-size:11px;">{_esc(e["title"])[:56]}</div></td>'
                  f'<td style="{B}white-space:nowrap;">{_euro(e["old_price"])} → <b>{_euro(e["price"])}</b></td>'
                  f'<td style="{B}color:{col};white-space:nowrap;font-weight:bold;">{e["pct"]:+} %</td>'
                  f'<td style="{B}text-align:center;">{nm}</td></tr>')
        return o

    def anoter_rows():
        B = 'padding:6px 9px;border-bottom:1px solid #eee;'
        o = ""
        for r in anoter:
            p = r["p"]
            lieu = _esc(p["quartier"]) if p["quartier"] else _esc(_commune_disp(p))
            o += (f'<tr data-commune="{_esc(_commune_disp(p))}"><td style="{B}"><a href="{_esc(p["url"])}" style="color:#8a6d1b;font-weight:bold;text-decoration:none;">{lieu}</a>'
                  f'<div style="color:#777;font-size:11px;">{_esc(p["title"])[:56]}</div></td>'
                  f'<td data-sort="{p["price"] or 0}" style="{B}font-weight:bold;white-space:nowrap;">{_euro(p["price"])}</td>'
                  f'<td data-sort="{p["surface"] or 0}" style="{B}white-space:nowrap;">{p["surface"]:g} m² · {p["rooms"] or "?"}p</td>'
                  f'<td data-sort="{r["pd"] if r["pd"] is not None else 9999}" style="{B}color:#2e7d32;">{_pdf(r["pd"])}</td>'
                  f'<td style="{B}">{_esc(_agency_of(p)) or "—"}</td></tr>')
        return o

    def ev_rows():
        o = ""
        for e in events:
            t = e["type"]
            titre = _esc(e["title"])[:64] or "voir l" + chr(39) + "annonce"
            url = e.get("url")
            # lien direct vers l'annonce pour tout mouvement encore en ligne (pas les retraits)
            corps = f'<a href="{_esc(url)}">{titre}</a>' if (url and t != "RETIRE") else titre
            if t == "NOUVEAU":
                o += f'<li><b style="color:#2e7d32;">NOUVEAU</b> {corps} — {_euro(e.get("price"))}</li>'
            elif t == "RETIRE":
                o += f'<li><b style="color:#8a8a8a;">RETIRÉ</b> {titre}</li>'
            else:
                col = "#2e7d32" if t == "BAISSE" else "#b00"
                o += (f'<li><b style="color:{col};">{t}</b> {corps} — '
                      f'{_euro(e.get("old_price"))} → <b>{_euro(e.get("price"))}</b> ({e.get("pct"):+}%)</li>')
        return o or "<li>Aucun mouvement.</li>"

    err_html = ("<div class='warn'><b>Sources non récupérées :</b><br>" + "<br>".join(_esc(x) for x in (errors or [])) + "</div>") if errors else ""
    synth = (f"{sum(len(p['aliases']) for p in props)} annonces → <b>{len(props)} biens uniques</b> · {n_multi} multi-mandats · "
             f"<b>{len(inb)} biens dans le budget</b> · <b>{len(cdc)} coups de cœur</b> · mouvements : {n_new} nouveaux, {n_baisse} baisses, {n_ret} retraits")

    moves = [e for e in events if e["type"] in ("BAISSE", "HAUSSE")]
    TH2 = 'style="padding:7px 9px;text-align:left;color:#5b4636;border-bottom:2px solid #c9a24a;background:#faf6ec;"'
    moves_block = ("" if not moves else
        f'<h3 style="font-size:17px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:20px;">'
        f'⚡ Mouvements de prix ({len(moves)})</h3>'
        f'<p style="font-size:12px;color:#777;font-style:italic;margin:5px 0;">Le signal le plus actionnable : un vendeur qui baisse son prix ouvre une fenêtre de négociation.</p>'
        f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-family:Georgia,serif;font-size:13px;">'
        f'<tr><th {TH2}></th><th {TH2}>Bien (lien)</th><th {TH2}>Prix</th><th {TH2}>Écart</th><th {TH2}>Mandats</th></tr>{moves_rows()}</table>')
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
<div class="synth"><b>Synthèse.</b> {synth}.</div>
<div class="toolbar"><label for="communeFilter">Filtrer par commune :</label>
<select id="communeFilter"><option value="">Toutes les communes</option></select>
<span id="filterCount" class="count"></span>
<span class="hint">↕ cliquez un en-tête de colonne pour trier.</span></div>
<h2>★ Coups de cœur dans le budget ({len(cdc)})</h2>
<p class="note">Confort de zone ≥ 5/6 <b>et</b> prix ≤ moyenne maisons de la commune. « Mandats » = nb d'annonces pour le même bien.</p>
<table class="sortable filterable"><tr><th>Bien (lien)</th><th>Prix</th><th>Surface</th><th>Mandats</th><th>Confort</th><th>vs moy.</th><th>En ligne (est.)</th><th>Statut</th></tr>{cdc_rows(True)}</table>
{anoter_block}
<h2>Biens dans vos critères ({len(inb)})</h2>
<p class="note">700 000–1 200 000 € · ≥ 90 m² · ≥ 4 p. — ● nouveau · ○ déjà suivi. <span style="background:#5b4636;color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;">AGENCE</span> = annonce d'un site d'agence.</p>
<table class="sortable filterable"><tr><th class="nosort"></th><th>Prix</th><th>Surf.</th><th>P.</th><th>Mandats</th><th>Conf.</th><th>vs moy.</th><th>En ligne (est.)</th><th>Commune</th><th>Quartier</th></tr>{inb_rows()}</table>
<h2>Mouvements depuis le dernier scan (chaînés par bien)</h2><ul style="font-size:13px;">{ev_rows()}</ul>
<h2>Biens en multi-mandats ({n_multi})</h2>
<table class="sortable filterable"><tr><th>Mandats</th><th>Surface</th><th>Prix</th><th>Commune</th><th class="nosort">Identifiants (alias)</th></tr>{multi_rows()}</table>
{err_html}
<p class="note">Scores de confort = scores de ZONE indicatifs ; confirmer le dénivelé réel au trajet piéton (≤ 20–25 m cumulés). « En ligne depuis » = first_seen chaîné, ou estimation par la séquence des identifiants tant que l'historique est court.</p>
{SCRIPT}
</div></body></html>"""

    email = f"""<div style="font-family:Georgia,serif;color:#2b2b2b;max-width:960px;">
<p style="color:#8a6d1b;font-size:12px;letter-spacing:1px;margin:0;">VEILLE IMMOBILIÈRE — OUEST PARISIEN</p>
<h2 style="font-size:22px;color:#3a2f1c;margin:3px 0;">Maison à acheter — scan du {today}</h2>
<div style="background:#faf6ec;border:1px solid #e6d9b8;border-radius:6px;padding:11px 15px;font-size:14px;color:#5b4636;"><b>Synthèse.</b> {synth}.</div>
{moves_block}
<h3 style="font-size:17px;color:#3a2f1c;border-bottom:2px solid #c9a24a;padding-bottom:5px;margin-top:18px;">★ Coups de cœur dans le budget ({len(cdc)})</h3>
<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-family:Georgia,serif;font-size:13px;">
<tr style="background:#faf6ec;"><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Bien (lien)</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Prix</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Surface</th><th style="padding:8px 9px;text-align:center;border-bottom:2px solid #c9a24a;">Mandats</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Confort</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">vs moy.</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">En ligne (est.)</th><th style="padding:8px 9px;text-align:left;border-bottom:2px solid #c9a24a;">Statut</th></tr>
{cdc_rows(True)}</table>
{anoter_block}
<p style="font-size:12px;color:#777;font-style:italic;">Rapport complet (biens du budget, multi-mandats, mouvements) en pièce jointe HTML. Scores de confort = scores de zone indicatifs.</p>
</div>"""
    stats = dict(biens=len(props), inb=len(inb), cdc=len(cdc), multi=n_multi, nouveaux=n_new, retraits=n_ret, baisses=n_baisse)
    return full, email, stats
