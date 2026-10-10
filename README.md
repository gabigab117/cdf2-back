# Comité des fêtes d'Ons-en-Bray — API

[![CI](https://github.com/gabigab117/cdf2-back/actions/workflows/ci.yml/badge.svg)](https://github.com/gabigab117/cdf2-back/actions/workflows/ci.yml)

API de la v2 de l'application du Comité des fêtes d'Ons-en-Bray (Oise), une association qui organise les animations de la commune. L'application regroupe deux parties :
- un **site public** : agenda des manifestations, fiches événements, souvenirs ;
- un **espace réservé au bureau** de l'association : organisation des événements et des bénévoles, documents, trésorerie, stock de la buvette, prêts de matériel aux associations du village.

Ce dépôt contient l'API. Le front (Nuxt 4) est dans [cdf2-front](https://github.com/gabigab117/cdf2-front).

> **État** : projet en cours de construction (octobre 2026). Le socle technique est en place ; les fonctionnalités arrivent par étapes.

## Stack

- **Python 3.13**, **Django 6.1**, **Django Ninja 1.7** (Pydantic 2)
- **PostgreSQL 17**, en développement, en CI et en production
- Authentification **JWT** (django-ninja-jwt) : access token en mémoire côté front, refresh token en cookie httpOnly
- Outillage : **uv**, **ruff** (lint et format), **pytest** (pytest-django, factory_boy, pytest-cov), **pre-commit**

## Principes

- **Le contrat d'API, c'est le schéma OpenAPI** généré par Django Ninja à partir des schémas Pydantic et des signatures des opérations. Il est exporté dans [`openapi.json`](openapi.json) à chaque commit, validé par `openapi-spec-validator`, et le front en génère ses types TypeScript. Chaque opération déclare toutes ses réponses, codes d'erreur compris.
- **Vues fines, services épais** : une opération ne fait que la couche HTTP. La logique métier vit dans les `services/` de chaque app : des fonctions typées, testées sans HTTP, qui lèvent des erreurs métier, jamais des erreurs HTTP.
- **Privé par défaut** : l'authentification est posée sur l'API entière, et un endpoint public se déclare explicitement (`auth=None`), avec des schémas dédiés sans donnée personnelle. Un objet hors de portée renvoie 404, jamais 403.
- **Fonctionnalités natives d'abord** : contraintes en base plutôt que validations à la main, pagination, filtres et throttling de Ninja.
- **Couverture de tests totale** : 100 % des lignes et des branches, vérifiée en CI.

## Authentification

- **Access token** de 15 minutes : `POST /api/auth/login` le renvoie, et le front le garde en mémoire pour l'envoyer dans l'en-tête `Authorization: Bearer …`.
- **Refresh token** de 7 jours, dans un cookie httpOnly, `SameSite=Strict`, limité à `/api/auth/` :
  - `POST /api/auth/refresh` l'échange contre un nouvel access token et un nouveau refresh token, l'ancien étant blacklisté (rotation) ;
  - `POST /api/auth/logout` le révoque et supprime le cookie.
- **Un seul rôle, membre du bureau** : un compte actif, superuser ou membre du groupe « Bureau ». Le groupe est créé par migration, et les comptes se gèrent dans l'admin Django.
  - Toute opération est réservée à ce rôle, sauf déclaration explicite `auth=None`.
  - Un appel sans identité valable reçoit un 401, un compte hors bureau un 403.
  - Désactiver un compte ou le retirer du groupe prend effet à la requête suivante.
- **Throttling** par IP de la connexion et du renouvellement. Les compteurs sont dans un cache en base, partagé par les workers.
- **Purge** chaque nuit, par un timer systemd ([`deploy/`](deploy/README.md)) : les jetons expirés (`flushexpiredtokens`), les sessions expirées de l'admin (`clearsessions`), puis le cache, dont chaque compteur nomme une adresse IP (`clear_cache`).

## Site public

Les pages publiques, rendues côté serveur par le front, lisent des endpoints ouverts et en lecture seule, sous `/api/public/`. Leurs schémas sont propres au site, et aucun ne nomme une personne.

- `GET /api/public/events` : l'agenda, soit les événements publiés à venir, le plus proche d'abord, par page et filtrables par catégorie.
- `GET /api/public/agenda` : les catégories présentes dans l'agenda, et la date de sa dernière modification.
- `GET /api/public/events/{slug}` : la fiche d'un événement publié (programme, « Bon à savoir », lieu, tarifs), suivie des deux événements qui viennent après lui dans l'agenda.
- `GET /api/public/agenda.ics` : l'agenda au format iCalendar, auquel s'abonne l'agenda du visiteur. Il garde les événements passés.
- `GET /api/public/events/{slug}.ics` : un événement, à ajouter à son agenda.

Les fichiers iCalendar sont écrits en heure de Paris (`TZID=Europe/Paris`, avec la définition du fuseau), avec la bibliothèque `icalendar`.

## Organisation

```
config/          projet Django : settings (base, dev, test, prod), urls, NinjaAPI unique (api.py)
accounts/        comptes et authentification JWT des membres du bureau (connexion par adresse e-mail), liste des membres (/api/board/members)
core/            socle commun : santé du service, schémas partagés, traduction des erreurs en réponses 422
dashboard/       tableaux de bord : celui du bureau (GET /api/board/overview, prochains événements avec leurs tâches et leurs notes, dernières notes) et celui d'un événement (GET /api/board/events/{id}/dashboard, compteurs de ses onglets, bloc « Tâches », personnes affectées aux postes, places réservées), agrégats bornés que chaque domaine enrichit
documents/       documents du comité : dépôt (PDF, images converties en WebP), classement, validation, fichiers privés servis par X-Accel-Redirect, e-mail à chaque dépôt et import de la v1 (/api/board/documents)
equipment/       matériel et prêts : prêts numérotés, écrits sous verrou sans dépasser le libre, sortis, rendus, rouverts ou annulés, listés par état (/api/board/loans), inventaire du jour, occupation d'un matériel, refus d'un changement qui laisse un prêt à court (/api/board/equipment), disponibilités au pic journalier, sur les dates effectives des prêts (/api/board/equipment/availability), reprise de l'inventaire de la v1 (import_v1_equipment)
events/          événements du comité : programme, « Bon à savoir », API du bureau (/api/board/events), API du site public (/api/public/), fichiers iCalendar et jeu de démonstration (seed_demo)
notes/           notes du bureau, sur un événement ou générales, avec un niveau de réponses ; seul l'auteur les modifie (/api/board/notes)
reservations/    réservations d'un événement par le bureau : types de place, capacité, saisie sous verrou, chiffres et export Excel (/api/board/events/{id}/reservations)
stations/        postes d'un événement et bénévoles qui y sont affectés ; « complet » seulement si chaque poste l'est (/api/board/events/{id}/stations)
tasks/           tâches du bureau : assignation, échéance, faite ou non, dans l'ordre du bureau (/api/board/tasks)
tests/           tests pytest, en miroir des apps
openapi.json     schéma OpenAPI exporté (contrat avec le front)
```

## Démarrage local

Prérequis : [uv](https://docs.astral.sh/uv/) et un serveur PostgreSQL 17.

```bash
cp .env.example .env              # puis renseigner SECRET_KEY et la connexion PostgreSQL
uv sync                           # environnement et dépendances (versions figées par uv.lock)
uv run pre-commit install         # hooks de qualité à chaque commit
uv run python manage.py migrate
uv run python manage.py createcachetable  # table du cache, où le throttling compte les requêtes
uv run python manage.py createsuperuser
uv run python manage.py seed_demo         # facultatif : les événements fictifs de la maquette
uv run python manage.py runserver
```

- Santé du service : `GET /api/health`.
- Documentation interactive de l'API : `/api/docs` (servie en développement seulement).

## Données de démonstration

`manage.py seed_demo` écrit les événements fictifs de la maquette, publiés : cinq à venir et quatre passés, avec leur programme et leur « Bon à savoir ». Il sert au développement, à la préproduction et aux parcours de bout en bout du front.

- **Il n'est permis que si l'environnement pose `DEMO_DATA_ENABLED=true`** (`.env.example` le fait pour le développement local). Aucun fichier de settings ne l'active : il est refusé en production.
- **Chaque événement revient chaque année au même jour.** Ceux à venir prennent leur prochaine date, aujourd'hui compris, et les passés leur dernière date avant aujourd'hui. La démonstration reste ainsi vivante d'une année sur l'autre.
- **Il peut être relancé** : un événement déjà écrit est retrouvé par son adresse et réécrit. Relancé après la date d'un événement, il en écrit l'édition suivante, et la précédente reste parmi les événements passés.
- Il ne crée aucun compte et ne nomme aucun responsable.

## Qualité

| Commande | Rôle |
|---|---|
| `uv run pytest --cov` | Tests sur PostgreSQL, couverture de 100 % exigée (lignes et branches) |
| `uv run ruff check .` / `uv run ruff format .` | Lint et formatage |
| `uv run pre-commit run --all-files` | Tous les contrôles du commit : ruff, détection de secrets (gitleaks), migrations à jour, export et validation du schéma OpenAPI |

Les tests sont écrits en fonctions, avec des docstrings Gherkin. Ils passent par le client HTTP de Django, pour exercer l'authentification et les middlewares réels.

## Licence

[MIT](LICENSE)
