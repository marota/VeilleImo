# Veille immo — exécution autonome via GitHub Actions

Ce dépôt fait tourner la veille **sans dépendre de ton ordinateur** : GitHub
exécute le scan tous les 3 jours, chaîne les biens, et t'envoie le rapport par
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
- **Automatique** : cron `30 6 */3 * *` = tous les 3 jours à **06:30 UTC**
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

## Run local sans crédit (`--local`) — le filet de secours

Quand le quota scrape.do est épuisé (HTTP 401) ou que tu veux simplement le rapport
du jour sans attendre le cron :

    pip install -r requirements-gha.txt playwright && python -m playwright install chromium
    python run_veille.py --config config.gha.yaml --local --no-email

Le rapport atterrit dans `data/reports/rapport_AAAA-MM-JJ.html`, l'état est mis à
jour normalement, **zéro crédit consommé**.

Pourquoi ça marche alors que GitHub est bloqué : DataDome bloque les IP datacenter
(GitHub Actions) **et** le Chromium *headless* même en local (HTTP 403 vérifié),
mais laisse passer un Chromium **headed** depuis une IP résidentielle (HTTP 200).
`veille_immo/collector_local.py` ouvre donc une vraie fenêtre — positionnée hors
écran pour ne pas voler le focus — et parse le HTML avec `bd_parse.parse_cards`,
exactement comme le collecteur scrape.do : mêmes identifiants, état chaînable sans
rupture. Le défilement déclenche le lazy-load, si bien que cette collecte est en
pratique **plus complète que celle de l'API** (mesuré le 05/08/2026 : Ville-d'Avray
39 annonces contre 20, Viroflay 39 contre 31).

Deux précautions :

- `--local` prime sur `SCRAPER_API_KEY` ; sans clé du tout, c'est le mode par défaut.
- L'hystérésis compte les **scans**, pas les jours : enchaîner plusieurs runs le même
  jour consomme les 3 scans de grâce et peut déclarer RETIRÉ un bien simplement
  absent du portail ce jour-là. Pour un essai, viser une copie de l'état :
  `--state /tmp/state_test.json`.

## Test local (sans email, sans toucher à l'état)
    python run_veille.py --config config.gha.yaml --local --no-email \
        --state /tmp/state_test.json

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
collecteur ScrapingBee (sinon il retombe sur le navigateur local, cf. `--local`).

**Coût / crédits.** Le mode stealth (nécessaire contre DataDome) coûte ~75 crédits
par page. Périmètre = 10 pages → ~750 crédits par scan. Un scan tous les 3 jours
≈ 10 scans/mois ≈ ~7 500 crédits/mois — soit trois fois le tarif scrape.do, qui
reste donc le fournisseur par défaut. L'essai gratuit (1000 crédits) couvre
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
« retraits » qui reviennent en « nouveaux » au run suivant. Trois mécanismes :

- **Hystérésis** (`retrait_grace: 3` dans `config.gha.yaml`) : un bien n'est
  déclaré RETIRÉ qu'après **3 scans consécutifs d'absence**. Une absence ponctuelle
  est ignorée (le bien reste « en sursis » dans l'état).
- **Gel par commune** : une commune est **gelée** — ni retrait, ni compteur —
  si sa source échoue (0 annonce / 502) **ou** si son volume collecté chute
  fortement d'un scan à l'autre (`chain.volume_drop_communes`, seuil < 50 % du
  volume précédent avec ≥ 4 biens auparavant : signature d'une collecte partielle).
- **Backlog des retraits** (`retired` dans `state_chained.json`, 180 j) : un bien
  retiré est archivé avec sa date et son prix de retrait. S'il **réapparaît** à un
  scan ultérieur (même id ou même bien par empreinte), il est signalé
  **REMISE_EN_LIGNE** (rappel date + prix de retrait, variation si le prix a bougé)
  plutôt que compté comme nouveau — et retiré du backlog. Les entrées de plus de
  180 jours sont purgées.

Chaque bien de l'état porte `misses` (absences consécutives) et `last_seen`.
Augmente `retrait_grace` si tu veux être encore plus conservateur.

---

## Budget crédits scrape.do (à surveiller — c'est la contrainte réelle)

Coût d'une page selon le mode (barème scrape.do) : datacenter 1, datacenter +
rendu JS **5**, résidentiel **10**, résidentiel + rendu JS **25**.

`config.gha.yaml` contient **10 URL** — une par commune et par portail, 5 Belles
Demeures + 5 SeLoger — et le cron tourne **tous les 3 jours** (≈ 10 runs/mois) :

| Mode                              | par run | par mois |
|-----------------------------------|--------:|---------:|
| résidentiel + rendu JS (défaut)   |     250 |   2 500  |
| résidentiel sans rendu JS         |     100 |   1 000  |
| datacenter + rendu JS (éco)       |      50 |     500  |

### Plusieurs comptes scrape.do (bascule automatique)

Un seul quota ne suffit pas ? Déclare des comptes de secours : la collecte bascule
sur le suivant dès qu'un compte répond **HTTP 401 « no credits »**, et **rejoue
l'URL refusée** — aucune commune n'est perdue au passage. Deux façons de faire :

- secrets distincts `SCRAPER_API_KEY_2`, `SCRAPER_API_KEY_3` (déjà câblés dans le
  workflow ; laisser vide s'il n'y en a qu'un) ;
- ou plusieurs jetons séparés par des virgules dans `SCRAPER_API_KEY`.

L'ordre est celui de la déclaration : le compte 1 est vidé avant qu'on touche au 2.
Le log indique la bascule et la consommation compte par compte :

    [scrapedo/super] 2 comptes disponibles (bascule automatique si quota épuisé)
    [scrapedo/super] compte 1 : crédits épuisés ou abonnement suspendu — bascule sur le compte 2 après 60 s
    [scrapedo/super] compte 1 crédits consommés : 175 — restants : 0
    [scrapedo/super] compte 2 crédits consommés : 75 — restants : 925

Une pause de 60 s précède la première requête du compte de secours
(`SCRAPER_ROTATE_PAUSE`, en secondes ; `0` la désactive) : enchaîner une salve de
401 avec des appels immédiats sur un compte neuf est une mauvaise manière, et la
pause laisse retomber une éventuelle limite de débit. **Elle ne rend pas les
comptes indépendants** : même jeu d'URL, mêmes plages d'IP GitHub Actions, même
User-Agent, même cadence — le délai ne change rien à cette signature.

L'alerte « crédits bientôt épuisés » dans le rapport se déclenche sur le **total**
restant, tous comptes confondus. Quand tous sont à sec, on retombe sur le
comportement habituel : collecte partielle exploitée, communes non atteintes gelées.

Note : cumuler les quotas gratuits de plusieurs comptes est souvent encadré par les
CGU des fournisseurs — à vérifier. Le mécanisme sert aussi, sans ambiguïté, à
chaîner un compte payant et un compte de secours.

**L'offre gratuite = 1000 crédits/mois.** À 2 500/mois on reste au-dessus du quota :
le run peut heurter le plafond en cours de mois et scrape.do répondre **HTTP 401
« no credits »**, ce qui vide des communes entières. Deux leviers :

1. **Passer à une offre payante** (le premier palier couvre très largement 2 500/mois) ;
2. **Tester le résidentiel sans rendu JS** : *Run workflow* → cocher `no_render`
   (ou `SCRAPER_RENDER=false`) : **−60 % de crédits, soit 1 000/mois — pile le quota
   gratuit**. Vérifier alors le compte des sources `seloger_*` en particulier :
   SeLoger est une SPA React, elle peut exiger le rendu là où Belles Demeures s'en
   passe. Si ces sources tombent à 0, ne pas garder `no_render`.

En dépannage, `--local` reste gratuit et collecte les deux portails (cf. plus haut).

### Ce que rapporte chaque URL (audit du 06/08/2026)

Mesuré id par id sur une collecte réelle, en croisant avec `criteria` :

| source | annonces | dans les critères | **exclusifs** dans les critères |
|---|---:|---:|---:|
| sevres_brancas    | 28 |   4 | 0 |
| ville_davray      | 40 |   9 | 5 |
| meudon            | 20 |   6 | 1 |
| chaville          | 34 |  23 | 1 |
| viroflay          | 38 |  28 | 9 |
| les 5 `seloger_*` | 110 | **107** | 89 |

SeLoger coûte le même prix que Belles Demeures et rapporte plus du double de biens
utiles. Les sources BD sont conservées quand même : ce sont les seules sur leur
commune si SeLoger change de balisage, et elles couvrent le segment > 1,2 M €.

C'est cet audit qui a fait tomber 5 URL redondantes (Chaville avait deux URL au jeu
identique, Viroflay quatre pages `pl-` n'apportant qu'une annonce à elles toutes) :
**−125 crédits/run pour zéro bien perdu** — vérifié, les deux configurations donnent
exactement les mêmes 190 biens. Refaire cet audit avant d'ajouter des URL :
`scratchpad/audit_urls.py` dans l'historique de la PR, ou simplement comparer les
jeux d'ids URL par URL.

Attention : la redondance d'URL n'était pas que de la couverture. Pendant les
orages de 502 chez scrape.do, les communes à plusieurs URL survivaient là où les
communes à URL unique tombaient à zéro. Avec une seule URL par commune, ce sont les
3 essais avec back-off qui jouent ce rôle — pas une seconde URL.

Le log de chaque run affiche `[scrapedo/super] crédits consommés : N — restants : M`,
et sous 400 crédits restants un avertissement est ajouté au rapport.

## Tentative éco → résidentiel (dans le workflow)

Le mode économique (datacenter) est **désactivé par défaut depuis le 31/07/2026** :
DataDome bloque désormais systématiquement ces IP sur Belles Demeures, la tentative
ne ramenait plus rien et coûtait quand même crédits et ~15 min avant de repasser en
résidentiel. Le run scheduled part donc **directement en résidentiel**.

Pour la réactiver ponctuellement : *Actions → Veille immo → Run workflow* → cocher
**`eco_first`**. Le workflow retrouve alors son comportement à deux étages :

- Étape 1 « Scan (éco - datacenter) » : `SCRAPER_SUPER=false`, `--strict`
  (la moindre commune manquante rend la main), `--suppress-alert-email`,
  `continue-on-error: true`.
- Étape 2 « Scan (résidentiel) » : s'exécute si l'étape 1 a échoué, sans
  suppression d'alerte.

Dans tous les cas : **un seul email par run**.

## Collecte partielle : rapport dégradé plutôt que silence

Une source muette ne doit plus faire disparaître le rapport. Le garde-fou est
désormais à deux niveaux (`run_veille.collecte_suffisante`) :

- **Plancher global** : si la collecte tombe sous **30 %** du parc connu, on
  n'envoie que l'alerte « état conservé » (rien de fiable à dire du marché).
- **Ratio par périmètre** : au-dessus du plancher, les communes gelées sortent des
  **deux** côtés de la comparaison. Exemple réel du 05/08/2026 : 59 biens collectés
  vs 116 connus déclenchaient l'alerte (< 60 %) alors que seules Ville-d'Avray et
  Meudon étaient muettes ; hors gel c'est 59 sur 74 attendus → le rapport part.

Le rapport et l'email portent alors un **bandeau « Collecte partielle — communes
gelées : … »**, le sujet est préfixé **`⚠ partiel`**, et l'état mémorise le nombre
de scans consécutifs de gel (`frozen` dans `state_chained.json`) : le bandeau
affiche « Meudon — 2e scan consécutif », signe qu'il faut aller voir la source.

Les biens des communes gelées sont **conservés à l'identique** : ni nouveauté, ni
retrait, ni mouvement de prix n'est fabriqué à partir d'une source en panne.

## Robustesse des téléchargements

- **scrape.do** : 3 essais par URL avec back-off exponentiel + jitter. Les 502
  (« request has failed, please try again ») sont fréquents et transitoires — ils
  vidaient des communes entières quand la source n'avait qu'une seule URL, et ces
  réponses ne sont **pas facturées**. Un **401/402** (crédits épuisés) arrête en
  revanche la collecte immédiatement : inutile d'insister, la collecte partielle
  déjà obtenue est remontée telle quelle et les communes non atteintes sont gelées.
- **Sites d'agences** : 3 essais par page, et surtout **isolation par URL** — un
  `ReadTimeout` sur la page 2 d'AETM ne fait plus perdre les 18 annonces déjà
  extraites des autres pages (c'est ce qui s'était produit le 05/08).

---

## Source SeLoger — le segment 700 k–1,2 M €

Belles Demeures est la **vitrine « luxe » du même back-office que SeLoger** (groupe
AVIV) : les deux partagent un seul espace d'identifiants — l'URL SeLoger d'un bien
haut de gamme redirige vers `bellesdemeures.com` sous le même id. Conséquence : une
maison à 740 000 € n'apparaît **jamais** sur Belles Demeures, alors qu'elle est au
cœur des critères. C'est un angle mort structurel, pas un défaut de collecte.

Les sources `parser: seloger` de `config.gha.yaml` comblent ce trou. Mesure du
06/08/2026 : **+70 annonces**, l'état passe de 128 à **179 biens** et les *biens
dans le budget* de 41 à **94**.

- **Chaînage natif** : ids partagés ⇒ un bien vu sur les deux portails fusionne
  tout seul (multi-mandats), sans préfixe ni migration d'état.
- **Filtrage côté serveur** : `priceMin/priceMax/roomCountMin/squareMeterMin` dans
  l'URL, calés sur `criteria`. Une page par commune suffit — peu de volume, peu de
  crédits. **Si tu changes `criteria`, pense à répercuter dans ces 5 URL.**
- **Code de localisation** (`locations=AD08FR…`) : numéroté par ordre alphabétique
  dans le département. Relevés — Chaville 36607, Meudon 36620, Sèvres 36629,
  Ville-d'Avray 36633, Viroflay 32622 ; en bonus Saint-Cloud 36627,
  Vélizy-Villacoublay 32607. Pour une commune nouvelle : la chercher sur seloger.com
  et lire `locations=` dans l'URL, ou ouvrir une SERP voisine et y relever les
  `AD08FR…` du JSON embarqué (chaque annonce porte le code de sa commune).
- **Ajouter un portail** se fait par un parser : `veille_immo/sl_parse.py` + une
  entrée dans `collector_scrapedo.PARSERS`. La récupération (proxy résidentiel,
  rendu JS, réessais, navigateur local) est mutualisée, seul le balisage change.

## Sources « agences locales » (gratuites, hors portail)

En plus de Belles Demeures, la veille interroge directement les sites d'agences
locales (`agences:` dans `config.gha.yaml`). Ces sites sont en HTML simple, sans
anti-robot : **aucun crédit scrape.do consommé**. Objectif : capter les
exclusivités et avant-premières absentes du portail, et fiabiliser le compteur
« Mandats ».

Le collecteur est **générique** : pour chaque lien d'annonce, il remonte au plus
petit conteneur contenant un prix et une surface, puis extrait prix / surface /
pièces / commune / quartier. Il gère les deux gabarits rencontrés (prix dans le
texte du lien, ou prix dans la carte).

Ajouter une agence = une entrée de config :
```yaml
- name: mon_agence                  # préfixe des ids générés
  agency: Nom affiché
  base: https://www.exemple.com
  href_filter: "/fiches/4-40-"      # ne garder que les MAISONS (ce CMS : 4-40- maison, 3-33- appart)
  id_regex: "_(\\d{5,})"
  commune_default: Sèvres           # si la commune n'est pas détectable dans la carte
  urls: ["https://www.exemple.com/annonces/transaction/Vente.html"]
```
Les doublons avec le portail sont fusionnés automatiquement par l'empreinte
(lieu + description + prix + surface) : pas de double comptage, et `n_mandats`
reflète le nombre réel de diffuseurs.
