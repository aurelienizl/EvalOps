# EvalOps — Plateforme d'Évaluation DevOps & Laboratoires Linux

Plateforme web sécurisée d'apprentissage et d'évaluation automatisée pour cursus d'ingénierie et DevOps. Chaque étudiant dispose d'un espace de travail Linux dédié accessible par SSH, d'une persistance de ses données au sein d'un volume Docker dédié, et soumet ses travaux à des évaluateurs hermétiques exécutés hors réseau. Les enseignants et administrateurs disposent d'une console de contrôle complète pour superviser les charges, auditer les notes et piloter les verrous d'environnement.

---

## 1. Architecture du Système

Les responsabilités, interfaces, règles de démarrage et limites de déploiement sont décrites dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

L'infrastructure s'articule autour de trois services permanents orchestrés via Docker Compose :

```
                    ┌─────────────────────────┐
                    │      Client / WAF       │
                    └────────────┬────────────┘
                                 │ HTTP :8080
                    ┌────────────▼────────────┐
                    │        frontend         │  (Nginx, UI AMOLED)
                    └────────────┬────────────┘
                                 │ Réseau frontend_backend
                    ┌────────────▼────────────┐
                    │         backend         │  (FastAPI modulaire, SQLite WAL, RBAC, Admin API)
                    └────────────┬────────────┘
                                 │ Réseau backend_manager
                    ┌────────────▼────────────┐
                    │    container_manager    │  (FastAPI modulaire, Docker SDK, /var/run/docker.sock)
                    └────────────┬────────────┘
                                 │ Gestion du cycle de vie
          ┌──────────────────────┴──────────────────────┐
          │                                             │
┌─────────▼──────────────┐                   ┌──────────▼──────────────┐
│  Conteneur Étudiant    │                   │   Conteneur Évaluateur  │
│  (dev.Dockerfile)      │                   │   (eval.Dockerfile)     │
│  SSH 22000-22999 :rw   │                   │   network_mode: none    │
└─────────┬──────────────┘                   └──────────┬──────────────┘
          │                                             │
          └───────────────┬─────────────────────────────┘
                          │
             ┌────────────▼────────────┐
             │    Volume étudiant     │  (Volume Docker pérenne /home/student)
             └─────────────────────────┘
```

### Microservices

| Service | Technologies | Rôle |
|---|---|---|
| **`frontend`** | Nginx Alpine, HTML5, CSS3 AMOLED, ES Modules natifs | Interface utilisateur industrielle haute densité, affichage temps réel du statut et console d'administration complète. |
| **`backend`** | Python 3.11+, FastAPI, SQLite (mode WAL), Argon2id | Architecture modulaire par routeurs (`api/v1/`), authentification par cookies sécurisés, contrôle d'accès par rôles (`student` / `admin`), API d'administration générique, catalogue des cours et client dédié au Container Manager. |
| **`container_manager`** | Python 3.11+, FastAPI, Docker SDK Python | Architecture modulaire par domaine (`api/v1/`), orchestration des conteneurs étudiants, allocation dynamique des ports SSH, injection des clés SSH dans les volumes et exécution hermétique des évaluateurs. |

---

## 2. Sécurité & Isolation

- **Herméticité réseau de l'évaluation** : Les conteneurs d'évaluation sont exécutés avec `network_mode: none`. Ils ne disposent d'aucun accès réseau (ni Internet, ni réseau Docker interne).
- **Montage en lecture seule** : Lors d'une évaluation, le volume de l'étudiant est monté en lecture seule (`/home/student:ro`). L'évaluateur ne peut en aucun cas altérer ou supprimer le travail de l'étudiant.
- **Récupération directe des résultats** : L'évaluateur génère son rapport dans un volume d'échange éphémère (`/result:rw`) inspecté directement par le manager sans extraction d'archive intermédiaire.
- **Gestion des volumes sans conteneur temporaire** : L'injection de la clé publique SSH dans `authorized_keys` et des fichiers de profil s'effectue par accès direct au point de montage du volume (`/var/lib/docker/volumes/...`), éliminant les fuites de conteneurs orphelins.
- **Vérification stricte de la clé SSH** : Seules les clés au format `ssh-ed25519` sur une seule ligne et **sans aucun commentaire ni option** sont acceptées (rejet strict des clés RSA ou altérées).
- **Contrôle d'accès par rôles (RBAC)** : Ségrégation stricte des permissions via dépendances FastAPI (`require_admin`). Les étudiants n'ont aucun accès aux routes de supervision, de déverrouillage ou de gestion des comptes.
- **Réseaux cloisonnés** : Le frontend ne communique qu'avec le backend (`frontend_backend`). Le backend ne communique qu'avec le manager (`backend_manager`). Les conteneurs étudiants sont placés sur le bridge Docker avec leur port SSH exposé.
- **Protection WAF en amont** : Le backend s'appuie sur un WAF / Reverse-Proxy de bordure pour la limitation de débit (rate limiting) globale et se concentre sur la validation des entrées et l'intégrité des flux.

---

## 3. Interface Utilisateur (Design Industriel AMOLED)

L'application intègre une interface moderne et sobre au standard **AMOLED Dark** (`#000000` pur) :

- **Haute lisibilité & contraste** : Palette monochrome avec polices **Inter** pour les textes et **JetBrains Mono** pour les identifiants techniques, dates, scores et commandes.
- **Bannière télémétrique globale (HUD)** : Statut visuel en direct de l'environnement (`ACTIF`, `INITIALISATION`, `ÉVALUATION`, `ARRÊT`).
- **Connexion SSH en un clic** : Commande SSH pré-formatée avec bouton de copie rapide intégrant les options nécessaires pour éviter les avertissements d'empreinte d'hôte :
  ```bash
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p <PORT> student@<HOST>
  ```
- **Visualiseur de consignes Markdown** : Rendu sécurisé des énoncés avec listes ordonnées/non ordonnées, blocs de code contrastés et téléchargement des fichiers de ressources.
- **Rapport d'évaluation CI/CD** : Modale d'évaluation affichant les détails par assertion (`[PASS]` / `[FAIL]`) et les retours consoles d'erreur.
- **Console d'Administration (`#admin`)** :
  - **Tableau de bord télémétrique** : Statistiques globales en direct (nombre d'utilisateurs, évaluations soumises, taux de réussite global, opérations actives).
  - **Annuaire des utilisateurs** : Recherche plein texte par email, filtrage par rôle (`student` / `admin`), état de la clé SSH, pagination et promotion/rétrogradation de rôle en un clic.
  - **Surveillance des runtimes & verrous** : Vue des opérations actives et suppression des verrous obsolètes après vérification de leur état.
  - **Journal d'audit des évaluations** : Consultation transversale de toutes les évaluations avec filtre par étudiant, exercice et statut, incluant l'ouverture des rapports d'assertions détaillés.

---

## 4. Structure du Projet

```
EvalOps/
├── compose.yaml                # Définition des services Docker Compose
├── .env.example                # Modèle des variables d'environnement
├── requirements.txt            # Dépendances Python pour l'environnement hôte / tests
│
├── frontend/                   # Service Nginx & Assets Web
│   ├── Dockerfile
│   ├── nginx.conf              # Configuration Nginx (fichiers statiques, headers de sécurité)
│   └── public/
│       ├── index.html          # Shell SPA, modales, shell admin et templates SVG
│       ├── styles.css          # Thème CSS Industriel AMOLED & styles console admin
│       ├── app.js              # Point d'entrée et routeur SPA par hash avec guard admin
│       └── js/
│           ├── core.js         # API, session, utilitaires DOM et polling
│           ├── markdown.js     # Moteur de rendu Markdown sécurisé
│           ├── components/     # Bannière globale et verrouillage
│           └── pages/          # Vues (connexion, catalogue, module, exercice, profil, admin)
│               └── admin.js    # Contrôleur complet de la console d'administration
│
├── backend/                    # API métier, RBAC & administration (voir docs/BACKEND.md)
│   ├── Dockerfile
│   └── src/                    # Application Python modulaire
│       ├── __init__.py
│       ├── app.py              # Bootstrap FastAPI allégé (~70 lignes), lifespan & exceptions
│       ├── state.py            # État global et singletons du catalogue
│       ├── schema.sql          # Schéma SQLite relationnel avec support des rôles
│       ├── cli.py              # CLI d'administration (create-user, set-role, list-users, init-db)
│       ├── db.py               # Couche SQLite WAL, schéma initial & requêtes avec pagination
│       ├── runtime.py          # Orchestration des verrous étudiants et cycle de vie
│       ├── core/               # Sécurité, Argon2id, tokens et dépendances RBAC
│       │   ├── config.py       # Configuration centralisée
│       │   ├── security.py     # Hachage, tokens de session, validation Ed25519
│       │   └── dependencies.py # Dépendances FastAPI (auth, csrf, require_admin)
│       ├── services/           # Services applicatifs
│       │   └── container_client.py # Client HTTP typé dédié au Container Manager
│       └── api/                # Routeurs d'API modulaires (/api/v1/*)
│           └── v1/
│               ├── auth.py         # Connexion, déconnexion, session courante
│               ├── profile.py      # Profil, mot de passe, clé SSH
│               ├── courses.py      # Modules et catalogue d'exercices
│               ├── evaluations.py  # Historique et snapshots d'évaluations
│               ├── environment.py  # Contrôle des conteneurs étudiants (start, stop, grade)
│               ├── admin.py        # Interfaces de requêtage génériques & administration
│               └── system.py       # Sondes de vie et de préparation (/health, /ready)
│
├── container_manager/          # Microservice d'orchestration Docker (voir docs/CONTAINER_MANAGER.md)
│   ├── Dockerfile
│   └── src/                    # Application Python modulaire
│       ├── __init__.py
│       ├── app.py              # Bootstrap FastAPI allégé & cycle de vie
│       ├── builds.py           # Construction & vérification des images Docker
│       ├── docker_runtime.py   # Runtime Docker, quotas & pool de ports SSH
│       ├── core/               # Configuration et gestion des exceptions
│       │   ├── config.py       # Variables d'environnement (ports SSH, instance)
│       │   └── exceptions.py   # Fabrique d'erreurs HTTP normalisées
│       ├── services/           # Gestion de l'état d'exécution
│       │   └── state.py        # Singletons et pré-validation des requêtes
│       └── api/                # Routeurs d'API internes (/v1/*)
│           └── v1/
│               ├── system.py       # Santé et empreinte du catalogue (/health, /catalog)
│               ├── environments.py # Démarrage et arrêt des conteneurs dev
│               ├── evaluations.py  # Évaluation sandboxée et archives snapshot
│               └── operations.py   # Suivi d'opérations et injection de clé de volume
│
├── docs/                       # Guides et spécifications d'architecture
│   ├── BACKEND.md              # Référence d'architecture, RBAC & API du backend
│   ├── CONTAINER_MANAGER.md    # Référence d'architecture & API du container manager
│   └── COURSES_DOCUMENTATION.md # Guide de conception des cours et exercices
│
├── courses/                    # Catalogue pédagogique déclaratif
│   ├── examples/               # Trois exercices simples de programmation C
│   │   ├── course.yaml
│   │   └── exercises/
│   │       ├── hello-c/
│   │       ├── fibo-c/
│   │       └── sum-c/
│   └── shell/                  # Exercices de programmation shell
│       ├── course.yaml
│       └── exercises/
│           └── ...
│
└── tests/                      # Tests unitaires, fonctionnels et simulation de capacité
    ├── conftest.py             # Fixtures globales (détection URL container manager, chemins)
    ├── unit/                   # Tests unitaires isolés (rapides, sans conteneurs)
    │   ├── test_admin.py       # Permissions RBAC, pagination, requêtes admin & unlock
    │   ├── test_container_manager.py # Pool d'allocation de ports, BuildManager & validations
    │   ├── test_auth.py        # Hachage Argon2id & validation stricte des clés Ed25519
    │   ├── test_catalog.py     # Parsing des manifestes YAML & détection des traversées
    │   ├── test_scoring.py     # Formules de notes & persistance de complétion
    │   ├── test_locks.py       # Verrous étudiants isolés & persistance SQLite
    │   └── test_cli.py         # Administration CLI (création avec rôles, list-users, set-role)
    │
    └── functional/             # Tests fonctionnels complets (Minions & conteneurs réels)
        ├── conftest.py         # Instance propre, personas (Kevin, Bob, Stuart, Dave, Otto, Mel) & cleanups
        ├── test_environments.py # Kevin & Bob: démarrage, ports SSH, quotas Docker & arrêt
        ├── test_evaluations.py # Stuart & Dave: évaluation des cours examples & snapshots
        ├── test_errors.py      # Otto & Mel: cas d'erreurs (401, 403, 404, 422, rate-limit 429)
        ├── test_concurrency.py # Mel, Kevin & Bob: concurrence & verrous opérationnels
        ├── simulation_support.py # Déploiement Docker neuf et comptes de simulation
        ├── compose.simulation.yaml # Catalogue et projet isolés pour la simulation
        └── test_simulation.py  # Cohorte configurable, 99 étudiants par défaut
```

---

## 5. Spécification du Catalogue des Cours

Chaque module est décrit sous `./courses/<nom_du_cours>/` :

### Fichier `course.yaml`
```yaml
id: linux-basics
name: "Bases de l'administration Linux"
deadline: "2026-11-01T23:59:59Z"
```

### Fichier d'exercice `exercise.yaml`
Chaque exercice est placé dans un sous-dossier de `./courses/<cours>/exercises/<exercice>/` :
```yaml
id: sys-config
name: "Configuration serveur Nginx"
difficulty: easy     # warmup, easy, medium, hard
timeout: 30          # Durée max de l'évaluateur en secondes

resources:
  - id: sample-conf
    name: sample.conf
    path: resources/sample.conf
```

### Fichiers requis par exercice :
1. `README.md` : Consignes affichées dans l'interface utilisateur.
2. `dev.Dockerfile` : Image du conteneur interactif de l'étudiant (serveur OpenSSH, outils nécessaires).
3. `eval.Dockerfile` : Image de l'évaluateur exécuté hors réseau pour exécuter la suite de tests et produire `/result/result.json`.

---

## 6. Déploiement & Démarrage

### 6.1 Prérequis
- Système d'exploitation Linux (Ubuntu 22.04+, Debian 12+, RHEL 9+)
- Docker Engine 24.0+ et Docker Compose v2
- Port `8080` libre (ou mappé derrière votre proxy inverse de terminaison TLS)
- Plage de ports `22000-22999` ouverte sur le pare-feu hôte pour les connexions SSH

### 6.2 Configuration
Initialisez votre fichier d'environnement à partir de l'exemple :
```bash
cp .env.example .env
```

Variables principales :
- `PLATFORM_INSTANCE` : Identifiant unique de l'instance (ex: `evalops-prod`).
- `SSH_HOST` : Nom de domaine ou IP accessible par les étudiants (ex: `devops.ecole.fr` ou `localhost`).
- `SSH_BIND_ADDRESS` : Adresse d'écoute des ports SSH (`0.0.0.0`).
- `SSH_PORT_MIN` / `SSH_PORT_MAX` : Plage de ports réservés aux conteneurs de développement (`22000` - `22999`).

### 6.3 Lancement des conteneurs
```bash
docker compose up -d --build
```

Au démarrage :
1. Le service `container_manager` inspecte Docker et purge d'éventuels conteneurs résiduels d'une session précédente.
2. Le catalogue `./courses` est validé et les images Docker de développement et d'évaluation sont construites séquentiellement pendant l'initialisation. Le manager accepte les requêtes une fois les constructions terminées.
3. Une fois le manager sain, le `backend` initialise le schéma SQLite `/data/app.db` et démarre son API.
4. Le `frontend` Nginx sert l'interface sur `http://localhost:8080/`.

Vérifiez l'état de santé des services :
```bash
docker compose ps
```

---

## 7. Administration des Utilisateurs & Rôles

La gestion des comptes s'effectue soit via la **console web d'administration** (`#admin`), soit via la **CLI du backend**.

### 7.1 Création de comptes en ligne de commande
```bash
# Compte étudiant classique (rôle par défaut) :
docker compose exec backend python -m backend.src.cli create-user --email etudiant@ecole.fr

# Compte administrateur :
docker compose exec backend python -m backend.src.cli create-user --email prof@ecole.fr --role admin
```
*Le mot de passe est saisi de manière sécurisée sans écho dans le terminal, puis haché avec Argon2id.*

### 7.2 Consultation et gestion des rôles
```bash
# Lister les comptes avec filtrage optionnel :
docker compose exec backend python -m backend.src.cli list-users --role admin

# Modifier le rôle d'un compte existant :
docker compose exec backend python -m backend.src.cli set-role --email etudiant@ecole.fr --role admin
```

### 7.3 Réinitialisation de mot de passe
```bash
docker compose exec backend python -m backend.src.cli reset-password --email etudiant@ecole.fr
```
*La réinitialisation révoque instantanément toutes les sessions et cookies actifs du compte.*

---

## 8. Parcours Utilisateur

### Parcours Étudiant
1. **Connexion** : Rendez-vous sur `http://localhost/` et saisissez vos identifiants.
2. **Configuration SSH** :
   - Rendez-vous sur l'onglet **Profil**.
   - Collez votre clé publique Ed25519 brute (`ssh-ed25519 AAAAC3...`).
   - Cliquez sur **Enregistrer la clé**. La clé est écrite immédiatement dans votre volume persistant.
3. **Lancement de l'environnement** :
   - Choisissez un cours puis un exercice et cliquez sur **Lancer l'environnement**.
   - La bannière supérieure affiche la commande SSH prête à l'emploi :
     ```bash
     ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 22000 student@localhost
     ```
   - Connectez-vous et travaillez dans le répertoire de l'exercice (`~/<nom_exercice>`).
4. **Évaluation** :
   - Cliquez sur **Évaluer**.
   - L'environnement de travail est temporairement arrêté pour éviter toute écriture concurrente.
   - L'évaluateur exécute les tests en lecture seule et affiche le score et les assertions validées.
   - **Règle de score persistant** : Une fois un exercice validé à 100%, la note reste acquise de manière permanente, même si une évaluation ultérieure échoue.

### Parcours Administrateur
1. **Connexion avec un compte admin** : L'onglet **Admin** apparaît automatiquement dans la barre de navigation et le badge `[ADMIN]` est affiché.
2. **Supervision** : Suivez les métriques en temps réel sur l'onglet **Overview**.
3. **Gestion des utilisateurs** : Créez de nouveaux comptes étudiants ou administrateurs et promouvez/rétrogradez des rôles directement depuis l'annuaire.
4. **Déblocage** : Depuis **Active Runtimes**, supprimez un verrou obsolète. Une opération encore active doit se terminer avant le déblocage.
5. **Audit pédagogique** : Consultez l'ensemble des tentatives de tous les étudiants et inspectez les rapports d'évaluations dans l'onglet **Audit Logs**.

---

## 9. Sauvegardes & Restauration

### 9.1 Sauvegarde à chaud de la base SQLite
La base de données est configurée en mode **WAL** (*Write-Ahead Logging*). Utilisez l'API de sauvegarde en ligne SQLite pour garantir une copie intègre sans interruption de service :

```bash
docker compose exec backend python -c "
import sqlite3
src = sqlite3.connect('/data/app.db')
dst = sqlite3.connect('/data/app_backup.db')
src.backup(dst)
dst.close()
src.close()
"
docker compose cp backend:/data/app_backup.db ./backups/app_$(date +%F_%T).db
```

### 9.2 Sauvegarde des volumes étudiants
Pour archiver le travail des étudiants sous forme d'archives tar compressées :

```bash
# Exemple pour le volume de l'étudiant <UUID>
docker run --rm \
  -v "devops-${PLATFORM_INSTANCE:-evalops-prod}-student-<UUID>:/volume:ro" \
  -v $(pwd)/backups:/backup \
  alpine tar -czf /backup/student_<UUID>_$(date +%F).tar.gz -C /volume .
```

Sauvegardez aussi le volume `manager_data`, qui contient les archives des évaluations dans `/data/snapshots`.

### 9.3 Restauration complète
1. Arrêtez les services :
   ```bash
   docker compose stop backend container_manager
   ```
2. Remplacez le fichier `/data/app.db` dans le volume `backend_data`.
3. Restaurez les volumes étudiants et `manager_data` avec un conteneur d'extraction temporaire.
4. Redémarrez les services :
   ```bash
   docker compose start container_manager backend
   ```

---

## 10. Tests Automatisés

La suite de tests est scindée en deux répertoires complémentaires :
- **`tests/unit/`** : Tests unitaires ultra-rapides et hermétiques (sans conteneur Docker ni dépendance au stack en cours d'exécution), couvrant l'authentification, le RBAC, les requêtes admin paginées, le pool de ports, le scoring et la CLI.
- **`tests/functional/`** : Tests fonctionnels avec les étudiants Minions et simulation de capacité sur une instance Docker dédiée.

### 10.1 Exécution complète (Unitaires + Fonctionnels)
```bash
pytest -v tests
```

### 10.2 Exécution ciblée
```bash
# Tests unitaires uniquement
pytest -v tests/unit

# Tests fonctionnels habituels, sans simulation de capacité
pytest -v tests/functional
```

### 10.3 Simulation de concurrence et de capacité

Le scénario utilise trois exercices simples : `hello-c`, `fibo-c` et `sum-c`. Par défaut, il crée **99 étudiants** répartis en trois groupes de 33. Chaque groupe commence par un exercice différent, puis passe aux deux suivants. Les effectifs sont répartis aussi équitablement que possible pour les autres tailles de cohorte.

```bash
# Cohorte de 99 étudiants
pytest tests/functional/test_simulation.py --run-capacity -q -s

# Plus de 100 étudiants, avec des résultats reproductibles
pytest tests/functional/test_simulation.py --run-capacity --simulation-students=150 --simulation-seed=42 -q -s

# Vérification rapide du scénario avec trois étudiants
pytest tests/functional/test_simulation.py --run-capacity --simulation-students=3 -q -s
```

Chaque exécution démarre un projet Docker Compose neuf avec son propre backend, manager, base SQLite et volumes. Seuls les trois exercices sont copiés dans le catalogue de test, avec une échéance future. Les requêtes passent par le vrai serveur HTTP du backend. Les sources sont déposées dans les conteneurs via l'API Docker ; le scénario mesure les environnements et l'évaluation, sans simuler une connexion SSH ou l'interface web. Les comptes, sessions et espaces de travail de l'application habituelle ne sont pas modifiés.

À chaque tour, tous les environnements sont lancés avant la première soumission : le test vérifie donc réellement 99 environnements actifs et 99 ports SSH distincts. Un étudiant a une probabilité de réussite de **1/3 au premier essai**, puis de **1/2 au deuxième après un échec**, et réussit au troisième. Il cesse de soumettre dès sa réussite. La graine rend les choix reproductibles, indépendamment de l'ordre d'exécution des requêtes concurrentes.

Le test vérifie les notes, les historiques, les trois exercices validés par étudiant et l'absence d'opérations bloquées. Il écrit `simulation-report.json`, `compose.log` et `services.log` dans le répertoire temporaire indiqué à l'écran. Le rapport contient les groupes, les soumissions, le pic d'environnements actifs, la durée, le débit et les latences médiane/p95/max. Les conteneurs, volumes et réseaux de cette exécution sont supprimés à la fin, y compris en cas d'échec ; les images restent dans le cache Docker.

La simulation est activée par `--run-capacity` pour conserver une suite habituelle rapide. `--simulation-students` doit être positif et tenir dans la plage de ports SSH. Pour une cohorte plus grande, augmentez cette plage si nécessaire, par exemple `SSH_PORT_MAX=23999 pytest ...`. Les limites et délais des services restent ceux de l'application : un dépassement de capacité fait échouer le test.

---

## 11. Licence & Crédits

EvalOps est conçu pour l'évaluation et l'enseignement des pratiques DevOps et de l'administration système Linux en milieu académique et professionnel.
