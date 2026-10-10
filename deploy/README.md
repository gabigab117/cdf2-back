# Déploiement

L'application tourne sur un VPS Ubuntu 24.04, derrière nginx, une instance par environnement : `preprod` (données fictives) et `prod`. Ce dossier contient les modèles installés sur le serveur. Le front a les siens dans [cdf2-front/deploy](https://github.com/gabigab117/cdf2-front/tree/main/deploy).

## Organisation sur le serveur

```
/var/www/cdf3/<instance>/
├── back/
│   ├── repo.git/            miroir du dépôt (clé de déploiement en lecture seule)
│   ├── releases/<sha>/      une release par commit : code, venv, fichier REVISION
│   └── current -> releases/<sha>
├── front/
│   ├── releases/<sha>/      serveur Nitro construit par la CI
│   └── current -> releases/<sha>
├── backups/                 dumps de la base, faits avant une migration (0700)
└── shared/
    ├── back.env, front.env  configuration et secrets (0600)
    ├── static/              fichiers statiques collectés, servis par nginx
    └── private/             fichiers privés, servis par nginx après contrôle de Django
```

- **Utilisateur dédié** : tout tourne sous un utilisateur système (`cdf3`), sans mot de passe, qui n'a accès à aucune autre application du serveur.
- **Base de données** : PostgreSQL 17, en authentification « peer » par socket local. Aucun mot de passe de base n'existe.
- **Fichiers privés** (`shared/private/`, les documents déposés) :
  - `back.env` en donne le chemin à l'API (`MEDIA_ROOT`). Sans lui, la release échoue, plutôt que d'écrire dans son propre dossier ;
  - seule l'API y écrit : c'est le seul chemin inscriptible de son unité (`ReadWritePaths`) ;
  - nginx les lit, mais les autres comptes du serveur ne les lisent pas. Le dossier appartient à `cdf3`, groupe `www-data`, en `2750` : le bit setgid fait hériter ce groupe aux fichiers et dossiers créés dedans. Les réglages de production les créent en `640` et `750` :

    ```bash
    chgrp www-data /var/www/cdf3/<instance>/shared/private
    chmod 2750 /var/www/cdf3/<instance>/shared/private
    ```

  - l'API écrit chaque fichier à partir des octets reçus. Un gros envoi, déplacé depuis son fichier temporaire, garderait le groupe `cdf3`, que nginx ne lit pas.

## Une release

[`release-back.sh`](release-back.sh) est installé en `/usr/local/bin/cdf3-release-back`, propriété de root.
- **Appel par la CI** : la CI le déclenche par une clé SSH restreinte à cette seule commande (`restrict,command="cdf3-release-back <instance>"`). Le seul paramètre transmis est le SHA du commit testé.
- **Appel à la main** : `sudo -u cdf3 cdf3-release-back <instance> <sha>`.

Étapes :
1. **Vérification du commit** : il doit appartenir à `main`. Une seule release à la fois (`flock`).
2. **Création de la release** : extraction du commit (`git archive`), venv propre à la release (`uv sync --locked --no-dev`).
3. **Préparation**, sur la nouvelle release : `check --deploy`, un dump de la base si une migration attend (voir plus bas), `migrate`, `createcachetable` (la table où le throttling compte les requêtes, partagée par les workers), `collectstatic`.
4. **Bascule atomique** du lien `current`, puis redémarrage du service.
5. **Contrôle de santé** : `/api/health` doit répondre avec la base joignable **et le SHA attendu**.
6. **Retour arrière** : en cas d'échec, retour automatique à la release précédente, dont la santé est vérifiée à son tour. Le statut renvoyé dit si l'API est revenue. Les 3 dernières releases sont conservées.

Les migrations passent avant la bascule. Elles doivent donc rester compatibles avec la release précédente : voir la règle « Migrations » du [CLAUDE.md](../CLAUDE.md).

Le détail de chaque déploiement va dans le journal du serveur (`journalctl -t cdf3-release-back`). L'appelant ne reçoit qu'une ligne de statut, car les journaux d'une CI publique sont lisibles par tous.

## Dump avant migration

Avant de migrer, le script de release fait un dump de la base, s'il reste une migration à appliquer (`migrate --check`). Une migration ratée sur des données réelles se défait ainsi sans restaurer tout le serveur.
- Le dump va dans `/var/www/cdf3/<instance>/backups/before-<sha>.dump` (format personnalisé de `pg_dump`). Seul l'utilisateur de l'application le lit.
- Les 5 derniers sont gardés.

**Restaurer** l'état d'avant une release :
1. arrêter l'API : `systemctl stop cdf3-api@<instance>` ;
2. remettre la base : `sudo -u cdf3 pg_restore --clean --if-exists --single-transaction --dbname=<base> /var/www/cdf3/<instance>/backups/before-<sha>.dump` ;
3. repointer `current` sur la release précédente, celle qui va avec ce schéma (voir « Une release ») ;
4. redémarrer l'API, puis vérifier `/api/health`.

Ce qui a été écrit depuis le dump est perdu.

## Purge nocturne

Trois sortes de lignes restent en base après avoir servi. Aucune ne s'efface d'elle-même :
- **les refresh tokens**, émis et révoqués, jusqu'à leur expiration (7 jours). La commande `flushexpiredtokens` de ninja-jwt supprime ceux qui ont expiré ;
- **les sessions de l'admin Django**, après leur expiration (2 semaines). La commande `clearsessions` de Django les supprime ;
- **les compteurs du throttling**, chacun nommé d'après l'adresse IP qu'il compte. Le cache en base n'efface une ligne expirée que lorsqu'elle est relue. La commande `clear_cache` (`core/management/commands/`) vide le cache, qui ne contient qu'eux.

[`cdf3-flushtokens@.timer`](systemd/cdf3-flushtokens@.timer) lance les trois chaque nuit, dans cet ordre, par [`cdf3-flushtokens@.service`](systemd/cdf3-flushtokens@.service), sous l'utilisateur de l'application. Une purge qui échoue arrête les suivantes et fait échouer l'unité.

Le timer n'est installé, ou réinstallé après une modification de l'unité, qu'une fois en place une release qui contient les commandes :

```bash
install -m 0644 /var/www/cdf3/<instance>/back/current/deploy/systemd/cdf3-flushtokens@.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl start cdf3-flushtokens@<instance>.service      # un premier passage, à vérifier dans le journal
systemctl enable --now cdf3-flushtokens@<instance>.timer
```

## Déploiement continu

Un push sur `main` dont les contrôles passent se déploie seul, par le job `deploy` de [`ci.yml`](../.github/workflows/ci.yml).

- **Environnement GitHub `preprod`**, réservé à la branche `main`.
  - Secrets : `DEPLOY_SSH_KEY` (clé privée de la CI), `DEPLOY_KNOWN_HOSTS` (clé d'hôte du serveur, épinglée : jamais de confiance au premier contact) et `DEPLOY_HOST`.
  - Variable : `DEPLOY_USER`.
- **Côté serveur**, la clé publique de la CI figure dans le `authorized_keys` de l'utilisateur de l'application, restreinte au script de release :

  ```
  restrict,command="/usr/local/bin/cdf3-release-back <instance>" ssh-ed25519 AAAA… ci cdf2-back <instance>
  ```

  - `restrict` interdit le terminal, les redirections et tout autre accès.
  - Le SHA envoyé par la CI arrive dans `SSH_ORIGINAL_COMMAND` : c'est le seul paramètre que le script accepte, et il refuse tout ce qui n'est pas un commit de `main`.
- **Un déploiement à la fois, jamais interrompu.** Côté CI, une `concurrency` sans annulation. Côté serveur, le `flock` commun aux releases de l'API et du front.
- **Production** : le job `deploy-production` suit le déploiement réussi en préproduction, avec le même commit.
  - Son environnement GitHub, `production`, est réservé à `main` et attend l'approbation de son relecteur : rien n'y part sans elle. Un nouveau commit remplace celui qui attendait.
  - Il a ses propres secrets, de même nom, et sa propre clé, restreinte à `cdf3-release-back prod`.
- **Changer la clé de la CI** :
  1. générer une nouvelle paire ;
  2. remplacer la ligne dans `authorized_keys` ;
  3. poser la clé privée avec `gh secret set DEPLOY_SSH_KEY --env <environnement> < <fichier>` ;
  4. effacer la copie locale.

## Fichiers

| Fichier | Installé en | Rôle |
|---|---|---|
| `release-back.sh` | `/usr/local/bin/cdf3-release-back` | Release de l'API |
| `systemd/cdf3-api@.service` | `/etc/systemd/system/` | gunicorn, une instance par environnement (`cdf3-api@preprod`). Durci : système en lecture seule, mémoire et CPU plafonnés |
| `systemd/cdf3-flushtokens@.service`, `.timer` | `/etc/systemd/system/` | Purge nocturne des jetons, des sessions de l'admin et du cache, durcie comme l'API |
| `sudoers/cdf3` | `/etc/sudoers.d/cdf3` (0440, vérifié par `visudo -cf`) | L'utilisateur de l'application ne peut que redémarrer ses propres services |
| `nginx/cdf3.conf.template` | `/etc/nginx/sites-available/cdf3-<instance>` | Une seule origine : `/api/` et l'admin vers Django, le reste vers Nuxt. Les fichiers privés passent par l'emplacement interne `/_private/`, que Django désigne par `X-Accel-Redirect` une fois l'accès contrôlé. Les `{{…}}` sont remplacés à l'installation, puis certbot ajoute le TLS. En production, le rendu retire les lignes marquées `preprod only` (le `noindex`) |
| `nginx/cdf3-www.conf.template` | à la suite du précédent, en production | Le nom `www` du domaine redirige vers le domaine (301) |

**Rendre le vhost** d'une instance (ici la production ; la préproduction n'a ni la suppression des lignes `preprod only`, ni le modèle `www`) :

```bash
sed -e 's/{{INSTANCE}}/prod/g' -e 's/{{DOMAIN}}/<domaine>/g' \
    -e 's/{{API_PORT}}/8200/g' -e 's/{{WEB_PORT}}/3200/g' -e 's|{{ADMIN_PATH}}|<chemin de l’admin>|g' \
    -e '/# preprod only$/d' \
    nginx/cdf3.conf.template nginx/cdf3-www.conf.template > /etc/nginx/sites-available/cdf3-prod
```

Le serveur n'exécute jamais ces fichiers depuis le dépôt : il exécute les copies que root a installées. Modifier un script ou une unité ne prend effet qu'après sa réinstallation (suivie de `systemctl daemon-reload` pour une unité). Une étape ajoutée au script de release doit donc être installée **avant** de pousser le code qui en dépend.

Les valeurs propres au serveur restent hors du dépôt : domaine, chemin de l'admin, secrets, adresse et accès SSH.
