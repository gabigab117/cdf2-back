# CLAUDE.md — Backend Comité des fêtes v2 (Django 6.1 + Django Ninja 1.7)

Règles de développement de ce dépôt, pour les humains comme pour les agents. Elles couvrent tout ce qui touche au code du back. Le périmètre fonctionnel, la roadmap et le workflow multi-dépôts vivent dans le dépôt de documentation du projet (privé). Le front Nuxt est dans le dépôt `cdf2-front`.

## Conventions

- **Tout le code est en anglais** : apps, modèles, champs, services, schémas, chemins d'API, commentaires, docstrings (y compris les docstrings Gherkin des tests), messages de commit. **Seul ce que voit l'utilisateur final est en français** : messages d'erreur renvoyés par l'API, libellés (`verbose_name`, `choices`).
- Le vocabulaire métier suit un glossaire fixe : événement → `event`, poste → `station`, affectation → `assignment`, prêt → `loan`, emprunteur → `borrower`, caution → `deposit`, ligne de trésorerie → `ledger entry`, justificatif → `receipt`… Aucun nouveau terme sans entrée au glossaire.
- Fuseau Europe/Paris, stockage en UTC. Montants en `Decimal`, jamais en `float`.
- Les textes en français prennent l'apostrophe typographique (’), comme le front. ruff l'autorise (`allowed-confusables`).
- Conventional commits, directement sur `main`, historique linéaire.
- **Context7 avant tout code de librairie** : on vérifie l'API dans la documentation à jour (Context7, puis la doc officielle, puis le code source installé dans `.venv/`), jamais de mémoire. Beaucoup de réflexes « Django » sont des réflexes DRF, faux sous Ninja.

## Outillage (obligatoire)

- **uv** pour les dépendances et les environnements, jamais pip directement. Lockfile commité.
- Toutes les commandes passent par uv : `uv run manage.py ...`, `uv run pytest`.
- **ruff** pour le lint ET le format (`ruff check` + `ruff format`). Configuration dans `pyproject.toml`.
- **Annotations de types obligatoires sur le code métier uniquement** (`services/` et tout module hors couche Django/Ninja) : signatures complètes, retours inclus, vérifiées par les règles `ANN` de ruff. La couche framework (api, schemas, models, admin, urls, migrations) en est exclue via `per-file-ignores` :

```toml
[tool.ruff.lint.per-file-ignores]
"**/api.py" = ["ANN"]
"**/schemas.py" = ["ANN"]
"**/models.py" = ["ANN"]
"**/admin.py" = ["ANN"]
"**/urls.py" = ["ANN"]
"**/migrations/*" = ["ANN"]
```

  Piège propre à Ninja : dans `api.py`, l'exclusion ne couvre que ce que Ninja ne lit pas (`request`, type de retour). **Les annotations des paramètres d'une opération sont le contrat** : Ninja s'en sert pour valider l'entrée et générer le schéma. Elles sont toujours là, ruff ou pas.
- **Commande de gestion** : `handle(self, *args: object, **options: object) -> None`. `Any` est refusé par la règle `ANN401`.
- **Pas de vérificateur de types** (ni mypy ni ty), donc pas de stubs. ruff garantit qu'une annotation existe, jamais qu'elle est juste. **Ce sont les tests qui tiennent ce rôle** (Pydantic, lui, vérifie les schémas à l'exécution). C'est une décision, pas un oubli.
- **Schéma OpenAPI natif de Ninja, source du contrat d'API.**
  - Ninja n'a pas d'équivalent à `spectacular --validate`, et un `operation_id` en double n'y produit qu'un avertissement imprimé, sans échec.
  - La validation passe donc par `openapi-spec-validator`, sur le schéma exporté (`manage.py export_openapi_schema`) dans `openapi.json`.
  - Ce fichier est commité : le front en génère ses types, et sa CI vérifie qu'ils correspondent.
- **pre-commit** : ruff (lint et format), `manage.py makemigrations --check`, détection de secrets (gitleaks), export du schéma suivi d'`openapi-spec-validator`. La CI rejoue exactement ces hooks.

## Contrat d'API

- Toute opération déclare ses entrées par des schémas et ses réponses par `response=`, **chaque code de statut renvoyé compris**. Une opération sans `response=` publie une réponse sans contenu : le front n'aurait aucun type pour elle. Un schéma faux est un bug, même si l'endpoint fonctionne.
- **Ninja ne documente aucun code d'erreur de lui-même**, pas même ceux qu'il produit :
  - une opération privée déclare 401 et 403, les refus de la classe d'auth ;
  - une opération qui lit un corps déclare 400 (corps illisible) et 422 ;
  - une opération throttlée déclare 429.

  Un test du schéma vérifie que toute opération sans `auth=None` déclare 401 et 403.
- **Schémas et énumérations portent un nom unique dans tout le projet** (`EventCategory`, pas `Category`). Le schéma OpenAPI les range par nom de classe, et un doublon en remplace un autre sans erreur, dans le schéma comme dans les types du front (constaté sur Ninja 1.7.1). Les `TextChoices` se déclarent donc au niveau du module, nommés d'après leur modèle. Un test le vérifie.
- **Le corps JSON d'une opération se déclare `payload: XxxIn`.** Ninja situe une erreur 422 du schéma sous le nom de ce paramètre (`["body", "payload", "email"]`), quand les services la situent directement sous le champ (`["body", "email"]`, voir `core/errors.py`). Le front retire ce nom pour placer les deux sous le même champ du formulaire : un autre nom ferait disparaître ses erreurs de champ.
- **Énumération facultative** : elle se publie `XxxChoice | None`. La chaîne vide d'un `CharField` n'est pas un choix de l'énumération, et ferait échouer la réponse : le champ est donc `null=True`, avec un `# noqa: DJ001` qui en dit la raison. Les schémas ne laissant entrer que les choix ou `None`, « pas de valeur » n'a qu'une forme (étiquette d'une note).
- **Erreur sur une ligne d'une liste** : un service la nomme par son chemin pointé (`programme.2.title`), que `core/errors.py` situe comme Ninja (`["body", "programme", 2, "title"]`).
- **Réponse non JSON**, comme un fichier iCalendar :
  - l'opération renvoie une `HttpResponse`, que Ninja transmet telle quelle ;
  - elle déclare `response={200: None, …}` et un `openapi_extra` qui donne le type de contenu du 200 (`CALENDAR_FILE` dans `events/api.py`) ;
  - ses erreurs restent en JSON (`ErrorOut`).
- **Ordre des routes** : Ninja les essaie dans leur ordre de déclaration, et un paramètre de chemin accepte un point. `/events/{slug}.ics` est donc déclaré avant `/events/{slug}`, qui prendrait sinon `loto-2026.ics` pour une adresse. Un test le vérifie.
- Tout changement d'API se signale explicitement : le front doit régénérer ses types. Un changement n'est terminé que quand le front compile avec les nouveaux types.

## Tests (pytest)

- **Couverture totale** : 100 % des lignes **et** des branches sur tout le code du back.
  - Elle est vérifiée en CI : `pytest --cov --cov-branch --cov-fail-under=100`.
  - Seules exclusions, déclarées dans la configuration de coverage : migrations, settings, `manage.py`, `wsgi.py` et `asgi.py`.
  - `# pragma: no cover` est interdit, sauf avec un commentaire qui explique pourquoi la ligne ne peut pas être testée.
  - Une ligne non couverte, c'est un test manquant ou du code mort.
- Chaque feature est testée. Dossier `tests/` à la racine du dépôt, structure miroir des apps.
- **Tests en fonctions, jamais en classes** (`def test_...`). Le partage de contexte passe par des fixtures, pas par `setUp`.
- **Fixtures built-in de pytest-django d'abord** : `client`, `admin_client`, `db`, `django_user_model`, `settings`, `rf`… Fixtures maison justifiées : client authentifié par rôle (`board_client` dans `tests/conftest.py`, header `Authorization: Bearer …` posé une fois), objets métier via factory_boy.
- **Requêtes par le `client` de Django, pas par le `TestClient` de Ninja** : ce dernier appelle le routeur avec une requête fabriquée (utilisateur simulé, CSRF coupé, aucun middleware) et ne prouve donc rien sur l'authentification, les cookies ni le throttling.
- `pytest-django` + **factory_boy** : pas de création manuelle de modèles reliés dans chaque test.
- **Docstrings en Gherkin, en anglais** dans chaque test (sans pytest-bdd) :

```python
def test_loan_over_availability_rejected(api_client):
    """
    Given 2 folding tables free between 17 and 18 October
    When a loan of 3 tables is recorded for that period
    Then the loan is rejected with a 422
    And the error reports how many tables are free
    """
```

- **Tester les cas d'erreur et les permissions autant que les cas nominaux** :
  - 401 et 403 ;
  - entrée invalide → **422** (code de validation de Ninja, pas 400) ;
  - throttling → 429 ;
  - objet hors de portée de l'utilisateur → **404, jamais 403** (l'existence ne doit pas fuiter).
- Les tests tournent sur **PostgreSQL** (même moteur qu'en prod) : les contraintes et le comportement transactionnel testés sont ceux de la production. Ne jamais retomber sur SQLite « pour aller plus vite ».
- **Dates attendues** : la réponse JSON écrit une date à la milliseconde (encodeur JSON de Django), et un fichier iCalendar à la seconde. Un test compare donc `DjangoJSONEncoder().default(date)`, ou la date sans ses microsecondes, et non la date brute.
- **Données de test fictives uniquement** : aucune donnée réelle (document, nom, montant) dans le dépôt, qui est public.

## Architecture

- **Vues fines, services épais** : chaque app expose un `Router` dans `api.py`, monté sur l'unique `NinjaAPI` du projet. Une opération ne contient que la couche HTTP : entrée lue par sa signature, appel du service, réponse. Toute logique métier vit dans `services/` (fonctions explicites, typées, testables unitairement sans HTTP) et n'est **jamais** dupliquée dans une opération, un schéma ou l'admin.
- **Schémas dans `schemas.py` par app** (`Schema`, `ModelSchema`, `FilterSchema`), entrée et sortie distinctes (`EventIn` / `EventOut`). **Aucune logique métier dans un schéma** : il valide la forme (types, présence des clés, énumérations), le service décide. Les contraintes de valeur (longueurs, bornes, unicité, contraintes entre champs) vivent dans le modèle et passent par `full_clean()` dans le service, avec les messages de Django, en français. En sortie, un `ModelSchema` publie les champs `blank=True` comme facultatifs et nullables : pour un contrat à champs requis, on écrit un `Schema` simple.
- **Les services ne parlent pas HTTP** : ils lèvent la `ValidationError` de Django (données invalides) ou une exception métier, jamais `HttpError`. La traduction en réponse HTTP est faite une seule fois, par les `@api.exception_handler` du `NinjaAPI`. Ninja ne connaît pas la `ValidationError` de Django, qui finirait sinon en 500. Ces réponses d'erreur figurent dans le `response=` des opérations concernées.
- **Privé par défaut**
  - L'auth est posée sur le `NinjaAPI` (`auth=`) : toute opération est authentifiée, sauf opt-out explicite `auth=None`. Jamais l'inverse, jamais de défaut implicite permissif.
  - Un seul rôle applicatif : **membre du bureau**.
    - C'est un compte actif, superuser ou membre du groupe « Bureau » (`accounts/services/roles.py`). Le groupe est créé par migration.
    - Il est porté par `BoardMemberAuth`, sous-classe de `JWTAuth` (`accounts/auth.py`).
  - Une classe d'auth lève `AuthorizationError` (403) pour un utilisateur connecté sans le droit. Renvoyer `None` produirait un 401, faux pour quelqu'un de connecté.
  - Tout échec d'authentification donne le même 401 : jeton absent, invalide ou expiré, compte inconnu ou inactif. Un compte actif hors bureau reçoit un 403. Les messages, en français, sont posés par les handlers de `config/api.py`.
  - Pas de contrôle d'autorisation en `if request.user…` dans le corps d'une opération.
- **Un objet inaccessible n'existe pas** : queryset filtré par utilisateur et par portée avant toute lecture (`get_object_or_404(<queryset filtré>, pk=...)`) → 404, jamais 403. Exemple : seul l'auteur d'une note peut la modifier. Le 404 répond « Introuvable. » (handler de `config/api.py`) : Ninja, lui, répond en anglais.
- **Endpoints publics** (ceux que lisent les pages publiques rendues côté serveur) : `auth=None`, lecture seule, sous `/api/public/`, avec des **schémas de sortie dédiés** sans aucune donnée personnelle. Jamais de schéma interne réutilisé pour un endpoint public : un champ ajouté pour l'usage interne fuiterait.
  - Le routeur du site (`public_router`, dans `events/api.py`) est monté sur `/public/`. Chaque opération y déclare `auth=None` une à une : une opération ajoutée sans y penser reste privée.
  - Un test vérifie qu'aucun schéma d'une réponse publique ne sert aussi une opération privée, les énumérations mises à part.
  - **Une URL absolue tirée de la requête** (`build_absolute_uri`) ne vaut que pour ce que le navigateur ou l'agenda du visiteur appelle à travers nginx, comme les fichiers iCalendar. Le rendu serveur de Nuxt appelle l'API avec `Host: 127.0.0.1` : une réponse JSON qu'il lit donne des chemins relatifs.
- **Requêtes optimisées par défaut** : `select_related` / `prefetch_related` sur toute liste. Pas de N+1.
  - Un test le prouve sur toute liste qui lit des objets liés, par la fixture native `django_assert_max_num_queries` de pytest-django.
  - **Une requête qui regroupe ses lignes ignore `Meta.ordering`** (`annotate(Count(...))`, depuis Django 3.1) : elle redonne son ordre par `order_by()`, sans quoi les lignes sortent dans l'ordre de la base.
  - **Un booléen annoté qui compare un champ nullable** (« la note est-elle de ce membre ? ») s'écrit `Case(When(author=member, then=Value(True)), default=Value(False))`. Une simple égalité (`ExpressionWrapper(Q(...))`) vaut NULL, et non faux, quand le champ est nul (auteur supprimé) : la réponse échouerait.
  - Une condition qui traverse une relation multiple, comme les groupes d'un compte (`BOARD_MEMBERS`), renvoie une ligne par objet lié : `.distinct()`, et un test qui construit le doublon (un superuser membre de deux groupes).
- **Opérations synchrones** (WSGI, gunicorn) : Ninja accepte les vues `async`, mais l'ORM et les services sont synchrones. Pas d'`async def` sans arbitrage. Un traitement long ne bloque jamais un worker : il passera par le framework de tâches de Django, à arbitrer quand il arrivera.
- **Fichiers : tous privés.**
  - Ils sont stockés hors racine web, sous un nom UUID ; le nom d'origine est en base.
  - Ils sont servis par un endpoint qui contrôle l'accès : authentification, ou visibilité publique pour une photo publiée. On utilise `FileResponse` en dev et **nginx `X-Accel-Redirect`** en prod.
  - Le type est vérifié **sur le contenu** à l'envoi, et la réponse porte le type enregistré, `X-Content-Type-Options: nosniff` et un `Content-Disposition` avec `filename*`.
  - Aucun dossier n'est servi directement par nginx.
- **Fonctionnalités natives d'abord**, à vérifier dans Context7 **avant** d'écrire, pas après. Ninja n'a pas les réflexes de DRF ; voici leurs équivalents, à connaître avant d'écrire un validateur ou une boucle de requête :
  - **pagination** :
    - `PageNumberPagination` en réglage global (`NINJA_PAGINATION_CLASS`, `NINJA_PAGINATION_PER_PAGE`), posée par le décorateur `@paginate` sur chaque opération qui renvoie une **collection de ressources** ;
    - pas de `RouterPaginated` : il ignore une opération dont le `response=` est un dictionnaire de statuts, ce qui est le cas de toute opération privée (401, 403). La liste part alors entière, sans erreur (constaté sur Ninja 1.7.1). Un test du schéma vérifie qu'aucune réponse 2xx n'est un tableau nu ;
    - un **agrégat borné** renvoie un objet complet, non paginé, qui enveloppe sa liste : disponibilités, planning, résultats par événement, liste de courses, éléments « à traiter », tableau de bord ;
    - jamais de collection de ressources non paginée ;
  - **throttling** :
    - `ninja.throttling` (`AnonRateThrottle`, `AuthRateThrottle`, `UserRateThrottle`) sur l'API, un routeur ou une opération ;
    - les throttles anonymes comptent par IP : derrière nginx, `NINJA_NUM_PROXIES` doit être réglé, sinon tous les visiteurs partagent un seul compteur ;
    - pas d'`AnonRateThrottle` sur les endpoints publics : le rendu serveur les appelle tous depuis l'IP du serveur Nuxt, ils seraient étranglés pour tout le monde à la fois ;
    - une sous-classe par usage, avec son propre `scope`. Sinon deux `AnonRateThrottle` partagent le même compteur par IP. Les taux sont dans `NINJA_DEFAULT_THROTTLE_RATES`, lus à l'import ;
    - les compteurs vivent dans le cache par défaut, un `DatabaseCache` partagé par les workers gunicorn (`createcachetable` au déploiement). Un cache en mémoire compterait par worker ;
    - chaque compteur est nommé d'après l'adresse IP qu'il compte, et le cache en base ne supprime une ligne expirée que lorsqu'elle est relue (ou au-delà de 300 lignes). Le cache est donc vidé chaque nuit (`clear_cache`), comme les sessions expirées de l'admin (`clearsessions`) : aucune adresse ne survit à la nuit ;
    - workers synchrones seulement, sans `--threads` : les throttles gardent un état par requête sur des instances partagées ;
  - **filtres et recherche** : `FilterSchema` + `Query[...]`, avec `FilterLookup` et une liste de lookups pour une recherche multi-champs ;
  - **tri** : pas de natif dans Ninja. On utilise un paramètre `Literal[...]` des tris autorisés (énuméré dans le schéma, donc typé côté front), appliqué par `order_by`. Jamais une chaîne libre passée à `order_by` ;
  - **unicité** : contrainte en base (`UniqueConstraint` avec `violation_error_message` en français), vérifiée par `full_clean()` dans le service, contraintes à expression comme `Lower(...)` comprises. La `ValidationError` qui en résulte devient un 422 par le handler. Jamais de `filter(...).exists()` à la main.
    - Une contrainte à un seul champ porte aussi `violation_error_code="unique"` : Django ne rattache son erreur au champ que pour ce code. Sinon, elle tombe sur le formulaire entier ;
  - **suppression des espaces de bord** : DRF le faisait par défaut, Pydantic non.
    - `InputSchema` (`core/schemas.py`) pose `str_strip_whitespace=True`, et tous les schémas d'entrée en héritent.
    - Un champ gardé tel quel, comme un mot de passe, s'en exclut par `StringConstraints(strip_whitespace=False)`.
    - Pas de `.strip()` champ par champ ;
  - **validation croisée entre champs** : une contrainte du modèle (`CheckConstraint`) quand la règle vaut aussi en base, vérifiée par `full_clean()` ; sinon un `@model_validator` du schéma. Jamais dans l'opération. L'erreur d'une contrainte n'est rattachée à aucun champ : elle va au formulaire ;
  - **messages d'erreur en français** : les nôtres, ceux de Django (`LANGUAGE_CODE = "fr-fr"`, contraintes comprises), et ceux de Pydantic, qui n'existent qu'en anglais.
    - `core/errors.py` remplace les messages de Pydantic d'après leur type, par ceux que Django traduit déjà : les messages de ses champs de formulaire, les seuls sans `%(value)s` à remplir. Tout autre type reçoit « Saisissez une valeur valide. ».
    - Un schéma qui introduit un type de champ nouveau (décimal, date, UUID…) ou une contrainte de schéma ajoute ses types d'erreur à la table, avec un test.
    - Pas de `LocaleMiddleware` : le français de `LANGUAGE_CODE` vaut pour toutes les réponses ;
  - **back-office** : Django admin, pour la gestion des comptes.
- **Auth : JWT via `django-ninja-jwt`** (décision projet : l'API reste ouverte à une future app mobile ou à un tiers). Trois règles non négociables, chacune répond à un risque précis :
  - **access token court (15 min), transmis en header `Authorization`** et gardé en mémoire côté front. Jamais de token en `localStorage`.
  - **refresh token (7 j) posé en cookie httpOnly**. Il survit au rechargement de page sans être lisible par un script. Attributs :
    - `SameSite=Strict`, `Secure` en prod ;
    - `Path` limité aux endpoints d'authentification, `/api/auth/`. Pas au seul refresh : logout doit recevoir le cookie pour blacklister, le front ne pouvant pas lire un cookie httpOnly.
  - **app `ninja_jwt.token_blacklist` activée** :
    - le refresh est invalidé à la déconnexion ;
    - chaque renouvellement fait tourner le refresh et blackliste l'ancien (`accounts/services/sessions.py`), pour qu'un refresh volé ne serve qu'une fois. Un renouvellement concurrent du même jeton est refusé. Les réglages `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION` ne pilotent que les contrôleurs de ninja-jwt : ils ne sont pas posés ;
    - la désactivation d'un compte est immédiate : `JWTAuth` relit l'utilisateur à chaque requête et refuse un compte inactif.
  - **Endpoints écrits par nous**, sur les classes de tokens de ninja-jwt (`RefreshToken.for_user`, `.blacklist()`) :
    - login : pose le cookie de refresh et renvoie l'access ;
    - refresh : lit le cookie ;
    - logout : blackliste et supprime le cookie ;
    - « qui suis-je ».

    Raison du custom : les contrôleurs et routeurs fournis renvoient le refresh dans le corps JSON, ce que la règle du cookie httpOnly interdit. Leur refresh ne vérifie pas non plus que le compte est actif.

    Un refresh refusé ne touche pas au cookie : quand deux onglets renouvellent en même temps, la réponse perdante effacerait le cookie neuf.
  - Throttling strict sur login et refresh. Purge nocturne planifiée sur le serveur, par un timer systemd (`deploy/`) : tokens expirés (`flushexpiredtokens`), sessions expirées de l'admin (`clearsessions`), cache (`clear_cache`).
  - **Limites acceptées** :
    - pas de détection de la réutilisation d'un refresh volé ;
    - changer de mot de passe ne révoque pas les sessions ouvertes ;
    - la déconnexion ne révoque que le navigateur courant, et l'access token reste valide jusqu'à 15 min ;
    - les compteurs de throttling sont approximatifs sous concurrence ;
    - changer `SECRET_KEY` déconnecte tout le monde ;
    - les refresh tokens sont en clair dans la table `OutstandingToken`. C'est pourquoi les admins de jetons de ninja-jwt sont retirés.
  - **`django-ninja-extra` n'est qu'une dépendance transitive de ninja-jwt**, pas un outil du projet : ni `NinjaExtraAPI`, ni contrôleurs en classes, ni permissions ninja-extra. Un seul paradigme, les routeurs fonctionnels de Ninja. `JWTAuth` fonctionne sur un `NinjaAPI` ordinaire (ses exceptions héritent de `HttpError` → 401). `BoardMemberAuth` les ramène à un 401 uniforme, sans les messages détaillés de ninja-jwt.
- **PostgreSQL en dev comme en prod** (paramètres locaux dans `.env.example`, base dédiée au projet). Aucune divergence de moteur : les types et contraintes Postgres sont autorisés, et le comportement transactionnel testé en dev est celui de la production.

## Migrations

- **Jamais de migration écrite à la main.** Toujours `uv run manage.py makemigrations` (avec `--name` significatif). Seule exception : les migrations de données (`RunPython`), créées via `makemigrations --empty`, complétées — et testées.
- Ne **jamais** modifier une migration déjà appliquée.
- `makemigrations --check` dans le pre-commit.
- **Migrations rétrocompatibles.** Le déploiement migre la base avant de basculer sur le nouveau code, et peut revenir à la release précédente. Le code précédent doit donc fonctionner avec le schéma migré :
  - on ajoute d'abord, on retire dans une release ultérieure ;
  - pas de renommage ni de suppression de colonne utilisée dans la même release ;
  - une colonne NOT NULL ajoutée porte un `db_default` en plus de son `default` : la release précédente insère encore des lignes sans elle ;
  - tout `RunPython` déclare un `reverse_code`.
- **Limite d'un retour arrière** : la cascade d'une suppression est faite par Django, pas par la base. Une release qui rattache des objets à un modèle existant (notes, tâches, postes et réservations d'un événement, en phase 3) empêche la release précédente, qui ne connaît pas ces tables, de supprimer un objet qui en a : la base refuse la clé étrangère orpheline.
- **Aucun hook n'a le droit de réécrire une migration.**
  - Les migrations sont exclues de ruff (`extend-exclude`), et les deux hooks ruff tournent avec `--force-exclude`. Piège : sans lui, `extend-exclude` ne s'applique pas aux chemins que pre-commit passe en argument.
  - Les hooks de `ruff-pre-commit` le portent déjà dans leur `entry` amont : ne pas le repasser en `args`, ruff refuse le doublon.
  - Les hooks de lecture seule (détection de secrets) restent actifs sur les migrations.

## Sécurité

- Secrets uniquement en variables d'environnement (`django-environ`). `.env` dans `.gitignore`, `.env.example` commité. **Aucun secret dans le code ou les migrations.** Le dépôt est public : aucun accès au serveur non plus (adresse, clés, comptes de connexion) ni valeur de configuration sensible (chemin de l'admin, secrets). Les modèles de `deploy/` décrivent l'organisation du serveur ; ces valeurs y restent des espaces réservés `{{…}}`, remplis à l'installation.
- **Settings séparés** dev / test / prod.
  - En prod : `DEBUG=False`, `ALLOWED_HOSTS`, cookie de refresh `Secure`.
  - Derrière nginx : `SECURE_PROXY_SSL_HEADER` et `CSRF_TRUSTED_ORIGINS`. La redirection HTTPS est faite par nginx, pas par Django.
  - Le chemin de l'admin est lu dans l'environnement.
  - Schéma OpenAPI et docs interactives (`/api/docs`) servis selon un réglage dédié (`SERVE_API_SCHEMA`), coupé en prod. Pas selon `DEBUG`, que pytest-django force à `False`.
  - **Ce qui est interdit en production** (le jeu de démonstration, `DEMO_DATA_ENABLED`) ne s'autorise que par l'environnement, jamais par un fichier de settings. Sur le serveur, un `manage.py` lancé sans `DJANGO_SETTINGS_MODULE` charge les settings de dev, en lisant le même `.env`.
- **Pas de CORS** : le navigateur ne voit qu'une origine (nginx en prod, proxy de dev de Nuxt en local), et le rendu serveur appelle l'API de serveur à serveur. `django-cors-headers` n'arrive que si un client d'une autre origine entre au périmètre.
- Throttling strict sur login et refresh. Messages d'erreur non énumérants.
- **Toute entrée passe par un schéma.** Aucune confiance dans le client : règles métier et transitions de statut vérifiées côté serveur. Jamais de `ModelSchema` en `fields = "__all__"` ni en `exclude` sur une entrée : un champ ajouté au modèle deviendrait modifiable sans que personne l'ait décidé.
- **Données personnelles (RGPD)**
  - On ne stocke que ce qu'une card demande.
  - Aucune donnée personnelle dans un endpoint public.
  - Les durées de conservation sont appliquées par une purge planifiée.
  - Elles sont publiées sur la page « Données personnelles » du site, que le front rédige : une donnée personnelle ajoutée y est décrite, avec sa durée.

## Definition of Done (chaque feature)

1. **Context7 consulté** pour chaque API de librairie utilisée ou modifiée : rien d'écrit de mémoire.
2. `ruff check` (annotations `ANN` comprises) et `ruff format --check` passent.
3. Tests pytest écrits avec docstrings Gherkin, verts, **couverture à 100 % (lignes et branches)**, cas d'erreur et permissions couverts.
4. Aucun secret ni valeur en dur qui devrait être en config.
5. Migrations propres et rétrocompatibles si des modèles sont touchés (`makemigrations --check` passe).
6. Si l'API a changé :
   - chaque opération déclare ses réponses (`response=`, codes d'erreur compris) ;
   - `openapi.json` est régénéré et passe `openapi-spec-validator` ;
   - le changement est signalé explicitement, car le front doit régénérer ses types.
7. **Aucun code custom qui double une fonctionnalité native.** Tout validateur, helper ou boucle de requête écrit à la main suppose qu'on a cherché l'équivalent framework dans Context7 **avant** de l'écrire. S'il est conservé, un commentaire dit pourquoi le natif ne convenait pas.
8. Une donnée personnelle ajoutée, ou une durée de conservation changée, est décrite sur la page « Données personnelles » du front.
9. La CI est verte, et le déploiement en préproduction aussi.
10. La card correspondante de la roadmap est annotée **✅ Terminé**.
