"""Collecte headless (Playwright) — version durcie pour runner cloud.

Belles Demeures protège ses pages (DataDome). Depuis une IP de datacenter
(GitHub Actions) le blocage est fréquent : on gère les bannières de consentement,
on attend le rendu, on réessaie une fois, on journalise par source, et on
SIGNALE toute page bloquée/vide (jamais d'invention). Le garde-fou de volume
est appliqué en amont dans run_veille.py.
"""
import time

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

EXTRACT_JS = r"""() => {
  const clean = s => String(s||'').split('?')[0].split('#')[0];
  const AD = /\/annonces\/vente\/([^\/"'?]+)\/(\d{6,})\//;
  const PRICE = /(\d[\d\s  ]{4,})\s*€/;
  const SURF = /(\d{2,4}(?:[.,]\d{1,2})?)\s*m²/;
  const ROOMS = /(\d{1,2})\s*Pi[eè]ces?/i;
  const toI = t => { const d=String(t||'').replace(/[^\d]/g,''); return d?parseInt(d,10):null; };
  const out=[];
  document.querySelectorAll('div.item.js_favoritesParent').forEach(c=>{
    const a=c.querySelector('a[href*="/annonces/vente/"]'); if(!a) return;
    const href=clean(a.getAttribute('href')||''); const m=href.match(AD); if(!m) return;
    let url=href; if(url.startsWith('/')) url='https://www.bellesdemeures.com'+url;
    const loc=((c.querySelector('.location')||{}).textContent||'').replace(/\s+/g,' ').trim();
    const priceEl=(c.querySelector('.price')||{}).textContent||'';
    const desc=((c.querySelector('.desc')||{}).textContent||'').replace(/\s+/g,' ').trim();
    const full=(c.innerText||'').replace(/\s+/g,' ').trim();
    const price=toI((priceEl.match(PRICE)||full.match(PRICE)||[])[1]);
    const surf=(full.match(SURF)||[])[1];
    const rooms=(full.match(ROOMS)||[])[1];
    out.push({id:m[2], url, title: desc.slice(0,120), price,
      surface: surf?parseFloat(surf.replace(',','.')):null,
      rooms: rooms?parseInt(rooms,10):null, quartier: loc, agency:''});
  });
  return out;
}"""

CONSENT = ["#didomi-notice-disagree-button", "button:has-text('Continuer sans accepter')",
           "button#onetrust-reject-all-handler", "button:has-text('Tout refuser')",
           ".uc-deny-button", "button:has-text('Refuser')", "button:has-text('Accepter')",
           "#didomi-notice-agree-button"]


def _consent(page):
    for sel in CONSENT:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click(timeout=1500); page.wait_for_timeout(400); return
        except Exception:
            pass


def _blocked(page):
    body = ""
    try:
        body = (page.inner_text("body") or "")[:600].lower()
    except Exception:
        pass
    if any(k in body for k in ["datadome", "captcha", "vérifier que vous", "are human", "verifying"]):
        return "challenge anti-robot (DataDome)"
    if "existe pas" in body:
        return "page inexistante"
    return None


def _scan_one(page, src):
    page.goto(src["url"], wait_until="domcontentloaded", timeout=45000)
    _consent(page)
    try:
        page.wait_for_selector("div.item.js_favoritesParent", timeout=12000)
    except Exception:
        pass
    b = _blocked(page)
    if b:
        return None, f"{src['name']} : {b}"
    exp = src.get("expect")
    if exp and exp.lower() not in (page.title() or "").lower():
        return None, f"{src['name']} : titre inattendu ('{(page.title() or '')[:50]}') — source ignorée"
    for _ in range(3):
        page.mouse.wheel(0, 25000); page.wait_for_timeout(900)
    recs = page.evaluate(EXTRACT_JS)
    if not recs:
        return None, f"{src['name']} : 0 annonce extraite"
    return recs, None


def collect(sources, delay=6.0):
    from playwright.sync_api import sync_playwright   # import paresseux (testabilité)
    listings, errors, per_source = {}, [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox",
            "--disable-dev-shm-usage"])
        ctx = browser.new_context(locale="fr-FR", user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  timezone_id="Europe/Paris",
                                  extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                            "window.chrome={runtime:{}};")
        page = ctx.new_page()
        for src in sources:
            recs, err = None, None
            for attempt in (1, 2):                      # un réessai
                try:
                    recs, err = _scan_one(page, src)
                except Exception as e:
                    recs, err = None, f"{src['name']} : {type(e).__name__} {str(e)[:70]}"
                if recs:
                    break
                time.sleep(delay)
            n = 0
            if recs:
                for r in recs:
                    if r["id"] not in listings:
                        listings[r["id"]] = r
                n = len(recs)
            else:
                errors.append(err)
            per_source[src["name"]] = n
            print(f"[collect] {src['name']}: {n} annonces" + (f" — {err}" if err else ""))
            time.sleep(delay)
        browser.close()
    return list(listings.values()), errors, per_source
