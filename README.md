# Transcription audio

Transcrit **mot à mot** un enregistrement audio, en local sur votre ordinateur.
Aucune limite de minutes, aucun abonnement, aucune clé, aucun envoi sur internet.

Remplace la transcription de Word et son quota de 300 minutes par mois.

## Installation (une seule fois)

1. Télécharger l'installateur :
   **[TranscriptionAudio-Installateur.exe](https://github.com/Cdricpl/Nautes/releases/latest)**
2. Double-cliquer dessus et suivre les trois écrans.

C'est tout. Pas de Python à installer, pas de dossier à décompresser. Le programme
apparaît ensuite dans le menu Démarrer, et se désinstalle comme n'importe quel autre
logiciel depuis *Paramètres → Applications*.

L'installation ne demande pas de mot de passe administrateur : elle se fait dans votre
compte utilisateur.

> Windows peut afficher un bandeau bleu **« Windows a protégé votre ordinateur »**.
> Cliquer sur **Informations complémentaires**, puis sur **Exécuter quand même**.
> C'est le comportement normal pour un programme sans certificat de signature payant.

## Utilisation

Lancer **Transcription audio** depuis le menu Démarrer, puis :

1. **Ajouter...** pour choisir un ou plusieurs enregistrements.
2. Choisir la langue et la qualité.
3. Cliquer **Transcrire**.

Le bouton **Mode sombre**, en haut à droite, bascule l'affichage.

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

## Fichiers longs (1 h et plus)

Sur un enregistrement de 2 h en *Meilleure qualité* sans carte graphique, le calcul dure
plusieurs heures. Pendant ce temps :

- **Windows peut afficher « Ne répond pas »** dans la barre de titre. Ce n'est pas un
  plantage : la fenêtre est simplement occupée. Le calcul continue.
- Pour vérifier que ça avance, ouvrez le dossier de votre enregistrement : un fichier
  **`nom_en_cours.txt`** s'y remplit au fil de la transcription. S'il grossit, tout va bien.
- Ce fichier sert aussi de filet de sécurité : en cas de coupure de courant ou de
  fermeture accidentelle, le texte déjà transcrit est conservé. Il est supprimé
  automatiquement une fois le fichier final écrit.
- Le temps restant estimé s'affiche sous la barre de progression après une minute.

**Conseil** : pour un fichier de plus de 2 h sans carte graphique NVIDIA, préférez
**Équilibré** à *Meilleure qualité*. Vous passez de plusieurs heures à environ une heure
et demie, pour une différence de qualité faible sur un enregistrement correct.

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

### Indiquez le nombre de personnes

C'est le réglage le plus important de cette option. **Dites combien de personnes parlent**
dans la liste déroulante prévue à cet effet.

Sans cette information, le programme doit deviner, et il se trompe beaucoup : sur une
conversation réelle de 10 minutes à 2 voix, la détection automatique produisait
**16 interlocuteurs** au lieu de 2. Une même personne est recomptée dès que le micro
bouge ou que le ton change.

Avec le nombre exact, le découpage est fiable. Le choix *Je ne sais pas* reste possible
et a été nettement amélioré (2 interlocuteurs trouvés sur le même test), mais il reste
moins sûr qu'un nombre donné.

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

## Pour les développeurs

Lancer depuis les sources, sans installateur :

```
pip install -r requirements.txt
python transcrire.py
```

L'installateur Windows est construit automatiquement par GitHub à chaque envoi sur la
branche de développement (`.github/workflows/installateur-windows.yml`). La compilation
ne peut pas se faire sur une machine Linux : PyInstaller produit un exécutable pour le
système sur lequel il tourne.
