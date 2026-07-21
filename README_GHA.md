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
