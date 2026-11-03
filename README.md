# ARCTA Web — Release autonome

Analyse Couple/Tension, directement dans le navigateur, **sans DABCTA ni SELECTA**.

## Prérequis

- Python 3.12 ou plus récent installé sur le poste :
  https://www.python.org/downloads/
  (Sous Windows, cochez « Add python.exe to PATH » pendant l'installation.)

## Démarrage

- **Windows** : double-cliquez sur `LANCER_ARCTA.bat`
- **macOS / Linux** : `./lancer_arcta.sh` (ou `bash lancer_arcta.sh`)

Au premier lancement, l'environnement et les dépendances s'installent
automatiquement (quelques minutes). Ensuite, ARCTA s'ouvre dans votre
navigateur à l'adresse **http://127.0.0.1:8737**.

Le serveur tourne uniquement en local sur votre poste : rien n'est publié
sur le réseau, aucune donnée ne sort de la machine. Laissez la fenêtre
console ouverte pendant l'utilisation ; fermez-la (ou Ctrl+C) pour
arrêter ARCTA.

## Où sont les résultats

Les sorties (rapports PDF, exports Excel, manifestes) sont écrites dans :

- par défaut : `Documents/ARCTA_OUTPUTS/`
- sinon : le dossier indiqué par la variable d'environnement
  `ARCTA_OUTPUTS_DIR`

## Contenu du dossier

- `apps/arcta_web/`, `src/`, `DABCTA_64*.py` : code applicatif ARCTA.
  Les modules `DABCTA_64*.py` sont des briques de calcul internes
  utilisées par le moteur ARCTA ; ils ne nécessitent pas l'application
  DABCTA.
- `requirements.txt` : dépendances Python installées au premier
  lancement.
- `LANCER_ARCTA.bat` / `lancer_arcta.sh` : lanceurs.

## Dépannage

- « Python introuvable » : installez Python 3.12+ et relancez.
- Le port 8737 est occupé : fermez l'autre instance, ou éditez la
  variable `PORT` dans le lanceur.
- Après une mise à jour des sources : relancez le lanceur ; pour
  réinstaller les dépendances, supprimez le dossier `.venv` puis
  relancez.
