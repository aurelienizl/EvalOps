# Guide de Création de Cours et d'Exercices — EvalOps

Bienvenue dans le guide officiel de conception de cours et d'exercices pour la plateforme **EvalOps**.

Ce document est conçu pour les enseignants et formateurs souhaitant créer des travaux pratiques (TP), des devoirs et des examens en toute autonomie. Aucune connaissance préalable de l'architecture interne d'EvalOps n'est requise : il vous suffit de suivre la structure de fichiers et les contrats décrits ci-dessous.

---

## Table des Matières

1. [Vue d'Ensemble & Fonctionnement](#1-vue-densemble--fonctionnement)
2. [Structure Générale des Fichiers](#2-structure-générale-des-fichiers)
3. [Définir un Cours (`course.yaml`)](#3-définir-un-cours-courseyaml)
4. [Définir un Exercice (`exercise.yaml` & `README.md`)](#4-définir-un-exercice-exerciseyaml--readmemd)
5. [L'Environnement de Travail de l'Étudiant (`dev/`)](#5-lenvironnement-de-travail-de-létudiant-dev)
6. [Le Correcteur Automatisé (`evaluator/`)](#6-le-correcteur-automatisé-evaluator)
7. [Fichiers et Ressources Téléchargeables (`resources/`)](#7-fichiers-et-ressources-téléchargeables-resources)
8. [Quotas et Contraintes d'Exécution](#8-quotas-et-contraintes-dexécution)
9. [Exemple Complet Clé-en-Main](#9-exemple-complet-clé-en-main)
10. [Checklist de Validation avant Déploiement](#10-checklist-de-validation-avant-déploiement)

---

## 1. Vue d'Ensemble & Fonctionnement

Dans EvalOps :
- Un **Cours** (ou module) regroupe un ensemble d'exercices ordonnés avec une date limite de rendu.
- Un **Exercice** est composé de deux environnements Docker isolés :
  1. **L'environnement de développement (`dev/`)** : Le conteneur dans lequel l'étudiant se connecte via SSH pour programmer, administrer ou tester ses solutions. L'étudiant dispose d'un volume persistant dans son répertoire personnel.
  2. **L'évaluateur (`evaluator/`)** : Un conteneur éphémère lancé lorsque l'étudiant clique sur **« ÉVALUER »**. Il inspecte les fichiers produits par l'étudiant en lecture seule, exécute les assertions et écrit un rapport de notation au format JSON.

```
+-----------------------------------------------------------------------+
|                              ÉTUDIANT                                 |
|                                                                       |
|  1. Connexion SSH                      2. Clic sur "Évaluer"          |
|         |                                      |                      |
|         v                                      v                      |
|   +---------------+                     +---------------+             |
|   | Conteneur Dev |                     |  Évaluateur   |             |
|   |   (Interactif)|                     |  (Éphémère)   |             |
|   +-------+-------+                     +-------+-------+             |
|           |                                     |                     |
|           | Écriture                            | Lecture seule       |
|           v                                     v                     |
|   +---------------------------------------------+---------+           |
|   | Volume Persistant (/home/student/<workspace_dir>)     |           |
|   +-------------------------------------------------------+           |
|                                                 |                     |
|                                                 | Génère              |
|                                                 v                     |
|                                         /result/result.json           |
+-----------------------------------------------------------------------+
```

---

## 2. Structure Générale des Fichiers

Tous les cours sont situés dans le dossier racine `courses/`. Chaque cours possède son propre sous-dossier, qui contient un fichier `course.yaml` et un dossier `exercises/`.

Voici l'arborescence standard :

```text
courses/
└── <nom-du-cours>/                         # Ex: linux, python, docker-k8s
    ├── course.yaml                         # Métadonnées du cours
    └── exercises/
        ├── <nom-exercice-1>/               # Ex: hello-world, sys-config
        │   ├── exercise.yaml               # Métadonnées et barème de l'exercice
        │   ├── README.md                   # Consignes affichées dans l'interface
        │   ├── dev/                        # Environnement de travail de l'étudiant
        │   │   ├── Dockerfile
        │   │   └── entrypoint.sh
        │   ├── evaluator/                  # Script d'évaluation automatique
        │   │   ├── Dockerfile
        │   │   └── evaluate.py
        │   └── resources/                  # (Optionnel) Fichiers d'aide ou code de départ
        │       └── aide.txt
        └── <nom-exercice-2>/
            └── ...
```

---

## 3. Définir un Cours (`course.yaml`)

À la racine de votre cours, créez le fichier `course.yaml`.

### Exemple de `course.yaml`
```yaml
id: linux
name: Bases Linux & Administration Système
deadline: "2026-12-31T23:59:59+01:00"
```

### Spécification des champs

| Champ | Type | Obligatoire | Description |
| :--- | :--- | :--- | :--- |
| `id` | Chaîne | **Oui** | Identifiant unique du cours. Lettres minuscules, chiffres, tirets `-` et underscores `_` uniquement (`^[a-z0-9][a-z0-9_-]{0,63}$`). |
| `name` | Chaîne | **Oui** | Nom complet et lisible affiché aux étudiants. |
| `deadline` | Chaîne ISO 8601 | **Oui** | Date et heure limite de rendu. **Le décalage horaire (+01:00, +02:00 ou Z) est obligatoire.** |

> [!IMPORTANT]
> L'identifiant `id` doit être unique sur l'ensemble de la plateforme EvalOps.

---

## 4. Définir un Exercice (`exercise.yaml` & `README.md`)

Chaque exercice possède son sous-dossier dans `exercises/<nom-exercice>/`.

### 4.1. Le manifeste `exercise.yaml`

Ce fichier configure la difficulté, les quotas et l'espace de travail de l'exercice.

```yaml
id: hello-shell
name: Premier script shell
difficulty: warmup
workspace_dir: hello-shell
grade_timeout_seconds: 60
max_evaluations: 3
evaluation_window_minutes: 60

resources:
  - id: guide-bash
    name: Guide des commandes de base Bash
    file: resources/aide.txt
```

### Spécification des champs

| Champ | Type | Défaut | Description |
| :--- | :--- | :--- | :--- |
| `id` | Chaîne | - | **Obligatoire.** Identifiant unique de l'exercice (format: `^[a-z0-9][a-z0-9_-]{0,63}$`). |
| `name` | Chaîne | - | **Obligatoire.** Titre de l'exercice affiché dans l'interface. |
| `difficulty` | Chaîne | - | **Obligatoire.** Valeurs autorisées : `warmup`, `easy`, `medium`, `hard`. |
| `workspace_dir` | Chaîne | - | **Obligatoire.** Nom du dossier créé dans `/home/student/<workspace_dir>`. Doit être unique sur toute la plateforme. |
| `grade_timeout_seconds` | Entier | `120` | Durée maximale allouée au conteneur de correction (1 à 300 secondes). |
| `max_evaluations` | Entier | `3` | Nombre maximum de soumissions autorisées dans la fenêtre de temps. |
| `evaluation_window_minutes` | Entier | `60` | Durée de la fenêtre glissante en minutes pour le quota d'évaluations. |
| `resources` | Liste | `[]` | Fichiers additionnels téléchargeables par l'étudiant depuis l'interface. |

> [!NOTE]
> **Découplage complet des tests** : Les tests unitaires ne sont plus déclarés à l'avance dans `exercise.yaml`. Ils sont émis dynamiquement par le conteneur d'évaluation dans `/result/result.json`, avec leur statut, leur libellé descriptif et leurs messages d'erreur.

### 4.2. Les consignes (`README.md`)

Rédigez les consignes en Markdown dans le fichier `README.md`. Ce texte s'affiche directement dans la console web de l'étudiant.

**Recommandations de rédaction :**
- Précisez l'emplacement exact où l'étudiant doit travailler (ex: `cd ~/hello-shell`).
- Indiquez les noms exacts des fichiers attendus (la casse compte sous Linux).
- Donnez des exemples de commandes ou de formats d'entrée/sortie.
- Rappelez les critères d'évaluation.

---

## 5. L'Environnement de Travail de l'Étudiant (`dev/`)

Le dossier `dev/` contient les fichiers nécessaires à la création du conteneur de travail interactif de l'étudiant.

### 5.1. Rôle du conteneur `dev`
1. L'étudiant démarre son environnement en cliquant sur **« DÉMARRER »**.
2. EvalOps lance ce conteneur et expose un port SSH dédié.
3. L'étudiant s'y connecte en SSH avec son compte personnel `student`.

### 5.2. `dev/Dockerfile` — Modèle Standard

Voici le Dockerfile standard Debian recommandé. Vous pouvez y ajouter tous les paquets nécessaires à votre TP (ex: `gcc`, `python3`, `git`, `nginx`...) :

```dockerfile
FROM debian:bookworm-slim

# 1. Paquets requis pour le système et SSH (Obligatoire)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    bash \
    coreutils \
    curl \
    nano \
    vim \
    netcat-openbsd \
    ca-certificates \
    procps \
    sudo \
    # Ajoutez ici vos outils pédagogiques (ex: python3, gcc, make, git...) \
    && rm -rf /var/lib/apt/lists/*

# 2. Création de l'utilisateur student (UID/GID 1000 obligatoire)
RUN groupadd -g 1000 student && \
    useradd -u 1000 -g 1000 -m -s /bin/bash student && \
    passwd -d student

# 3. Configuration du serveur SSH
RUN mkdir -p /var/run/sshd /etc/training/authorized_keys && \
    chmod 755 /etc/training/authorized_keys

RUN echo "Port 22" > /etc/ssh/sshd_config.d/devops.conf && \
    echo "PermitRootLogin no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "AuthorizedKeysFile .ssh/authorized_keys /etc/training/authorized_keys/%u" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "StrictModes no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "KbdInteractiveAuthentication no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UsePAM yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UseDNS no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "ClientAliveInterval 30" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "ClientAliveCountMax 5" >> /etc/ssh/sshd_config.d/devops.conf

# 4. Script d'entrée
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
WORKDIR /home/student

# 5. Sonde de santé SSH (Obligatoire pour qu'EvalOps détecte le conteneur prêt)
HEALTHCHECK --interval=2s --timeout=3s --retries=30 CMD nc -z 127.0.0.1 22 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
```

### 5.3. `dev/entrypoint.sh` — Modèle Standard

Ce script configure les clés SSH au démarrage et prépare le répertoire de travail de l'étudiant :

```bash
#!/bin/bash
set -e

# Générer les clés d'hôte SSH si nécessaire
ssh-keygen -A

# Permissions du répertoire personnel et SSH
mkdir -p /home/student/.ssh
chown -R student:student /home/student
chmod 700 /home/student/.ssh
if [ -f /home/student/.ssh/authorized_keys ]; then
    chmod 600 /home/student/.ssh/authorized_keys
fi

# Création et droits sur le dossier de l'exercice
EX_DIR="${WORKSPACE_DIR:-/home/student/workspace}"
if [[ "${EX_DIR}" != /* ]]; then
    EX_DIR="/home/student/${EX_DIR}"
fi
mkdir -p "${EX_DIR}"
chown -R student:student "${EX_DIR}"
chmod 775 "${EX_DIR}"

# Lancer le serveur SSH au premier plan
exec /usr/sbin/sshd -D -e
```

---

## 6. Le Correcteur Automatisé (`evaluator/`)

Le dossier `evaluator/` contient le conteneur qui s'exécute lors du clic sur **« ÉVALUER »**.

### 6.1. Règles d'exécution de l'évaluateur
* **Lecture seule** : Le dossier `/home/student` est monté en lecture seule (`ro`). L'évaluateur ne peut pas modifier les fichiers de l'étudiant.
* **Sécurité réseau** : Le conteneur évaluateur n'a **aucun accès réseau** (`network_mode: none`). Les tests doivent être entièrement locaux.
* **Dossier de résultats** : EvalOps monte un volume vide sur `/result`.
* **Contrat de sortie** : L'évaluateur DOIT écrire un fichier `/result/result.json` contenant la validation des tests avant de se terminer avec un code de retour `0`.

### 6.2. Le format JSON attendu (`/result/result.json`)

Le fichier doit impérativement respecter cette structure :

```json
{
  "schema_version": 1,
  "tests": [
    {
      "id": "script_exists",
      "name": "Le script hello.sh existe et est exécutable",
      "passed": true,
      "message": null
    },
    {
      "id": "correct_output",
      "name": "Le script affiche exactement 'Hello DevOps'",
      "passed": false,
      "message": "Sortie inattendue: 'Hello' (attendu: 'Hello DevOps')"
    }
  ]
}
```

### Spécification des champs de chaque test

| Champ | Type | Obligatoire | Description |
| :--- | :--- | :--- | :--- |
| `id` | Chaîne | **Oui** | Identifiant technique du test. |
| `name` | Chaîne | Non | Libellé convivial affiché dans l'interface web. Si omis, l'interface affiche l'`id`. |
| `passed` | Booléen | **Oui** | `true` si le test est réussi, `false` sinon. |
| `message` | Chaîne ou null | Non | Message de diagnostic, d'erreur ou d'aide affiché à l'étudiant en cas d'échec. |

> [!NOTE]
> **Flexibilité et dynamisme** : Aucun couplage statique n'est requis dans `exercise.yaml`. Votre script de test peut émettre dynamiquement autant de tests qu'il le souhaite. EvalOps calcule automatiquement le score au prorata des tests réussis :
> $$\text{Score (\%)} = \frac{\text{tests réussis}}{\text{tests totaux}} \times 100$$

### 6.3. `evaluator/Dockerfile`

L'évaluateur est très léger. Un environnement Python minimaliste suffit amplement :

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY evaluate.py /app/evaluate.py
RUN chmod +x /app/evaluate.py

ENTRYPOINT ["python3", "/app/evaluate.py"]
```

### 6.4. `evaluator/evaluate.py` — Modèle Standard

Voici un modèle d'évaluation robuste en Python gérant la vérification de fichiers, l'exécution de sous-processus et l'écriture atomique :

```python
#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    # 1. Récupération du dossier de l'étudiant via la variable d'environnement
    workspace_dir = Path(os.environ.get("WORKSPACE_DIR", "/home/student/workspace"))
    script_path = workspace_dir / "mon_script.sh"

    tests = []

    # --- Test 1 : Vérification de l'existence du fichier ---
    if not script_path.exists():
        tests.append({
            "id": "test_fichier_present",
            "name": "Présence et droits d'exécution du script",
            "passed": False,
            "message": f"Le fichier '{script_path.name}' est introuvable."
        })
    elif not os.access(script_path, os.X_OK):
        tests.append({
            "id": "test_fichier_present",
            "name": "Présence et droits d'exécution du script",
            "passed": False,
            "message": f"Le fichier '{script_path.name}' existe mais n'est pas exécutable (utilisez chmod +x)."
        })
    else:
        tests.append({
            "id": "test_fichier_present",
            "name": "Présence et droits d'exécution du script",
            "passed": True,
            "message": None
        })

    # --- Test 2 : Exécution et vérification de la sortie ---
    # Si le test 1 a échoué, on n'exécute pas le test 2
    if not tests[0]["passed"]:
        tests.append({
            "id": "test_sortie_attendue",
            "name": "Validation de la sortie du script",
            "passed": False,
            "message": "Non testé car le script n'existe pas ou n'est pas exécutable."
        })
    else:
        try:
            # Exécution avec timeout strict pour éviter les boucles infinies de l'étudiant
            proc = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(workspace_dir)
            )
            output = proc.stdout.strip()
            
            if "VALEUR_ATTENDUE" in output:
                tests.append({
                    "id": "test_sortie_attendue",
                    "name": "Validation de la sortie du script",
                    "passed": True,
                    "message": None
                })
            else:
                tests.append({
                    "id": "test_sortie_attendue",
                    "name": "Validation de la sortie du script",
                    "passed": False,
                    "message": f"Sortie incorrecte. Reçu: '{output}'"
                })
        except subprocess.TimeoutExpired:
            tests.append({
                "id": "test_sortie_attendue",
                "name": "Validation de la sortie du script",
                "passed": False,
                "message": "Le programme a dépassé le délai maximum de 5 secondes (boucle infinie ?)."
            })
        except Exception as e:
            tests.append({
                "id": "test_sortie_attendue",
                "name": "Validation de la sortie du script",
                "passed": False,
                "message": f"Erreur d'exécution: {str(e)}"
            })

    # --- Écriture atomique du résultat ---
    output_data = {
        "schema_version": 1,
        "tests": tests
    }

    result_dir = Path("/result")
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # Utiliser un fichier temporaire pour éviter toute lecture partielle par la plateforme
    tmp_file = result_dir / "result.json.tmp"
    final_file = result_dir / "result.json"

    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    tmp_file.replace(final_file)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 7. Fichiers et Ressources Téléchargeables (`resources/`)

Si votre exercice nécessite que l'étudiant télécharge un fichier de départ (ex: une archive, un fichier de données CSV, un squelette de code, ou une notice), placez-le dans le dossier `resources/` de l'exercice.

1. **Placez le fichier** dans `exercises/<exercice>/resources/mon_fichier.tar.gz`.
2. **Déclarez-le** dans `exercise.yaml` :
   ```yaml
   resources:
     - id: archive-depart
       name: Squelette du projet C
       file: resources/mon_fichier.tar.gz
   ```
3. L'étudiant verra un bouton **« TÉLÉCHARGER »** directement sous la consigne dans l'interface web.

> [!CAUTION]
> Pour des raisons de sécurité, le chemin `file` ne doit **jamais** utiliser de chemin relatif sortant (ex: `../` ou chemin absolu). Il doit pointer strictement vers un fichier présent dans le dossier de l'exercice.

---

## 8. Quotas et Contraintes d'Exécution

Pour garantir la sécurité et la stabilité du serveur lors des examens ou TP avec de nombreux étudiants en simultané, EvalOps applique les règles automatiques suivantes :

1. **Ressources Conteneurs Strictes** :
   - **CPU** : 0.5 cœur maximum.
   - **RAM** : 512 Mo maximum.
   - **Processus simultanés** : 96 processus max (protection contre les *fork-bombs*).
2. **Isolation Réseau** :
   - Le conteneur dev dispose d'un accès sortant pour installer des outils ou cloner des dépôts si nécessaire.
   - Le conteneur évaluateur est totalement déconnecté du réseau (`network_mode: none`).
3. **Régulation des Soumissions (Rate Limiting)** :
   - Par défaut, un étudiant est limité à **3 évaluations par fenêtre de 60 minutes** (configurable via `max_evaluations` et `evaluation_window_minutes` dans `exercise.yaml`).
   - S'il dépasse ce quota, la plateforme renvoie un message clair lui indiquant dans combien de minutes il pourra soumettre à nouveau, sans interrompre son conteneur de développement.
4. **Instantanés Automatiques (Snapshots)** :
   - À chaque soumission d'évaluation, EvalOps archive automatiquement l'intégralité du répertoire de travail de l'étudiant (`.tar.gz`).
   - L'étudiant et l'enseignant peuvent retrouver et télécharger l'archive de chaque tentative depuis l'historique d'audit.

---

## 9. Exemple Complet Clé-en-Main

Voici un exemple prêt à l'emploi d'un exercice Python où l'étudiant doit écrire un script calculant le nombre d'occurrences de mots dans un fichier texte.

### Arborescence
```text
courses/python/exercises/word-count/
├── exercise.yaml
├── README.md
├── dev/
│   ├── Dockerfile
│   └── entrypoint.sh
└── evaluator/
    ├── Dockerfile
    └── evaluate.py
```

### `exercise.yaml`
```yaml
id: word-count
name: Analyseur de Texte Python
difficulty: easy
workspace_dir: word-count
grade_timeout_seconds: 30
max_evaluations: 5
evaluation_window_minutes: 30
```

### `README.md`
```markdown
# Analyseur de Texte

Dans cet exercice, vous devez créer un script Python nommé `count.py` dans votre dossier de travail `~/word-count`.

### Consignes
1. Le script `count.py` doit lire un fichier nommé `input.txt` situé dans le même répertoire.
2. Il doit afficher sur la sortie standard uniquement le nombre total de mots (séparés par des espaces).

### Exemple
Si `input.txt` contient :
```
Bonjour et bienvenue dans ce TP
```
L'exécution de `python3 count.py` doit afficher :
```
6
```
```

### `dev/Dockerfile`
```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server bash coreutils curl nano vim netcat-openbsd ca-certificates procps sudo \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 student && \
    useradd -u 1000 -g 1000 -m -s /bin/bash student && \
    passwd -d student

RUN mkdir -p /var/run/sshd /etc/training/authorized_keys && \
    chmod 755 /etc/training/authorized_keys

RUN echo "Port 22" > /etc/ssh/sshd_config.d/devops.conf && \
    echo "PermitRootLogin no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "AuthorizedKeysFile .ssh/authorized_keys /etc/training/authorized_keys/%u" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "StrictModes no" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UsePAM yes" >> /etc/ssh/sshd_config.d/devops.conf && \
    echo "UseDNS no" >> /etc/ssh/sshd_config.d/devops.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
WORKDIR /home/student
HEALTHCHECK --interval=2s --timeout=3s --retries=30 CMD nc -z 127.0.0.1 22 || exit 1
ENTRYPOINT ["/entrypoint.sh"]
```

### `dev/entrypoint.sh`
```bash
#!/bin/bash
set -e
ssh-keygen -A
mkdir -p /home/student/.ssh
chown -R student:student /home/student
chmod 700 /home/student/.ssh

EX_DIR="${WORKSPACE_DIR:-/home/student/word-count}"
mkdir -p "${EX_DIR}"
# Créer un fichier input.txt d'exemple pour l'étudiant
if [ ! -f "${EX_DIR}/input.txt" ]; then
    echo "Bonjour et bienvenue dans ce TP" > "${EX_DIR}/input.txt"
fi
chown -R student:student "${EX_DIR}"
chmod 775 "${EX_DIR}"

exec /usr/sbin/sshd -D -e
```

### `evaluator/evaluate.py`
```python
#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    workspace = Path(os.environ.get("WORKSPACE_DIR", "/home/student/word-count"))
    script = workspace / "count.py"
    
    tests = []

    # Test 1 : Existence du fichier
    if not script.is_file():
        tests.append({
            "id": "script_present",
            "name": "Présence du script count.py",
            "passed": False,
            "message": "Le fichier 'count.py' est introuvable dans ~/word-count"
        })
    else:
        tests.append({
            "id": "script_present",
            "name": "Présence du script count.py",
            "passed": True,
            "message": None
        })

    # Test 2 : Test fonctionnel avec un fichier de test dédié
    if not tests[0]["passed"]:
        tests.append({
            "id": "valid_count",
            "name": "Comptage valide des mots",
            "passed": False,
            "message": "Non testé en raison de l'absence du script."
        })
    else:
        # Création d'un fichier de test secret pour la correction
        test_input = workspace / "input.txt"
        secret_content = "Le conteneur docker exécute les tests de manière totalement automatisée"
        # 10 mots attendus
        test_input.write_text(secret_content, encoding="utf-8")

        try:
            res = subprocess.run(
                ["python3", str(script)],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(workspace)
            )
            output = res.stdout.strip()
            if output == "10":
                tests.append({
                    "id": "valid_count",
                    "name": "Comptage valide des mots",
                    "passed": True,
                    "message": None
                })
            else:
                tests.append({
                    "id": "valid_count",
                    "name": "Comptage valide des mots",
                    "passed": False,
                    "message": f"Nombre de mots incorrect: reçu '{output}', attendu '10'"
                })
        except subprocess.TimeoutExpired:
            tests.append({
                "id": "valid_count",
                "name": "Comptage valide des mots",
                "passed": False,
                "message": "Timeout : l'exécution a dépassé 5 secondes."
            })
        except Exception as e:
            tests.append({
                "id": "valid_count",
                "name": "Comptage valide des mots",
                "passed": False,
                "message": f"Erreur lors de l'exécution: {e}"
            })

    result_dir = Path("/result")
    result_dir.mkdir(parents=True, exist_ok=True)
    with open(result_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "tests": tests}, f, indent=2, ensure_ascii=False)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 10. Checklist de Validation avant Déploiement

Avant de mettre vos fichiers à disposition des étudiants sur le serveur EvalOps, vérifiez chaque point :

- [ ] **Identifiants uniques** : Tous les `id` de cours, d'exercices et de `workspace_dir` sont uniques et ne contiennent que des minuscules, chiffres, tirets ou underscores.
- [ ] **Fuseau horaire de la deadline** : `deadline` dans `course.yaml` inclut bien le fuseau horaire (ex: `+01:00`).
- [ ] **UID/GID 1000** : L'utilisateur `student` dans `dev/Dockerfile` possède bien l'UID `1000` et le GID `1000`.
- [ ] **Healthcheck SSH** : La directive `HEALTHCHECK` est bien présente dans `dev/Dockerfile` sur le port 22.
- [ ] **Résultat des tests généré** : L'évaluateur génère bien `/result/result.json` avec une liste `tests` contenant `id`, `name`, `passed` et `message`.
- [ ] **Pas de réseau dans l'évaluateur** : L'évaluateur ne tente aucun `pip install`, `curl` ou accès Internet externe (car le conteneur est lancé avec `network_mode: none`).
- [ ] **Timeouts dans l'évaluateur** : Tous les appels `subprocess.run(...)` dans votre script de test ont un argument `timeout` défini (généralement 5 à 10 secondes) pour éviter les blocages.
- [ ] **Ressources internes** : Les fichiers déclarés dans `resources:` existent bien et ne tentent pas d'échapper au dossier de l'exercice.
