"""Collecte via l'API scrape.do : rendu JS + proxy résidentiel (Super) français
pour franchir DataDome. Récupère le HTML rendu et le parse avec la même logique
que le collecteur ScrapingBee (réutilise bd_parse).

Clé lue dans l'environnement : SCRAPER_API_KEY (le 'token' scrape.do).
Réglage 'super_proxy' : True (résidentiel, franchit DataDome, plus cher) ou
False (datacenter, ~coût minimal, mais souvent bloqué).

Robustesse : scrape.do renvoie régulièrement 502 (« request has failed, please
try again ») sur une page pourtant valide — c'est ce qui vidait des communes
entières (une source à une seule URL = tout ou rien). On réessaie donc avec un
back-off exponentiel, et on distingue :
  - 429 / 5xx / timeouts  => réessayable (non facturé par scrape.do) ;
  - 401 / 402             => crédits épuisés : on arrête tout de suite (QuotaExhausted).
"""
import os, random, re, time, requests
from .bd_parse import parse_cards
from .errors import QuotaExhausted

API = "https://api.scrape.do/"
ATTEMPTS = 3                                   # 3 essais par URL (502 fréquents et transitoires)
MAX_BACKOFF = 45                               # plafond d'attente entre deux essais (s)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
FATAL_STATUS = {401: "crédits épuisés ou abonnement suspendu",
                402: "paiement requis (abonnement)"}
LOW_CREDITS = 400                              # en dessous : on le signale dans le rapport


def _fetch(url, token, super_proxy=True, render=True):
    params = {"token": token, "url": url, "geoCode": "fr"}
    if render:
        params.update({"render": "true",
                       "waitSelector": "div.item.js_favoritesParent",
                       "customWait": "3000"})
    if super_proxy:
        params["super"] = "true"      # proxy résidentiel (anti-DataDome)
    return requests.get(API, params=params, timeout=100)


class _Budget:
    """Suit la consommation de crédits via les en-têtes de réponse scrape.do."""

    def __init__(self):
        self.spent, self.left = 0, None

    def note(self, resp):
        def _int(v):
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return None
        cost = _int(resp.headers.get("Scrape.do-Request-Cost"))
        if cost:
            self.spent += cost
        left = _int(resp.headers.get("Scrape.do-Remaining-Credits"))
        if left is not None:
            self.left = left


def _backoff(delay, attempt):
    """Back-off exponentiel + jitter : 1er échec ~delay, puis 2×, 4×… (plafonné)."""
    return min(delay * (2 ** (attempt - 1)) + random.uniform(0, delay / 2), MAX_BACKOFF)


def _get(url, token, name, super_proxy, render, delay, budget):
    """Télécharge une URL avec réessais. Retourne (html, erreur) ; l'un des deux est None.
    Lève QuotaExhausted si le compte scrape.do ne sert plus (inutile d'insister)."""
    err = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = _fetch(url, token, super_proxy, render)
            budget.note(r)
            if r.status_code in FATAL_STATUS:
                raise QuotaExhausted(f"scrape.do HTTP {r.status_code} — {FATAL_STATUS[r.status_code]}")
            if r.status_code == 200:
                return r.text, None
            err = f"{name} : HTTP {r.status_code} ({url[-40:]})"
            if r.status_code not in RETRY_STATUS:
                break                                   # 4xx définitif : ne pas insister
        except requests.RequestException as e:
            err = f"{name} : {type(e).__name__} {str(e)[:60]}"
        if attempt < ATTEMPTS:
            time.sleep(_backoff(delay, attempt))
    if err and ATTEMPTS > 1:
        err += f" [{ATTEMPTS} essais]"
    return None, err


def _title_ok(title, expect):
    """expect peut être une chaîne ou une liste : au moins un motif doit apparaître."""
    if not expect:
        return True
    pats = expect if isinstance(expect, (list, tuple)) else [expect]
    return any(str(x).lower() in title.lower() for x in pats)


def collect(sources, delay=4.0, api_key=None, super_proxy=None, render=None):
    """Collecte TOUTES les URL d'une source et fusionne (couverture garantie même
    si l'une des URL est redirigée vers la recherche nationale)."""
    token = api_key or os.environ.get("SCRAPER_API_KEY")
    if not token:
        raise RuntimeError("SCRAPER_API_KEY manquant")
    if super_proxy is None:
        super_proxy = os.environ.get("SCRAPER_SUPER", "true").lower() != "false"
    if render is None:
        render = os.environ.get("SCRAPER_RENDER", "true").lower() != "false"
    budget = _Budget()
    tag = "scrapedo" + ("/super" if super_proxy else "") + ("" if render else "/norender")
    listings, errors = {}, []
    # toutes les sources sont connues d'avance : une source non atteinte reste à 0,
    # ce qui gèle sa commune au lieu de la faire passer pour un déstockage.
    per_source = {src["name"]: 0 for src in sources}
    try:
        for src in sources:
            got, urls = {}, (src.get("urls") or [src["url"]])
            for url_try in urls:
                html, err = _get(url_try, token, src["name"], super_proxy, render, delay, budget)
                if html is not None:
                    tm = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
                    title = (tm.group(1) if tm else "").strip()
                    if not _title_ok(title, src.get("expect")):
                        err = f"{src['name']} : titre inattendu ('{title[:46]}') sur ...{url_try[-34:]}"
                    else:
                        recs = parse_cards(html)
                        if recs:
                            for rec in recs:
                                got.setdefault(rec["id"], rec)
                        else:
                            err = f"{src['name']} : 0 annonce sur ...{url_try[-34:]}"
                if err:
                    errors.append(err)
                time.sleep(delay)
            for rid, rec in got.items():
                listings.setdefault(rid, rec)
            per_source[src["name"]] = len(got)
            print(f"[{tag}] {src['name']}: {len(got)} annonces"
                  + (f"  ({len(urls)} url)" if len(urls) > 1 else ""))
            time.sleep(delay)
    except QuotaExhausted as e:
        errors.append(f"COLLECTE INTERROMPUE — {e}")
        print(f"[{tag}] {e} : arrêt de la collecte (les sources restantes sont gelées)")
        raise QuotaExhausted(str(e), list(listings.values()), errors, per_source) from None
    finally:
        _log_budget(tag, budget, errors)
    return list(listings.values()), errors, per_source


def _log_budget(tag, budget, errors):
    if budget.spent or budget.left is not None:
        left = "?" if budget.left is None else budget.left
        print(f"[{tag}] crédits consommés : {budget.spent} — restants : {left}")
    if budget.left is not None and budget.left < LOW_CREDITS:
        errors.append(f"crédits scrape.do bientôt épuisés : {budget.left} restants")
