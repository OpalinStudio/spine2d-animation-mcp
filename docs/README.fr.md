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
- **Aperçu sans Spine** : image PNG, planche ou GIF.
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
3. Spine 4.3 installé et activé n'est nécessaire que pour les outils `spine_*` (CLI). Tout le reste fonctionne sans Spine.

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

**Claude Code** : `claude mcp add spine -- uv --directory /chemin/vers/spine2d-animation-mcp run spine2d-mcp`

Sous Windows, `Spine.com` (version console) est préféré à `Spine.exe` pour la ligne de commande, car il affiche la sortie et attend la fin de l'export.

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `SPINE_EXE` | Exécutable Spine, dossier d'installation ou `Spine.app`. Si absent, les emplacements par défaut de chaque système puis le `PATH` sont essayés |
| `SPINE_VERSION` | Version de l'éditeur passée en `-u` (`4.3.xx` = dernier patch 4.3) |
| `SPINE_JSON_VERSION` | Version écrite dans les nouveaux fichiers (défaut `4.3.00`) |
| `SPINE_ARGS` | Lue par Spine 4.3 : arguments ajoutés à chaque lancement |

L'outil `spine_status` indique quel exécutable a été trouvé.

## Exemples de demandes à Claude

- « Importe `C:\art\heros.psd` en rig Spine avec IK sur les jambes et une animation idle et walk. »
- « Ajoute une contrainte physique en chaîne sur les os `cheveux1` à `cheveux4`, avec du vent dans l'animation `idle`. »
- « Crée un slider `sourire` qui pilote l'animation `expression_sourire` sur la translation Y de l'os `controle_visage`. »
- « Fais une animation `attaque` de 0,8 s : anticipation, coup rapide avec easing `easeOutBack`, retour. Montre-moi un GIF. »
- « Mets le bras gauche derrière le corps entre 0,2 et 0,5 s dans `saut`. »
- « Importe `heros.json` dans `heros.spine`, puis exporte en binaire avec atlas dans `export/`. »
- « Exporte l'animation `walk` en PNG à 50 % et 24 fps. »

## Méthode conseillée

1. `import_psd_to_spine` sur un PSD en calques, ou `create_skeleton` pour partir de zéro.
2. Rig : IK, physique sur cheveux et vêtements, sliders pour les expressions, clipping, skins.
3. Animation : une base avec `generate_animation`, puis des retouches avec `set_keyframes`.
4. Vérification avec `render_preview` (planche ou GIF).
5. `spine_import_data` pour obtenir un projet `.spine` à ouvrir dans Spine 4.3.
6. `spine_export` pour le runtime (JSON/binaire + atlas) ou en PNG/GIF/vidéo.

Les coordonnées sont celles de Spine : y vers le haut, relatives à l'os parent, rotations en degrés dans le sens antihoraire. Les valeurs des timelines d'os sont des décalages par rapport à la pose de setup (l'échelle est un multiplicateur).

## Limites

- Les fichiers `.spine` sont un format binaire privé : on modifie le JSON exporté puis on le réimporte (`spine_import_data`).
- L'aperçu Python ne simule ni les contraintes ni le clipping. Pour un rendu exact, utiliser `spine_export` en PNG.
- Les options CLI ajoutées tard dans la 4.3 (`-a`, `--merge`, `--set`) dépendent de la version exacte de l'éditeur. `spine_cli_help` affiche la liste qui fait foi, et `spine_cli` permet de passer des arguments bruts.
