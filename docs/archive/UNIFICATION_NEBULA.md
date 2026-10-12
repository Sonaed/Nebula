# Unification des deux copies de Nebula — constat et décision

Date : 2026-09-24

## Conclusion : il n'y a pas de fusion à faire

Les deux répertoires ne sont **pas** deux branches divergentes du projet.
`Documents/Nebula` est le dépôt vivant ; `~/Nebula` est un
clone ordinaire, figé et strictement en retard.

## Preuves

**1. `Documents/Nebula` EST un dépôt git.**

`.nebula-git/.git/config` contient :

    [core]
        worktree = /home/deanos/Documents/Nebula
    [remote "origin"]
        url = git@github.com:Sonaed/Nebula.git

Le `.git` est déporté dans `.nebula-git/` (et `.nebula-git/` est lui-même
listé dans le `.gitignore`), ce qui explique qu'il passe inaperçu : le
répertoire n'a pas l'air d'un dépôt alors qu'il en est un.

**2. Les deux pointent sur le même `origin`** — `git@github.com:Sonaed/Nebula.git`.
Ce ne sont pas deux projets, c'est deux clones du même.

**3. `~/Nebula` est figé au 22 septembre 12:18.**
Tous ses fichiers portent la même date. `Documents` contient tout le travail
postérieur (jusqu'au 24 septembre).

**4. `~/Nebula` est un sous-ensemble strict.**
Aucun fichier source n'existe dans `~/Nebula` sans exister dans `Documents`.
L'inverse est faux — exemple sur `CANVAS/` :

| Fichier | `~/Nebula` | `Documents` |
|---|---|---|
| `gpu_safe_blitter.py` | absent | présent |
| `gpu_tile_compositor.py` | absent | présent |
| `view_state.py` | absent | présent |
| `memory_manager.py` | 14 725 o | 16 615 o |

Les seuls fichiers propres à `~/Nebula` sont des sauvegardes
`*.before_*` (`canvas.py.before_gpu_canvas`, etc.), que le `.gitignore`
de `Documents` exclut volontairement.

## Décision

`Documents/Nebula` est la copie de référence. C'est celle que
le hub utilise, celle qui est versionnée, celle qui contient tout le travail
récent.

`~/Nebula` peut être supprimé **après** ces deux vérifications, à faire
par toi :

    cd "/home/deanos/Documents/Nebula"
    git --git-dir=.nebula-git/.git status
    git --git-dir=.nebula-git/.git log --oneline -5

    cd ~/Nebula
    git status          # doit être clean
    git log --oneline -3

Si `~/Nebula` est clean et que son dernier commit est déjà dans l'historique
de `Documents`, rien n'y est unique : le dépôt distant en garde l'historique
complet, la suppression ne perd rien.

    rm -rf ~/Nebula

Si `git status` y montre des modifications non commitées, les inspecter
avant de supprimer — elles seraient le seul contenu réellement unique.

## Pourquoi je ne l'ai pas supprimé moi-même

Cette session ne dispose pas d'un shell sur ta machine ni d'outil de
suppression : je peux écrire et modifier des fichiers, pas en effacer.
Et 1 659 fichiers ne se suppriment pas sur une déduction, même solide.

## Risque écarté au passage

Tout le travail de cette session (moteur de brush, gestion mémoire,
nettoyage du code mort) a été écrit dans `Documents/Nebula`,
c'est-à-dire dans le dépôt versionné et dans la copie utilisée par le hub.
Rien n'a été écrit dans la copie morte.
