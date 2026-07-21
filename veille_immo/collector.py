"""Collecte headless (Playwright) des annonces Belles Demeures pour un run cloud.

Remplace la collecte via navigateur local (Claude-in-Chrome). Sur un runner
GitHub Actions, on n'a pas le vrai Chrome connecté d'Antoine : on utilise un
Chromium headless avec quelques garde-fous anti-détection. Belles Demeures
protège ses pages (DataDome) : si une page renvoie 0 annonce ou une page de
challenge, on le SIGNALE (on n'invente rien) et le run alerte par email.
"""
import time
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

EXTRACT_JS = r"""() => {
  const clean = s => String(s||'').split('?')[0].split('#')[0];
  const AD = /\/annonces\/vente\/([^\/"'?]+)\/(\d{6,})\//;
  const PRICE = /(\d[\d\s  ]{4,})\s*€/;
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


def _dismiss_cookies(page):
    for sel in ["#didomi-notice-disagree-button", "button:has-text('Tout refuser')",
                "button:has-text('Continuer sans accepter')", "#onetrust-reject-all-handler",
                "button:has-text('Refuser')", "button:has-text('Accepter')"]:
        try:
            el = page.query_selector(sel)
            if el:
                el.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def collect(sources, delay=6.0, errors=None):
    """sources: [{name, url, expect(optionnel: mot attendu dans le titre)}].
    Retourne (listings, errors). errors liste les pages non récupérées."""
    errors = errors if errors is not None else []
    listings = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = browser.new_context(locale="fr-FR", user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        for i, src in enumerate(sources):
            try:
                page.goto(src["url"], wait_until="domcontentloaded", timeout=45000)
                if i == 0:
                    _dismiss_cookies(page)
                page.wait_for_timeout(1500)
                title = (page.title() or "")
                body = (page.inner_text("body") or "")[:400]
                if "n'existe pas" in body or "existe pas" in body:
                    errors.append(f"{src['name']} : page inexistante"); continue
                if any(k in body.lower() for k in ["datadome", "captcha", "vérifier que vous"]):
                    errors.append(f"{src['name']} : challenge anti-robot (DataDome)"); continue
                exp = src.get("expect")
                if exp and exp.lower() not in title.lower():
                    errors.append(f"{src['name']} : titre inattendu ('{title[:60]}') — source ignorée"); continue
                for _ in range(3):
                    page.mouse.wheel(0, 25000); page.wait_for_timeout(900)
                recs = page.evaluate(EXTRACT_JS)
                if not recs:
                    errors.append(f"{src['name']} : 0 annonce extraite")
                for r in recs:
                    if r["id"] not in listings:
                        listings[r["id"]] = r
            except Exception as e:
                errors.append(f"{src['name']} : {type(e).__name__} {str(e)[:80]}")
            time.sleep(delay)
        browser.close()
    return list(listings.values()), errors
