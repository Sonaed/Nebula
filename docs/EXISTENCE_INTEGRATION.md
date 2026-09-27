# Nebula dans Existence

Nebula est un `Universe` autonome de l'écosystème Existence. Existence connaît
son identité, son cycle de vie, ses capacités et ses ressources, mais ne prend
pas possession de son moteur de peinture. Le rendu, le brush engine et le
modèle de document restent dans Nebula, avec le calcul pixel/raster en C++.

## Contrat exposé

Le manifeste machine-readable est
`EXISTENCE/manifest.json`. Il décrit notamment :

- `resource://existence/nebula` comme namespace ;
- `raster_painting`, `brush_engine_cpp` et `tablet_pressure` comme capacités ;
- les messages `open_as_raster`, `send_resource`, `ping` et `get_state` ;
- le répertoire de travail et le point de lancement de Nebula.

Le manifeste est compatible avec le contrat `normalize_contract` du hub
Existence. La version `working_dir` renvoyée par l'adaptateur est recalculée à
partir de l'installation courante afin d'éviter un chemin périmé.

## Transport actuel

Le pont de départ est volontairement simple et sans état :

```text
python -m EXISTENCE.adapter --manifest
python -m EXISTENCE.adapter --handshake
printf '{"message":"ping"}\n' | python -m EXISTENCE.adapter --message
```

`main.py` accepte également `--existence-manifest`,
`--existence-handshake` et `--existence-message`. Dans ce dernier mode, les
requêtes sont JSON Lines. Une ouverture raster répond `deferred_to_gui`, car le
processus Qt déjà lancé doit rester le propriétaire de la fenêtre et de son
event loop. Cette étape évite de créer une deuxième QApplication ; le hub peut
ensuite remplacer cette réponse par une livraison au processus vivant.

## Transport Unix

Le même protocole peut maintenant être servi par une socket locale privée :

```text
python -m EXISTENCE.adapter --socket /run/user/1000/existence/nebula.sock
```

Chaque ligne reçue est une requête JSON et chaque ligne retournée une réponse
JSON. Les messages `handshake`, `ping`, `describe`, `get_state`,
`open_as_raster`, `send_resource` et `close` sont pris en charge. Le serveur
supprime sa socket à la fermeture normale ou après un arrêt du processus.

Le lifecycle manager d'Existence peut donc lancer Nebula, attendre le fichier
socket, effectuer le handshake, surveiller la connexion et déduire un état
`closed` ou `failed` lorsque le processus disparaît. Le détecteur de crash et
la journalisation `universe.failed` restent à brancher dans le hub lui-même ;
Nebula fournit désormais le point d'entrée transportable nécessaire.

## Limites assumées

Le `MessageExecutor` actuel d'Existence valide et journalise les échanges mais
ne livre pas encore les appels au processus d'une application. L'adaptateur
prépare donc le contrat et le handshake sans prétendre fournir une IPC complète.
La prochaine évolution naturelle est un canal local supervisé (JSON Lines sur
stdin/stdout ou socket Unix) géré par le lifecycle manager d'Existence.
