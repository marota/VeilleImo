"""Collecte locale via un navigateur réel (Playwright « headed ») — zéro crédit.

Pourquoi : DataDome (anti-robot de Belles Demeures) bloque les IP datacenter — donc
GitHub Actions, d'où le recours à un proxy résidentiel payant — mais aussi le
Chromium *headless* lancé depuis la machine (HTTP 403 vérifié). En revanche un
Chromium **headed** depuis une IP résidentielle passe (HTTP 200). C'est le mode de
dépannage manuel quand les crédits scrape.do sont épuisés :

    python run_veille.py --config config.gha.yaml --local --no-email

Prérequis : `pip install playwright && python -m playwright install chromium`.
La fenêtre est ouverte hors écran (`--window-position`) pour ne pas voler le focus.

Le HTML est parsé par bd_parse.parse_cards, exactement comme le collecteur
scrape.do : mêmes identifiants, mêmes champs, état chaînable sans rupture. Le
défilement déclenche le lazy-load des cartes — cette collecte est donc en pratique
un peu plus complète que celle de l'API (qui photographie la page sans dérouler).
"""
import os, time

from .bd_parse import parse_cards
from .collector_scrapedo import _title_ok

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BLOCKED = ("datadome", "captcha", "are human", "vérifier que vous")


def _scan_url(page, url, name, expect):
    """Charge une URL et en extrait les annonces. -> (records, erreur)."""
    r = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    status = r.status if r else 0
    if status >= 400:
        return None, f"{name} : HTTP {status} ({url[-40:]})"
    try:
        page.wait_for_selector("div.item.js_favoritesParent", timeout=15000)
    except Exception:
        pass
    body = (page.inner_text("body") or "")[:400].lower()
    if any(k in body for k in BLOCKED):
        return None, f"{name} : challenge anti-robot (DataDome) sur ...{url[-34:]}"
    title = page.title() or ""
    if not _title_ok(title, expect):
        return None, f"{name} : titre inattendu ('{title[:46]}') sur ...{url[-34:]}"
    for _ in range(3):                       # déroule la page : lazy-load des cartes
        page.mouse.wheel(0, 25000)
        page.wait_for_timeout(700)
    recs = parse_cards(page.content())
    if not recs:
        return None, f"{name} : 0 annonce sur ...{url[-34:]}"
    return recs, None


def collect(sources, delay=4.0, headless=None):
    """Même contrat que collector_scrapedo.collect : (rows, errors, per_source)."""
    from playwright.sync_api import sync_playwright   # import paresseux (dépendance optionnelle)
    if headless is None:                              # headless = bloqué par DataDome, mais
        headless = os.environ.get("VEILLE_HEADLESS") == "1"   # utile pour un test hors ligne
    listings, errors = {}, []
    per_source = {s["name"]: 0 for s in sources}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled",
            "--window-position=-3000,0", "--window-size=1366,900"])
        ctx = browser.new_context(locale="fr-FR", user_agent=UA,
                                  viewport={"width": 1366, "height": 900},
                                  timezone_id="Europe/Paris",
                                  extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                            "window.chrome={runtime:{}};")
        page = ctx.new_page()
        try:
            for src in sources:
                got, urls = {}, (src.get("urls") or [src["url"]])
                for url in urls:
                    recs, err = None, None
                    for attempt in (1, 2):            # un réessai (aléa réseau / rendu)
                        try:
                            recs, err = _scan_url(page, url, src["name"], src.get("expect"))
                        except Exception as e:
                            recs, err = None, f"{src['name']} : {type(e).__name__} {str(e)[:60]}"
                        if recs or (err and "titre inattendu" in err):
                            break                     # redirection : inutile de réessayer
                        time.sleep(delay)
                    if recs:
                        for rec in recs:
                            got.setdefault(rec["id"], rec)
                    elif err:
                        errors.append(err)
                    time.sleep(delay / 2)
                for rid, rec in got.items():
                    listings.setdefault(rid, rec)
                per_source[src["name"]] = len(got)
                print(f"[local] {src['name']}: {len(got)} annonces"
                      + (f"  ({len(urls)} url)" if len(urls) > 1 else ""), flush=True)
        finally:
            browser.close()
    return list(listings.values()), errors, per_source
