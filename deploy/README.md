# Déploiement

L'application tourne sur un VPS Ubuntu 24.04, derrière nginx, une instance par environnement : `preprod`, puis `prod`. Ce dossier contient les modèles installés sur le serveur. Le front a les siens dans [cdf2-front/deploy](https://github.com/gabigab117/cdf2-front/tree/main/deploy).

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
└── shared/
    ├── back.env, front.env  configuration et secrets (0600)
    ├── static/              fichiers statiques collectés, servis par nginx
    └── private/             fichiers privés, servis par nginx après contrôle de Django
```

- **Utilisateur dédié** : tout tourne sous un utilisateur système (`cdf3`), sans mot de passe, qui n'a accès à aucune autre application du serveur.
- **Base de données** : PostgreSQL 17, en authentification « peer » par socket local. Aucun mot de passe de base n'existe.

## Une release

[`release-back.sh`](release-back.sh) est installé en `/usr/local/bin/cdf3-release-back`, propriété de root.
- **Appel par la CI** : la CI le déclenche par une clé SSH restreinte à cette seule commande (`restrict,command="cdf3-release-back <instance>"`). Le seul paramètre transmis est le SHA du commit testé.
- **Appel à la main** : `sudo -u cdf3 cdf3-release-back <instance> <sha>`.

Étapes :
1. **Vérification du commit** : il doit appartenir à `main`. Une seule release à la fois (`flock`).
2. **Création de la release** : extraction du commit (`git archive`), venv propre à la release (`uv sync --locked --no-dev`).
3. **Préparation** : `check --deploy`, `migrate`, `collectstatic`, sur la nouvelle release.
4. **Bascule atomique** du lien `current`, puis redémarrage du service.
5. **Contrôle de santé** : `/api/health` doit répondre avec la base joignable **et le SHA attendu**.
6. **Retour arrière** : en cas d'échec, retour automatique à la release précédente, dont la santé est vérifiée à son tour. Le statut renvoyé dit si l'API est revenue. Les 3 dernières releases sont conservées.

Les migrations passent avant la bascule. Elles doivent donc rester compatibles avec la release précédente : voir la règle « Migrations » du [CLAUDE.md](../CLAUDE.md).

Le détail de chaque déploiement va dans le journal du serveur (`journalctl -t cdf3-release-back`). L'appelant ne reçoit qu'une ligne de statut, car les journaux d'une CI publique sont lisibles par tous.

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
- **Changer la clé de la CI** :
  1. générer une nouvelle paire ;
  2. remplacer la ligne dans `authorized_keys` ;
  3. poser la clé privée avec `gh secret set DEPLOY_SSH_KEY --env preprod < <fichier>` ;
  4. effacer la copie locale.

## Fichiers

| Fichier | Installé en | Rôle |
|---|---|---|
| `release-back.sh` | `/usr/local/bin/cdf3-release-back` | Release de l'API |
| `systemd/cdf3-api@.service` | `/etc/systemd/system/` | gunicorn, une instance par environnement (`cdf3-api@preprod`). Durci : système en lecture seule, mémoire et CPU plafonnés |
| `sudoers/cdf3` | `/etc/sudoers.d/cdf3` (0440, vérifié par `visudo -cf`) | L'utilisateur de l'application ne peut que redémarrer ses propres services |
| `nginx/cdf3.conf.template` | `/etc/nginx/sites-available/cdf3-<instance>` | Une seule origine : `/api/` et l'admin vers Django, le reste vers Nuxt. Les `{{…}}` sont remplacés à l'installation, puis certbot ajoute le TLS |

Les valeurs propres au serveur restent hors du dépôt : domaine, chemin de l'admin, secrets, adresse et accès SSH.
