# spine2d-mcp : guide en français

Serveur MCP qui permet à un assistant IA (Claude Desktop, Claude Code…) de **rigger et animer des personnages Spine 4.3** (Essential / Professional) et de piloter la ligne de commande de l'éditeur Spine sur **macOS, Windows et Linux**.

Le serveur travaille sur les fichiers JSON de squelette Spine. Chaque outil charge le fichier, applique une modification, valide le résultat selon les règles du lecteur Spine 4.3, puis enregistre. Une modification invalide est refusée et le fichier n'est pas touché. Les fichiers exportés par Spine sont relus et réécrits sans perte : on peut faire des allers-retours entre l'éditeur et l'assistant.

## Ce que ça couvre

- **PSD → rig** : un PSD en calques devient os, slots, attachments, atlas et images par partie, avec os orientés, IK jambes/bras et animations de départ en option.
- **Squelette** : os (coordonnées locales ou monde, reparentage qui garde la pose, modes d'héritage, icône 4.3, visibilité), slots, ordre de dessin, skins.
- **Attachments** : région (avec séquences d'images), mesh (grille, contour polygonal ou explicite), poids automatiques, linked mesh (4.3 : source dans un autre slot), bounding box, clipping (4.3 : inverse et convexe), point, path.
- **Contraintes 4.3** : IK (`scaleY` none/uniform/volume), transform (nouveau mapping de propriétés from→to), path, physique (chaîne, vent/gravité globaux), **sliders**. L'ordre du tableau donne l'ordre de mise à jour.
- **Animation** : toutes les timelines 4.3 (os, slot, IK, transform, path, physique, slider, deform, sequence, événements), courbes bezier et presets d'easing, ordre de dessin complet ou partiel, **dossiers d'ordre de dessin 4.3**, retiming.
- **Animations procédurales** : idle, marche, course, saut, salut, hochement de tête, clignement, flottement, rebond (squash & stretch), tremblement, oscillation, follow-through, flash, fondu, pulsation, teinte.
- **Animations de symboles de slot** : `symbol_idle` (boucle au repos), `symbol_land` (arrivée en fin de rouleau), `symbol_win` (gain : contraction, pop, flash, gelée), `symbol_anticipation` (tension avant le 3e scatter), `symbol_dim` (assombrir les perdants). Elles partent et reviennent à la pose de setup, donc s'enchaînent dans le jeu.
- **Rendu par le runtime officiel** (`runtime_render`) : le vrai `spine-webgl` d'Esoteric dans un Chromium invisible. Physique, IK, clipping, additif et teinte deux couleurs sont calculés comme dans le jeu. PNG, dossier d'images, planche, GIF, APNG, WebP, MP4, WebM avec alpha, MOV ProRes 4444 avec alpha.
- **Rendu par l'éditeur Spine** (`editor_render`) : le rendu de référence pour les livrables. GIF, APNG, WebM, MOV, AVI ou séquences PNG / WebP / JPEG, depuis un `.spine` ou un JSON importé dans un projet temporaire.
- **Validation par le runtime** (`runtime_validate`) : charge le JSON ou le `.skel` et l'atlas dans le runtime officiel. Si ça passe, le jeu le chargera.
- **Aperçu web** (`export_web_preview`) : un seul fichier HTML avec le Spine Web Player, boutons d'animation, de skin, de fond et de vitesse. Vérifié automatiquement en taille téléphone et bureau.
- **Pack pour le jeu** (`export_game_pack`) : `.skel` ou `.json` + atlas par l'éditeur, alpha prémultiplié, plusieurs résolutions (`@0.5x`), poids mémoire des textures, puis contrôle de chargement dans le runtime.
- **Aperçu Python rapide** : image PNG, planche ou GIF (approximatif, sans contraintes).
- **Atlas** : empaquetage, lecture, dépaquetage en Python pur.
- **CLI Spine** : export JSON/binaire/atlas/PNG/GIF/vidéo, import de données dans un projet `.spine` (fusion et import d'animation 4.3), texture packer, unpack, clean up, infos projet, derniers réglages d'export (4.3), overrides `--set` (4.3).

La liste complète des outils est dans le [README anglais](../README.md#what-it-covers).

## Installation

1. Installer [uv](https://docs.astral.sh/uv/) :
   - macOS : `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell) : `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Cloner le dépôt puis, dans le dossier :
   ```bash
   uv sync
   uv run pytest
   ```
3. Spine 4.3 installé et activé n'est nécessaire que pour les outils `spine_*`, `editor_render` et `export_game_pack`. Tout le reste fonctionne sans Spine.
4. Rendu par le runtime officiel : au premier usage, le serveur télécharge `@esotericsoftware/spine-webgl` et `spine-player` depuis npm (empreinte sha512 vérifiée) dans le cache utilisateur, jamais dans le dépôt. Il faut aussi un Chromium invisible : outil `spine_runtime_setup`, ou `uv run playwright install chromium-headless-shell`. `ffmpeg` est nécessaire pour MP4, WebM et MOV.

> **Licence** : les Spine Runtimes sont sous la *Spine Runtimes License*. Chaque utilisateur doit avoir sa propre licence de l'éditeur Spine. C'est pour cela qu'ils sont téléchargés depuis npm sur la machine de l'utilisateur, et pas copiés dans ce dépôt MIT.

## Configuration de Claude Desktop

*Réglages → Développeur → Modifier la config*, puis ajouter le serveur.

**macOS** (`~/Library/Application Support/Claude/claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "spine": {
      "command": "uv",
      "args": ["--directory", "/Users/vous/code/spine2d-animation-mcp", "run", "spine2d-mcp"],
      "env": {
        "SPINE_EXE": "/Applications/Spine.app/Contents/MacOS/Spine",
        "SPINE_VERSION": "4.3.xx"
      }
    }
  }
}
```

**Windows** (`%APPDATA%\Claude\claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "spine": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\vous\\code\\spine2d-animation-mcp", "run", "spine2d-mcp"],
      "env": {
        "SPINE_EXE": "C:\\Program Files\\Spine\\Spine.com",
        "SPINE_VERSION": "4.3.xx"
      }
    }
  }
}
```

Si `uv` n'est pas trouvé, mettre son chemin complet (`which uv` sur Mac, `where uv` sur Windows). Redémarrer Claude Desktop ensuite.

**Claude Code** (macOS, Windows ou Linux) : `claude mcp add spine -- uv --directory /chemin/vers/spine2d-animation-mcp run spine2d-mcp`

**Linux** : Claude Desktop n'existe pas officiellement sous Linux, on passe donc par Claude Code ou tout autre client MCP. Spine est cherché dans `~/Spine/Spine.sh`, `/opt/Spine/Spine.sh`, `/usr/local/Spine/Spine.sh` puis dans le `PATH`. Sinon, définir `SPINE_EXE=/chemin/vers/Spine.sh`.

Sous Windows, `Spine.com` (version console) est préféré à `Spine.exe` pour la ligne de commande, car il affiche la sortie et attend la fin de l'export.

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `SPINE_EXE` | Exécutable Spine, dossier d'installation ou `Spine.app`. Si absent, les emplacements par défaut de chaque système puis le `PATH` sont essayés |
| `SPINE_VERSION` | Version de l'éditeur passée en `-u` (`4.3.xx` = dernier patch 4.3) |
| `SPINE_JSON_VERSION` | Version écrite dans les nouveaux fichiers (défaut `4.3.00`) |
| `SPINE_ARGS` | Lue par Spine 4.3 : arguments ajoutés à chaque lancement |
| `SPINE_RUNTIME_VERSION` | Runtime web à utiliser : `4.3` (dernier 4.3.x), `4.2` ou une version exacte. Par défaut, celle des données (un export 4.2 est rendu avec le runtime 4.2) |
| `SPINE_MCP_CACHE` | Dossier du cache des runtimes (défaut : `~/Library/Caches/spine2d-mcp` sur Mac) |
| `SPINE_MCP_GL` | `software` pour forcer le rendu CPU (serveur sans GPU). Par défaut, GPU (Metal sur Mac) puis CPU |

L'outil `spine_status` indique quel exécutable a été trouvé.

## Exemples de demandes à Claude

- « Importe `C:\art\heros.psd` en rig Spine avec IK sur les jambes et une animation idle et walk. »
- « Ajoute une contrainte physique en chaîne sur les os `cheveux1` à `cheveux4`, avec du vent dans l'animation `idle`. »
- « Crée un slider `sourire` qui pilote l'animation `expression_sourire` sur la translation Y de l'os `controle_visage`. »
- « Fais une animation `attaque` de 0,8 s : anticipation, coup rapide avec easing `easeOutBack`, retour. Montre-moi un GIF. »
- « Mets le bras gauche derrière le corps entre 0,2 et 0,5 s dans `saut`. »
- « Importe `heros.json` dans `heros.spine`, puis exporte en binaire avec atlas dans `export/`. »
- « Exporte l'animation `walk` en PNG à 50 % et 24 fps. »
- « Ajoute à `gemme.json` les animations `symbol_land`, `symbol_win` avec un flash sur le slot `gemme` et `symbol_dim`, puis montre-moi une planche du gain sur fond `#1b1d22`. »
- « Fais un aperçu HTML de `gemme.json` que j'ouvre sur mon téléphone. »
- « Exporte `gemme.spine` pour le jeu en binaire, atlas 2048 max, résolutions 1 et 0,5. »

## Méthode conseillée

1. `import_psd_to_spine` sur un PSD en calques, ou `create_skeleton` pour partir de zéro.
2. Rig : IK, physique sur cheveux et vêtements, sliders pour les expressions, clipping, skins.
3. Animation : une base avec `generate_animation`, puis des retouches avec `set_keyframes`.
4. Vérification avec `runtime_render` (planche sur le fond du jeu, puis GIF ou WebM), et `runtime_validate`.
5. `spine_import_data` pour obtenir un projet `.spine` à ouvrir dans Spine 4.3.
6. `export_game_pack` pour le jeu, `editor_render` pour les vidéos et GIF de présentation, `export_web_preview` pour faire valider sur téléphone.

Les coordonnées sont celles de Spine : y vers le haut, relatives à l'os parent, rotations en degrés dans le sens antihoraire. Les valeurs des timelines d'os sont des décalages par rapport à la pose de setup (l'échelle est un multiplicateur).

## Limites

- Les fichiers `.spine` sont un format binaire privé : on modifie le JSON exporté puis on le réimporte (`spine_import_data`).
- L'aperçu Python (`render_preview`) ne simule ni les contraintes ni le clipping. Utiliser `runtime_render` (runtime officiel) ou `editor_render` (éditeur).
- Sur fond transparent, les slots en mode additif n'ajoutent leur lumière à rien : les halos paraissent absents. Spine fait pareil. Passer `background` avec la couleur du jeu pour les juger (l'outil prévient).
- Spine 4.3.26 : l'import JSON plante sur une timeline `rgba` ou `rgb` courbée d'un slot à teinte deux couleurs. Le serveur la réécrit automatiquement en `rgba2` / `rgb2`, avec le même rendu.
- Depuis la CLI, l'éditeur 4.3.26 refuse les exports PSD, MP4 et HTML. `editor_render` propose les formats qui marchent ; pour le MP4, utiliser `runtime_render`.
- Les options CLI ajoutées tard dans la 4.3 (`-a`, `--merge`, `--set`) dépendent de la version exacte de l'éditeur. `spine_cli_help` affiche la liste qui fait foi, et `spine_cli` permet de passer des arguments bruts.
