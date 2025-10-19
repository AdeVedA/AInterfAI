<p align="center">
  <img src="assets/icon.png" width="120" alt="AInterfAI Logo">
</p>

<h1 align="center"><font size="7">AInterfAI</font></h1>

<h2 align="center"><font size="6">
  <p>
    <a href="./readme.md">English</a> |
    <b>Français</b>
  </p>
</font></h2>
<p align="center"><font size="4"><em>
Une interface graphique locale pour LLM offrant chat avancé avec édition de messages et de requêtes finales, configurations diverses, injection de contexte et RAG <br>- codé avec/pour PyQt6, LangChain, Qdrant & Ollama -
</em></font></p>

<p align="center">
  <img src="assets/session_chat.gif" width="410" alt="AInterfAI UI Screenshot">
  <img src="assets/session_coder.gif" width="410" alt="AInterfAI UI Screenshot2">
</p>

<div align="center"><font size="4">
<strong>

[⚙️ Stack Technique](#tech-stack)
[🚀 Fonctionnalités](#features)
[⚙️ Installation](#installation)
[⌨️ Raccourcis Clavier](#keyboard-shortcuts)
[🗂️ Arborescence du Projet](#file-structure)
[📜 Licence](#license)

</strong></font>

</div>

---

**AInterfAI** est une application de bureau conçue pour interagir avec des modèles de langage locaux (LLM servis localement par [Ollama](https://ollama.com)) dans un environnement productif et permettant d'enrichir les requêtes avec votre contexte local (documents ).

Construite avec PyQt6 et LangChain, elle supporte la gestion des sessions, la gestion de la configuration des LLM, la gestion des fichiers de contexte avec insertion complète de vos documents (Full) dans vos requêtes ou Retrieval-Augmented Generation (RAG) sur vos propres fichiers - le RAG utilise la base de données vectorielle [Qdrant](https://qdrant.tech).

<div align="center"><font size="4">
<strong>
<h6>----------------------</h6>

<h2>(TL;DR) trop long, pas le temps de lire</h2>

[⚙️ Installation](#installation)

USAGE :

1 - cliquez sur "+ session" (**créer une session**)<br>
2 - **choisir** un **Role**, un **LLM** (règlages éventuels)<br>
3 - cliquez sur **Load LLM**<br>
(3) - si mode de contexte "Full" - choisir au moins un fichier<br>
(3) - si mode de contexte "RAG" - choisir au moins un fichier
(réglages éventuels de du nombre d'extraits K et de leur taille) et cliquez sur "Context vectorization"<br>
4 - écrivez votre prompt. une fois terminé, cliquez sur **ctrl+entrée**<br>
5 - validez votre requête avec **ctrl+entrée**...<br>

<h6>----------------------</h6>
Présentation

</strong></font>

</div>

L'architecture sépare principalement deux couches :

-   **core/** : logique métier, modèles de données, gestionnaires de configuration, gestionnaire de LLM, sous-module rag, thème, convertisseur tiktoken.
-   **gui/** : composants UI PyQt, workers pour le rendu et l'interaction avec le LLM, panneaux.

La partie « core » est indépendante du framework UI et peut donc être réutilisée pour d'autres projets LLM...  
Bien que ce pattern soit utile, il introduit des difficultés pour garder les composants indépendants et partager un état centralisé. PyQt nécessite souvent de nombreux signaux dans ce type de situation.

> Aucun cloud, aucun suivi, aucune télémétrie : 100 % d'« intelligence synthétique » locale.

---

<h2 id="tech-stack">⚙️ Stack Technique</h2>

-   **Ollama** (serveur LLM local avec API REST)
-   **PyQt6** (framework GUI)
-   **SQLAlchemy** (ORM SQLite pour le stockage persistant)
-   **Qdrant** (base de vecteurs pour le RAG)
-   **LangChain** (bibliothèque d'intégration LLM)
-   **LangChain-ollama** (intégration Ollama pour LangChain)
-   **LangChain-qdrant** (intégration Qdrant pour LangChain)
-   **python-docx, python-pptx, pdfminer.six, striprtf** (modules d'extraction de texte)
-   **markdown2** (rendu Markdown)
-   **pygments** (coloration syntaxique)
-   **Configs JSON** (paramètres généraux de l'UI, prompts/configs de prompts, filtres du parseur de contexte)

<h2 id="features">🚀 Fonctionnalités</h2>

### 🧩 Général (Chat, Barre d'outils...)

-   Chat avec les LLM locaux via Ollama
-   **Rendu** Markdown avec coloration syntaxique
-   **Diffusion** de messages en temps réel
-   **Copier**, **modifier**, **supprimer** les messages
-   **Recherche** d'une chaîne dans le contenu des bulles de chat, avec mise en surbrillance et navigation préc/suiv
-   Chargement/déchargement dynamique des modèles
-   Barre d'outils avec **indicateur d'état** du LLM (vert/rouge)
-   **console** superposée affichant la sortie console de l'application (cliquer sur le triangle ▼ en haut-à-gauche du panneau de chat)
-   **comptage** local des **tokens** affiché à l'aide de `tiktoken` (session, requête utilisateur, panier des fichiers de contexte)
-   Options pour :

    -   **Afficher et modifier la requête finale avant envoi** au LLM (avec recherche ctrl+f aussi dedans !)
    -   **Générer** automatiquement un **titre** de session (si le nom de la session a sa forme par défaut) <br> -> Je vous recommande de désactiver cette option si vous avez de faibles ressources, ou si vous utilisez un gros LLM avec une longue session (économie d'énergie et de temps).
    -   Définir le temps de **« keep-alive »** du LLM en mémoire
    -   Définir l'intervalle entre chaque sondage sur la **disponibilité** du LLM

### 🗂️ Gestion des Sessions

-   Multiples sessions de chat avec stockage persistant
-   **Filtrage** par date (avec vos dossiers), type de Prompt (Rôle) ou LLM
-   Organisation par **dossiers** (et dossiers "factices" pour le filtrage des sessions par LLM ou Prompt/Rôle)
-   Glisser-déposer les sessions entre dossiers (avec auto-ouverture des dossiers cibles lors du dépôt)
-   Ouvrir / fermer un dossier
-   Créer automatiquement un dossier de session lorsqu'on dépose une session sur une autre session
-   **Renommer** (double-clic sur le nom de la session/dossier) et **supprimer** les sessions ou dossiers avec l'icône "corbeille"
-   **Infobulle** de session (avec le dernier LLM utilisé, type de prompt/rôle, date...)
-   **Exporter en markdown** une session entière (tous les messages du chat) stylisée avec le thème actif, sauvegardée dans un fichier nommé {nom_de_session}.md
-   Exporter en html (wip...)

### 📚 Système de Contexte

Un système modulaire pour enrichir les prompts avec vos documents (connaissances fondées sur vos documents injectables).

-   **Modes de Contexte**

    -   `OFF` : Aucun contexte externe (requête normale)
    -   `FULL CONTEXT` : Injecte le contenu complet parsé des fichiers sélectionnés
    -   `RAG` : vectorise & récupère les chunks sémantiquement pertinents (pour votre requête) des fichiers sélectionnés via Qdrant avec le modèle d'embedding

    -   Formats supportés : `.pdf`, `.epub`, `.docx`, `.pptx`, `.rtf`, `.txt`, `.md`, `.xml`, `.json`, etc.

-   **Fonctionnalités FULL & RAG**

    -   Paramètres ajustables : `K extracts` (nombre de chunks récupérés) et `chunk size` (taille du chunk ≈ tokens par chunk).
    -   Modèle d'embedding utilisé par défaut : `nomic-embed-text:latest` (vous pouvez changer `embedding_model` dans `core/rag/config.py` pour l'instant)
    -   Rafraîchir l'index (utile après mise à jour des fichiers source)
    -   Vectorisation et indexation par fichier ou paquet de fichiers
    -   **Utilisation du RAG** :
        -   sélectionner vos fichiers,
        -   cliquer sur **Context vectorization**,
        -   (sélectionner et) charger un LLM avec un rôle/Prompt pertinent (RAG... ou créez le vôtre),
        -   écrire & envoyer votre prompt

-   **Parsing de Contexte Multi-Config**

    -   Configurations persistantes et personnalisables du parsing d'arborescence de fichiers (inclusion/exclusions/gitignore/repertoires)nommées et définies par l'utilisateur stockées dans `context_parser_config.json`.
    -   Interface d'édition des configurations à onglets
    -   Contrôle précis des extensions de fichiers, motifs d'inclusion/exclusion avec wildcards et exclusions optionnelles `.gitignore`, nombre maximal d'enregistrements d'historique de dossiers locaux...

-   **Navigation dans l'Arborescence de Fichiers**

    -   Listing récursif depuis un chemin racine (avec une limite -désactivable- à 3000 fichiers pour éviter les risques de surmenage et inviter l'utilisateur à resserer les filtres dans la config)
    -   Respect de `.gitignore` et des exclusions définies par l'utilisateur
    -   Filtrage basé sur les expressions régulières (regex)
    -   Rafraîchissement et scan d'un simple clic

### ⚙️ Gestion de la Configuration LLM

-   **Configurations de prompts par défaut (français ou anglais)**

    -   Les **nombreux modèles de rôle/prompts fournis** permettent de définir rapidement un rôle/prompt système pertinent pour vos LLM.
    -   Toute **modification de la combinaison LLM + rôle/prompt système** et ses paramètres associés peut être **sauvegardée**.
    -   Vous pouvez **créer de nouveaux prompts** en cliquant sur « + New Role ». Si plusieurs rôles ou prompts système partagent le même premier mot suivi d’un espace, ils seront affichés/regroupés dans un sous‑menu correspondant à ce mot.
    -   Les rôles/prompts par défaut sont chargés avec un **choix de langue (français ou anglais)** et organisés en dossiers selon le premier mot de leurs noms. Vous pouvez donc vous organiser comme vous le souhaitez : utilisez « + New Role » dans l’application ou éditez simplement le fichier core/prompt_config_defaults_fr.json.
    -   Lors du changement de langue (français/anglais), le programme tente de trouver et de charger le prompt équivalent dans l’autre langue (par index)

-   **Propriétés du LLM**

    -   Récupération des paramètres par défaut du LLM via l'API locale d'Ollama
    -   Indication des paramètres par défaut (le cas échéant) sur les curseurs du panneau UI de configuration

-   **Configurations Rôle/Prompt & LLM**

    -   Enregistrer/Charger : ensembles Prompt/rôle + paramètres LLM
    -   **Paramètres éditables** (et hyper-paramètres) :
        -   prompt système
        -   temperature, top_k, repeat_penalty, top_p, min_p
        -   max tokens (avec limitation du modèle intégrée)
        -   flash attention (booléen)
        -   kv_cache_type (f16, q8_0, q4_0)
        -   use_mmap (booléen)
        -   num_thread (threads CPU à utiliser)
        -   thinking (booléen, uniquement si le modèle le supporte)

### 🎨 Thèmes & Apparence

-   Thématisation dynamique QSS avec placeholders de couleur (ex. `/*Base*/`, `/*Accent*/`)
-   Thèmes clair/sombre via un système de palette JSON (vous pouvez personnaliser `core\theme\color_palettes.py` à votre guise)
-   Sortie streaming Markdown avec blocs de code mis en surbrillance (autant que possible)
-   Bulles de messages avec icônes copier, éditer et supprimer qui suivent le défilement (double-clic sur les bulles pour afficher/masquer ces icônes)

---

<h2 id="installation">⚙️ Installation</h2>

### 0. Installer [Python 3.13+](https://www.python.org/downloads/) _des versions antérieures pourraient fonctionner... je n'ai simplement pas testé !_ et [git](https://git-scm.com/downloads)

→ [https://www.python.org/downloads/](https://www.python.org/downloads/)

→ [https://git-scm.com/downloads](https://git-scm.com/downloads)

### 1. Récupérer le logiciel

#### A - lancer l'interpréteur de commande windows

Lancez votre explorateur windows (WIN+E). Allez (dans le répertoire) où vous souhaitez mettre le répertoire d'AInterfAI. Clic gauche dans la barre d'adresse de l'explorateur, écrivez **"cmd"** (à la place de l'adresse) et appuyez sur **"entrée"** (comme à chaque fin d'instruction en ligne future):

    cmd  # ou `terminal` sur Mac/Linux

#### B - Créer un répertoire pour le programme

Créez un répertoire. vous pouvez l'appeler **AInterfAI** dans d:\chemin\vers\mon\dossier\AInterfAI

```bash
md AInterfAI # ou `mkdir AInterfAI` sur Mac/Linux
cd AInterfAI
```

#### C - cloner le repo Github du projet dans ce répertoire

dans le terminal (l'invite de commande) qui indique bien que vous êtes à l'adresse du dossier créé, écrivez :

```bash
git clone https://github.com/AdeVedA/AInterfAI
```

### 2. Créer un Environnement Virtuel

```bash
python -m venv env         # ou `python3 -m venv env` sur Mac/Linux
env\Scripts\activate       # ou "source env/bin/activate" sur Mac/Linux
```

### 3. Installer les Dépendances

```bash
pip install -r requirements.txt
```

### 4. Installer Ollama

→ [https://ollama.com/download](https://ollama.com/download)

installez-le. Redémarrez si demandé. Une fois installé, vérifiez (ou ajoutez-le) que le chemin d'installation d'Ollama est bien dans le path de vos variables d'environnement système

-   touche windows, "variables", "Modifier les variables d'environnement système", "Variables d'environnement", selectionnez la ligne "Path", cliquez sur "modifier" et vérifiez que le chemin vers ollama est présent.
-   Si non, cliquez sur "Nouveau"
-   ajoutez: %LOCALAPPDATA%\Programs\Ollama (ou le chemin exact dans lequel vous avez installé Ollama)
-   Cliquez "OK" pour sauvegarder.

### 5. Télécharger un LLM et un embedding

→ [https://ollama.com/search](https://ollama.com/search)
Sur cette page, trouvez un modèle LLM dont la taille est de maximum 3/4 de votre VRAM+RAM (GB), cliquez sur son nom et copiez la commande à exécuter en terminal. Testez une fois en terminal avec une requête (après avoir fait un ollama run {nom_du_model_choisi}) comme ca vous êtes sûr que ca fonctionne côté serveur ollama.

**A.** Téléchargez votre premier modèle (voir la section [Modèles Ollama Recommandés](#modeles_recommandes) si vous êtes perdu, ici on montre comment télécharger `mistral-small3.2:24b`) :

```bash
ollama pull mistral-small3.2:24b
```

Vous pouvez utiliser n'importe quel modèle local compatible avec Ollama (`mistral`, `qwen3`, `gemma3`, `gpt-oss`, etc.).
Si vous avez très peu de ressources (RAM & VRAM), prenez un gemma3n:e4b, ou plus petit (mistral:7b, deepseek-r1:latest)

**B.** Téléchargez le modèle d'embedding `"nomic-embed-text:latest"` (le RAG ne sera pas possible sans lui) :

```bash
ollama pull nomic-embed-text:latest
```

### 6. Installer [Qdrant](https://github.com/qdrant/qdrant/releases)

→ [https://github.com/qdrant/qdrant/releases](https://github.com/qdrant/qdrant/releases)

Téléchargez le fichier correspondant à votre os (qdrant-x86_64-pc-windows-msvc.zip pour Windows, qdrant-x86_64-apple-darwin.tar.gz pour Mac, etc..), décompressez/ouvrez l'archive et mettez le fichier qdrant (binary) dans un dossier de votre choix. Vous **devez** alors indiquer le chemin vers `qdrant.exe` (Windows ex.: C:\BDD\Qdrant\qdrant.exe) ou `qdrant` (mac/linux ex: C:/BDD/Qdrant/qdrant) dans le fichier `.env` à la racine du projet (ouvrez -le avec un editeur de texte, insérez le bon chemin et sauvegardez).
Sinon, autre possibilité, le programme vous demandera le chemin vers qdrant au premier lancement du programme et l'inscrira dans le .env automatiquement.
Vous pouvez aussi personnaliser le fichier de configuration Qdrant `config.yaml` dans le dossier `project_root\utils` si vous savez ce que vous faites.

AInterfAI pourra alors lancer Qdrant automatiquement au démarrage.

### 7. Lancer AInterfAI

```bash
python main.py
```

Lors du premier lancement, le programme interrogera, via des requêtes _locales_ à l'API REST d'Ollama (`api/tags` & `api/show`), les informations des modèles afin de les enregistrer en base et de fournir des indications sur les hyper-paramètres et propriétés recommandés pour chaque LLM au sein du Modelfile d'Ollama et les préférer à ceux associés aux rôles/prompts par défaut (qui sont agnostiques du LLM).
Si besoin, vous pouvez modifier le délai (`sync_time: timedelta = timedelta(days=30)`) entre chaque parsing des propriétés LLM dans `core\llm_properties.py` (si vous mettez à jour les Modelfile souvent).

### 8. Lancement facile (pour un démarrage automatisé)

#### A. Windows

Créez un fichier nommé **`AInterfAI.bat`** dans le même répertoire que `main.py` et `env/`.  
Modifiez ce fichier avec Notepad++ ou WordPad et copiez‑y le contenu suivant (enregistrez, puis double‑cliquez) :

```bat
@echo off
call .\env\Scripts\activate.bat
py main.py
cmd /k
```

Vous pouvez créer un raccourci sur le Bureau en faisant un clic droit sur le fichier et en sélectionnant **“Créer un raccourci”** (ou _Envoyer vers → Bureau_).  
Une fois le raccourci créé, faites un clic droit dessus, choisissez **“Propriétés → Modifier l’icône…”**, puis parcourez `/assets/icon.ico` (ou choisissez votre propre icône).

#### B. macOS / Linux

Créez un fichier nommé **`run.sh`** (ou tout autre nom de votre choix) dans le même répertoire que `main.py` et `env/` et copiez :

```bash
source ./env/bin/activate
python3 main.py
```

Rendez le script exécutable :

```bash
chmod +x run.sh
```

Exécutez‑le depuis un terminal :

```bash
./run.sh
```

<h2 id="modeles_recommandes">🤖 Modèles Ollama Recommandés</h2>

Les réponses les plus rapides proviennent de LLM entièrement chargés dans la VRAM du GPU, mais vous pouvez choisir des modèles plus performants (au prix d'une latence supérieure) en les chargeant à la fois en VRAM et en RAM.

**Pour le chat / usage général :**
| Modèle | VRAM / RAM min | Remarques |
| --- | --- | --- |
| `gemma3n:e4b` | pour CPU bas de gamme (>12 GB RAM) | MOE, léger et très rapide |
| `phi4:14b` | ~8 GB VRAM + ~8 GB RAM | Dense, léger et assez rapide |
| `gpt-oss:20b` | ~6 GB VRAM + ~12 GB RAM | MOE, rapide, performant |
| `qwen3:30b-a3b` | ~8 GB VRAM + ~16 GB RAM | MOE, rapide, performant |
| `qwen3:30b` | ~8 GB VRAM + ~16 GB RAM | Dense, rapide, performant |
| `gemma3:27b-it-qat` | ~12 GB VRAM + ~16 GB RAM | Dense, bon compromis, quantification optimisée (qat) |
| `mistral-small3.2:24b` | ~8 GB VRAM + ~16 GB RAM | Dense, bon compromis, performant |
| `gpt-oss:120b` | ~16 GB VRAM + ~64 GB RAM | MOE, très grand, plus précis |

**Pour le codage :**
| Modèle | VRAM / RAM min | Remarques |
| --- | --- | --- |
| `gpt-oss:20b` | ~6 GB VRAM + ~12 GB RAM | MOE, rapide, performant |
| `qwen3-coder:30b-a3b` | ~8 GB VRAM + ~16 GB RAM | MOE, rapide, performant |
| `gemma3:27b-it-qat` | ~12 GB VRAM + ~16 GB RAM | Dense, bon compromis, quantification optimisée (qat) |
| `qwen3-coder:30b` | ~8 GB VRAM + ~16 GB RAM | Dense, encore plus performant |
| `magistral:24b` | ~8 GB VRAM + ~16 GB RAM | Dense, très performant |
| `gpt-oss:120b` | ~16 GB VRAM + ~64 GB RAM | MOE, très grand, plus précis |

_Note pour les débutants :_ les LLM MOE (Mixture-Of-Experts) sont plus rapides et moins gourmands en ressources que les LLM denses.

---

<h2 id="keyboard-shortcuts">⌨️ Raccourcis Clavier</h2>

| Raccourci                  | Contexte                                                                                                                                                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Ctrl + Molette de souris` | Zoom in/out de la police (dans les bulles de chat)                                                                                                                                                                         |
| `PageUp/PageDown`          | Navigation paginée (dans les bulles de chat et autres zones de texte)                                                                                                                                                      |
| `CTRL + F`                 | Recherche du `mot` sélectionné dans le chat (et dans le dialogue de validation pré-inference),<br>surbrillance des résultats avec précédent/suivant & surbrillance des résultats (dans les messages d'une session ouverte) |
| `CTRL + Enter`             | Envoyer le message (lorsque le champ de saisie du chat a le focus)                                                                                                                                                         |
| `Escape`                   | Annuler (en cours d'édition d'un message, lors d'une recherche)                                                                                                                                                            |
| `CTRL + S`                 | Confirmer & sauvegarder (en cours d'édition d'un message)                                                                                                                                                                  |
| `Enter`                    | Parcourir l'arborescence de fichiers <br>(lorsque la boîte de chemin `Root folder` a le focus)                                                                                                                             |
| `↑ / ↓`                    | Naviguer parmi les chemins récents (dans la boîte de chemin `Root folder`)                                                                                                                                                 |

---

<h2 id="file-structure">🗂️ Arborescence du Projet</h2>

```
project_root/
├── main.py                         # Point d'entrée de l'application
├── requirements.txt                # Dépendances Python
├── README.md
├── config.yaml                     # Configuration Qdrant
│
├── core/                               # Logique back-end (LangChain, DB, parsing,...)
│   ├── config_manager.py           # Gestionnaire de configurations Rôle/Prompt
│   ├── context_parser_config.json  # Configs multi-mode pour la gestion du contexte
│   ├── context_parser.py           # Logique de gestion du contexte
│   ├── database.py                 # Session DB SQLAlchemy
│   ├── llm_manager.py              # Gestionnaire de LLM
│   ├── llm_properties.py           # Gestionnaire des propriétés par défaut du LLM
│   ├── models.py                   # Modèles ORM (Session, Message, Folder, llm_properties, prompt_config)
│   ├── prompt_config_defaults.json # Configs par défaut Rôle/Prompt
│   ├── prompt_config_manager.py    # Gestionnaire de configurations Rôle/Prompt
│   ├── prompt_manager.py           # Construit les prompts LLM à partir des configs
│   ├── session_manager.py          # Gestion des sessions (et leurs messages)
│   ├── message_manager/                  # Module de gestion des messages
│       ├── msg_proc.py             # Gestionnaire de traitement des messages
│       ├── msg_proc_utils.py       # Utilitaires de traitement des messages
│   ├── rag/                              # Module de gestion du rag
│       ├── handler.py              # Gestionnaire global du rag
│       ├── file_loader.py          # Extracteurs de texte pour les formats supportés
│       ├── indexer.py              # Indexation et récupération de chunks Qdrant
│       ├── config.py               # Configuration du pipeline rag
│   ├── theme/                            # Module de thématisation
│       ├── theme_manager.py        # Gestionnaire de thématisation QSS dynamique
│       ├── color_palettes.py       # Palettes de couleurs pour injection QSS
│       ├── theme.qss               # Feuille de style QSS
│   ├── tiktoken/                         # Module tiktoken
│       ├── 9b5ad...                # modèle tiktoken local pour comptage de tokens
│
├── gui/                                # Composants GUI PyQt6
│   ├── chat_panel.py               # Interface de chat LLM avec streaming
│   ├── config_panel.py             # Panneau de gestion des paramètres LLM
│   ├── context_parser_panel.py     # Panneau pour sélection de mode de contexte & sélection de fichiers
│   ├── gui_config.json             # Paramètres persistants de l'UI
│   ├── gui.py                      # Fenêtre principale MainWindow
│   ├── llm_worker.py               # Thread pour le streaming LLM
│   ├── render_worker.py            # Thread du parseur Markdown
│   ├── renderer.py                 # Parseur Markdown avec coloration syntaxique
│   ├── session_panel.py            # Arbre dossier/session avec drag & drop, vue et gestion des sessions
│   ├── thread_manager.py           # Gestionnaire de threads (QThread et threading.Thread...)
│   ├── toolbar.py                  # Panneau de barre d'outils
│   ├── widgets/                          # Petit module de widgets
│       ├── context_config_dialog.py# Dialogue de configuration de contexte
│       ├── prompt_validation_dialog.py # Dialogue de validation de votre requête, editable avant envoi pour inference
│       ├── small_widget.py         # Petits widgets
│       ├── spinner.py              # Spinner « processing... »
│       ├── status_indicator.py     # Indicateur vert/rouge LLM chargé/déchargé
│       ├── search_dialog.py        # Boîte de recherche CTRL+F, surbrillance des résultats dans les bulles avec navigation prev/next
│
├── utils/                              # Modules utilitaires
│   ├── qdrant_launcher.py          # Gestion du lancement/arrêt du binaire Qdrant
│   ├── env_tools.py                # Entrée CLI utilisateur pour placer le chemin Qdrant.exe dans .env si besoin
│   ├── config.yaml                 # Config Qdrant
│
```

---

## 🔮 Perspectives Futures

-   trouver un emploi ! <--- IMPORTANT après presque 5 mois sur cette application !!!!
-   Panneau de chat : « continue / regenerate » des réponses LLM
-   Sauvegarder les messages rendus en HTML pour éviter le rendu à la volée
-   Abstraction de la gestion des serveurs LLM afin d'intégrer llamacpp et/ou LMStudio comme fournisseur LLM
-   Autoriser l'usage de l'API OpenAI pour des requêtes LLM distantes
-   Possibilité d'imbriquer des dossiers de session dans d'autres dossiers de session
-   Création et orchestration d'agents LangChain
-   Résumé structuré multi-fichiers basé sur le RAG
-   Migration de la base SQLite vers PostgreSQL(...?)
-   Intégration de la gestion d'images pour les LLM capables de vision
-   Gestion multilingue de l'interface : traductions... (pour les rôles/prompt par défaut, c'est déjà fait!)
-   Collaborations ?

---

<h2 id="license">📜 Licence</h2>

Ce projet est distribué sous licence GPL v3. Voir le fichier [LICENSE](https://github.com/python-qt-tools/PyQt6-stubs/blob/main/LICENSE) pour plus de détails.

### Licences Tierces

-   [PyQt6](https://github.com/python-qt-tools/PyQt6-stubs/blob/main/LICENSE) - GPL v3
-   [LangChain](https://github.com/langchain-ai/langchain/blob/master/LICENSE) - MIT
-   [Qdrant](https://github.com/qdrant/qdrant/blob/master/LICENSE) - Apache 2.0
-   [Ollama](https://github.com/ollama/ollama/blob/main/LICENSE) - MIT
