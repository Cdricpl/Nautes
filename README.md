# Transcription audio

Transcrit **mot à mot** un enregistrement audio, en local sur votre ordinateur.
Aucune limite de minutes, aucun abonnement, aucune clé, aucun envoi sur internet.

Remplace la transcription de Word et son quota de 300 minutes par mois.

## Installation (une seule fois)

1. Installer Python : ouvrir le **Microsoft Store**, chercher **Python 3.12**, installer.
2. Double-cliquer sur **`Installer.bat`** et attendre la fin (quelques minutes).

## Utilisation

Double-cliquer sur **`Transcrire.bat`**, puis :

1. **Ajouter...** pour choisir un ou plusieurs enregistrements.
2. Choisir la langue et la qualité.
3. Cliquer **Transcrire**.

Le texte est écrit à côté du fichier d'origine : `reunion.mp3` produit `reunion.txt`.

Au tout premier lancement, le modèle de reconnaissance se télécharge automatiquement
(environ 500 Mo pour *Rapide*, 1,5 Go pour *Équilibré*, 3 Go pour *Meilleure*).
Ensuite tout fonctionne hors ligne, même sans connexion.

## Formats acceptés

MP3, M4A, WAV, FLAC, OGG, OPUS, AAC, WMA, ainsi que les vidéos MP4, MOV, AVI et MKV
(la piste audio est extraite automatiquement). Rien d'autre à installer.

## Qualité et durée de traitement

| Qualité | Précision | 2 h d'audio sur un PC récent |
| --- | --- | --- |
| Rapide (small) | bonne, comparable à Word | 20 à 40 min |
| Équilibré (medium) | meilleure que Word | 45 min à 1 h 30 |
| Meilleure (large-v3) | la plus fidèle | 1 h 30 à 3 h |

Avec une carte graphique NVIDIA, comptez 5 à 10 fois plus rapide : laissez l'option
*Utiliser le GPU* cochée, l'application bascule seule sur le processeur si besoin.

Commencez par **Rapide**. Si le résultat ne vous satisfait pas, refaites le même fichier
en **Équilibré**.

## Options

- **Fichier horodaté en plus** — un second `.txt` avec l'heure devant chaque phrase,
  pratique pour retrouver un passage dans l'enregistrement.
- **Sous-titres .srt** — fichier de sous-titres standard.
- **Identifier les interlocuteurs** — voir ci-dessous.

## Identifier les interlocuteurs

En cochant cette option, le texte est découpé par personne qui parle :

```
Interlocuteur 1 : Bonjour, merci d'être venu aujourd'hui.

Interlocuteur 2 : Merci à vous, je suis ravi d'en discuter.

Interlocuteur 1 : Commençons par le budget annuel.
```

L'application reconnaît les voix, pas les identités : elle ne sait pas *qui* parle, mais
elle sait *quand la voix change*. Le numéro suit l'ordre d'apparition — la première
personne entendue devient **Interlocuteur 1**. Il suffit ensuite de remplacer les
étiquettes par les vrais noms dans Word.

Le nombre d'interlocuteurs est détecté automatiquement, sans avoir à l'indiquer.

Compter environ **8 minutes de calcul par heure d'audio**, en plus de la transcription.
Deux petits modèles (37 Mo au total) se téléchargent au premier usage seulement.

Les étiquettes apparaissent aussi dans le fichier horodaté et dans les sous-titres `.srt`
si ces options sont cochées.

À savoir : la séparation est très fiable quand les personnes parlent chacune à leur tour,
et moins précise quand elles se coupent la parole ou quand une voix est très lointaine.

Vous pouvez ajouter plusieurs fichiers d'un coup : ils sont traités à la suite.
Le bouton **Annuler** interrompt le traitement à tout moment.

## Confidentialité

Tout se passe sur votre machine. Les enregistrements ne quittent jamais l'ordinateur :
aucun serveur, aucun compte, aucune donnée envoyée. Seul le modèle de reconnaissance est
téléchargé, une seule fois, au premier lancement.
