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
from . import bd_parse, sl_parse
from .errors import QuotaExhausted

# Une source déclare son portail via `parser:` — même mécanique de récupération
# (proxy résidentiel + rendu JS), seul le balisage des cartes diffère.
PARSERS = {"bd": (bd_parse.parse_cards, "div.item.js_favoritesParent"),
           "seloger": (sl_parse.parse_cards, sl_parse.CARD)}

API = "https://api.scrape.do/"
ATTEMPTS = 3                                   # 3 essais par URL (502 fréquents et transitoires)
MAX_BACKOFF = 45                               # plafond d'attente entre deux essais (s)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
FATAL_STATUS = {401: "crédits épuisés ou abonnement suspendu",
                402: "paiement requis (abonnement)"}
LOW_CREDITS = 400                              # en dessous : on le signale dans le rapport
ROTATE_PAUSE = 60                              # pause avant la 1re requête d'un compte de secours

# Rendu JS : DÉSACTIVÉ par défaut depuis l'audit du 06/08/2026 (run GHA 31107448276).
# Mesuré sur une collecte réelle : sans rendu, les 10 sources répondent (SeLoger
# compris — la SPA sert du HTML exploitable) pour 100 crédits, contre 250 avec. Et
# depuis, le rendu FAIT PERDRE des sources : les cinq URL Belles Demeures tombent en
# HTTP 502 (DataDome relève le challenge JS quand la page est réellement exécutée) —
# 5 sources sur 10 le 13/08. `--render` / SCRAPER_RENDER=true le rallume au besoin.
RENDER_DEFAULT = False
_VRAI = {"1", "true", "vrai", "yes", "oui", "on"}


def render_enabled(env=None):
    """Rendu JS demandé ? Lit SCRAPER_RENDER, sinon RENDER_DEFAULT."""
    brut = os.environ.get("SCRAPER_RENDER") if env is None else env
    if brut is None or not str(brut).strip():
        return RENDER_DEFAULT
    return str(brut).strip().lower() in _VRAI


def _fetch(url, token, super_proxy=True, render=RENDER_DEFAULT, wait_selector=None):
    params = {"token": token, "url": url, "geoCode": "fr"}
    if render:
        params.update({"render": "true",
                       "waitSelector": wait_selector or "div.item.js_favoritesParent",
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


def tokens(api_key=None):
    """Jetons scrape.do disponibles, dans l'ordre d'utilisation.

    Plusieurs comptes peuvent être déclarés — utile pour cumuler des quotas ou pour
    garder un compte de secours : soit plusieurs jetons séparés par des virgules
    dans SCRAPER_API_KEY, soit SCRAPER_API_KEY_2, _3… (secrets GitHub distincts)."""
    if api_key is not None:                  # appel explicite : on n'ajoute rien d'autre
        bruts = [api_key]
    else:
        bruts = [os.environ.get("SCRAPER_API_KEY", "")]
        bruts += [os.environ.get(f"SCRAPER_API_KEY_{n}", "") for n in range(2, 6)]
    out = []
    for b in bruts:
        out += [t.strip() for t in re.split(r"[,\s]+", b or "") if t.strip()]
    return list(dict.fromkeys(out))          # dédoublonne en conservant l'ordre


def _rotate_pause():
    """Secondes d'attente au changement de compte (SCRAPER_ROTATE_PAUSE, 0 = aucune)."""
    try:
        return max(0, int(os.environ.get("SCRAPER_ROTATE_PAUSE", ROTATE_PAUSE)))
    except ValueError:
        return ROTATE_PAUSE


class _Keyring:
    """Trousseau de comptes : on bascule sur le suivant dès qu'un quota est épuisé."""

    def __init__(self, jetons, tag="scrapedo"):
        self.jetons = list(jetons)
        self.tag = tag
        self.i = 0
        self.budgets = [_Budget() for _ in self.jetons]

    @property
    def token(self):
        return self.jetons[self.i]

    def note(self, resp):
        self.budgets[self.i].note(resp)

    def rotate(self, raison):
        """-> True si un compte de secours a pris le relais.

        On temporise avant la première requête du compte suivant : enchaîner une
        salve de 401 avec des appels immédiats sur un compte neuf est une mauvaise
        manière, et la pause laisse aussi retomber une éventuelle limite de débit.
        Elle ne rend pas les comptes indépendants pour autant — même workload, même
        plage d'IP, même cadence : le délai ne change pas cette signature."""
        if self.i + 1 >= len(self.jetons):
            return False
        pause = _rotate_pause()
        print(f"[{self.tag}] compte {self.i + 1} : {raison} — bascule sur le compte "
              f"{self.i + 2}" + (f" après {pause} s" if pause else ""), flush=True)
        if pause:
            time.sleep(pause)
        self.i += 1
        return True


def _backoff(delay, attempt):
    """Back-off exponentiel + jitter : 1er échec ~delay, puis 2×, 4×… (plafonné)."""
    return min(delay * (2 ** (attempt - 1)) + random.uniform(0, delay / 2), MAX_BACKOFF)


def _get(url, keys, name, super_proxy, render, delay, wait_selector=None):
    """Télécharge une URL avec réessais. Retourne (html, erreur) ; l'un des deux est None.
    Lève QuotaExhausted quand PLUS AUCUN compte n'a de crédits (inutile d'insister)."""
    err, attempt = None, 0
    while attempt < ATTEMPTS:
        attempt += 1
        try:
            r = _fetch(url, keys.token, super_proxy, render, wait_selector)
            keys.note(r)
            if r.status_code in FATAL_STATUS:
                raison = FATAL_STATUS[r.status_code]
                if keys.rotate(raison):
                    attempt -= 1        # changer de compte ne consomme pas un essai
                    continue            # et on rejoue la MÊME url : rien n'est perdu
                raise QuotaExhausted(f"scrape.do HTTP {r.status_code} — {raison}")
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
    jetons = tokens(api_key)
    if not jetons:
        raise RuntimeError("SCRAPER_API_KEY manquant")
    if super_proxy is None:
        super_proxy = os.environ.get("SCRAPER_SUPER", "true").lower() != "false"
    if render is None:
        render = render_enabled()
    tag = "scrapedo" + ("/super" if super_proxy else "") + ("" if render else "/norender")
    keys = _Keyring(jetons, tag)
    if len(jetons) > 1:
        print(f"[{tag}] {len(jetons)} comptes disponibles (bascule automatique si quota épuisé)")
    listings, errors = {}, []
    # toutes les sources sont connues d'avance : une source non atteinte reste à 0,
    # ce qui gèle sa commune au lieu de la faire passer pour un déstockage.
    per_source = {src["name"]: 0 for src in sources}
    try:
        for src in sources:
            got, urls = {}, (src.get("urls") or [src["url"]])
            parse_cards, wait_selector = PARSERS[src.get("parser", "bd")]
            for url_try in urls:
                html, err = _get(url_try, keys, src["name"], super_proxy, render, delay,
                                 wait_selector)
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
        msg = f"{e} (tous les comptes épuisés : {len(jetons)})" if len(jetons) > 1 else str(e)
        errors.append(f"COLLECTE INTERROMPUE — {msg}")
        print(f"[{tag}] {msg} : arrêt de la collecte (les sources restantes sont gelées)")
        raise QuotaExhausted(msg, list(listings.values()), errors, per_source) from None
    finally:
        _log_budget(tag, keys, errors)
    return list(listings.values()), errors, per_source


def _log_budget(tag, keys, errors):
    """Journalise la consommation compte par compte, et prévient quand le dernier
    compte encore utilisable approche de la fin (les précédents sont déjà à sec)."""
    for n, budget in enumerate(keys.budgets, start=1):
        if budget.spent or budget.left is not None:
            left = "?" if budget.left is None else budget.left
            compte = f" compte {n}" if len(keys.budgets) > 1 else ""
            print(f"[{tag}]{compte} crédits consommés : {budget.spent} — restants : {left}")
    dispo = sum(b.left for b in keys.budgets if b.left is not None)
    if any(b.left is not None for b in keys.budgets) and dispo < LOW_CREDITS:
        errors.append(f"crédits scrape.do bientôt épuisés : {dispo} restants "
                      f"sur {len(keys.jetons)} compte(s)")
