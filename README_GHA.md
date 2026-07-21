# Veille immo — exécution autonome via GitHub Actions

Ce dépôt fait tourner la veille **sans dépendre de ton ordinateur** : GitHub
exécute le scan tous les 2 jours, chaîne les biens, et t'envoie le rapport par
email. L'état est conservé d'un run à l'autre (commit automatique).

## 1. Créer le dépôt
1. Crée un dépôt **privé** sur GitHub (ex. `veille-immo`).
2. Pousse le contenu de ce dossier tel quel (arborescence `veille_immo/`,
   `run_veille.py`, `config.gha.yaml`, `requirements-gha.txt`,
   `.github/workflows/veille.yml`, `data/state_chained.json`).

## 2. Déposer les secrets (une seule fois)
Dépôt → **Settings → Secrets and variables → Actions → New repository secret** :
| Secret | Valeur |
|---|---|
| `GMAIL_ADDRESS` | ton adresse Gmail expéditrice |
| `GMAIL_APP_PASSWORD` | le mot de passe d'application 16 caractères (https://myaccount.google.com/apppasswords) |
| `MAIL_TO` | `sebastianne.antoine@gmail.com` |

Les secrets sont chiffrés côté GitHub et injectés en variables d'environnement au
run ; ils ne sont jamais écrits sur disque ni visibles dans les logs.

## 3. Lancer / planifier
- **Automatique** : cron `30 6 */2 * *` = tous les 2 jours à **06:30 UTC**
  (≈ 08:30 Paris l'été, 07:30 l'hiver — GitHub Actions est en UTC, sans heure d'été).
- **À la main** : onglet **Actions → Veille immo → Run workflow** (bouton).
  Fais-le une fois pour vérifier que l'email arrive.

## 4. Ce que fait chaque run
1. Collecte headless (Playwright/Chromium) des sources de `config.gha.yaml`.
2. Chaînage par bien (empreinte lieu+description+prix+surface) vs `data/state_chained.json`.
3. Rapport HTML (coups de cœur avec colonne **Mandats** + « en ligne depuis » + statut,
   biens du budget, multi-mandats, mouvements).
4. Email (corps HTML + rapport complet en pièce jointe) via SMTP Gmail.
5. Persistance : commit de `data/state_chained.json` et `data/reports/…` + artefact.

## Points d'attention (honnêtes)
- **Anti-robot** : Belles Demeures utilise DataDome. En headless, une source peut
  être bloquée. Le collecteur le détecte, le signale dans le rapport, et si la
  collecte est **entièrement vide** il envoie un email d'alerte sans toucher à l'état.
  Si les blocages deviennent fréquents : ajouter des délais, un proxy résidentiel,
  ou passer par une API de scraping.
- **Cron GitHub** : peut être décalé de quelques minutes en cas de charge, et est
  **désactivé après 60 jours d'inactivité** du dépôt (un run manuel le réarme).
- **Minutes** : dépôt privé = quota de minutes Actions (largement suffisant ici) ;
  dépôt public = gratuit et illimité.
- **App passwords indisponibles** (compte Workspace restreint / Protection Avancée) :
  remplacer l'envoi SMTP par l'API Gmail en OAuth (scope `gmail.send`) — me le dire,
  je fournis la variante `mailer_oauth.py`.

## Test local (optionnel, sans email)
    pip install -r requirements-gha.txt && python -m playwright install chromium
    python run_veille.py --config config.gha.yaml --no-email

---

## Collecte fiable via ScrapingBee (recommandé)

Depuis une IP GitHub, DataDome (l'anti-robot de Belles Demeures) bloque souvent
la collecte headless. On passe donc par **ScrapingBee**, qui rend la page depuis
une **IP résidentielle française** en mode *stealth*.

1. Crée un compte sur https://www.scrapingbee.com (essai gratuit ~1000 crédits, sans CB).
2. Récupère ta **clé API** (dashboard).
3. Ajoute-la en secret du dépôt : **Settings → Secrets → Actions → New repository secret**,
   nom `SCRAPER_API_KEY`, valeur = ta clé.

Dès que `SCRAPER_API_KEY` est présent, `run_veille.py` utilise automatiquement le
collecteur ScrapingBee (sinon il retombe sur Playwright headless).

**Coût / crédits.** Le mode stealth (nécessaire contre DataDome) coûte ~75 crédits
par page. Périmètre = 5 pages → ~375 crédits par scan. Un scan tous les 2 jours
≈ 15 scans/mois ≈ ~5 600 crédits/mois. L'essai gratuit (1000 crédits) couvre
~2-3 scans de test ; au-delà, le plan payant le moins cher suffit largement.
Pour réduire : dans `veille_immo/collector_scrapingbee.py`, tu peux tester
`premium_proxy=true` (moins cher) à la place de `stealth_proxy=true` si DataDome
laisse passer, ou espacer les scans.

Le garde-fou reste actif : si ScrapingBee échoue et que la collecte est partielle,
l'état n'est pas modifié et tu reçois une alerte.

---

## Variante scrape.do (par défaut ici)

`scrape.do` ≠ ScrapingBee (services distincts). Le pipeline utilise **scrape.do**
par défaut (`config.gha.yaml` → `scraper.provider: scrapedo`), offre gratuite
**1000 crédits/mois renouvelables**.

1. Compte sur https://scrape.do → récupère ton **token** (dashboard).
2. Secret `SCRAPER_API_KEY` = ton token scrape.do.
3. (facultatif) **Test du mode économique** : ajoute une *Variable* de dépôt
   (Settings → Secrets and variables → Actions → **Variables**) nommée
   `SCRAPER_SUPER` = `false` → utilise le proxy datacenter (coût minimal). Si les
   sources reviennent vides/bloquées (DataDome), repasse à `true` (proxy
   résidentiel, franchit DataDome). Par défaut (`true`) c'est le mode fiable.

**Diagnostic** : le log du run affiche `[veille] collecteur : scrapedo (API, super=…)`
puis, par source, `[scrapedo/super] <source>: N annonces`. Une collecte vide côté
API + 0 crédit débité = le token n'a pas été pris en compte (secret absent) → le
run est retombé sur le headless.

Pour repasser sur ScrapingBee : `scraper.provider: scrapingbee` dans `config.gha.yaml`
et `SCRAPER_API_KEY` = ta clé ScrapingBee.

---

## Fiabilité des mouvements (anti-variance)

La complétude de la collecte varie d'un run à l'autre (une source peut renvoyer
moins d'annonces, ou échouer en 502). Sans précaution, ça produit de faux
« retraits » qui reviennent en « nouveaux » au run suivant. Deux mécanismes :

- **Hystérésis** (`retrait_grace: 2` dans `config.gha.yaml`) : un bien n'est
  déclaré RETIRÉ qu'après **2 scans consécutifs d'absence**. Une absence ponctuelle
  est ignorée (le bien reste « en sursis » dans l'état).
- **Gel par commune** : si la source d'une commune échoue (0 annonce / 502),
  ses biens sont **gelés** — ni retrait, ni compteur — puisqu'on ne peut rien
  conclure. Le rapport reste complet grâce à l'état conservé.

Chaque bien de l'état porte `misses` (absences consécutives) et `last_seen`.
Augmente `retrait_grace` (ex. 3) si tu veux être encore plus conservateur.
