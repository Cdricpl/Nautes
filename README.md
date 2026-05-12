# Nautes

Application web mobile installable pour prendre des notes de rendez-vous.

## Ce qui est pret

- Accueil minimaliste avec un seul bouton : `Demarrer` / `Stop`.
- Apres `Stop` : transcription puis compte-rendu IA automatiques.
- Parametres separes : langue, modele, consentement, mode offline/cloud, export.
- Historique local en memoire du telephone via `localStorage`.
- PWA installable avec `manifest.webmanifest` et `sw.js`.

## Tester sur ordinateur

Ouvrir `index.html` dans un navigateur.

Pour que le micro et l'installation PWA fonctionnent correctement, il faut servir le dossier en `https` ou en `localhost`.
Exemple depuis VS Code :

```bash
node server.mjs
```

Puis ouvrir :

```text
http://localhost:8080
```

## Publier sur GitHub Pages

L'application est déjà statique et prête à être servie comme page GitHub.

1. Créez un dépôt GitHub pour ce dossier.
2. Poussez les fichiers sur la branche `main`.
3. Activez GitHub Pages en choisissant la branche `main` et le dossier racine (`/`).
4. Ouvrez l'URL GitHub Pages depuis votre smartphone.
5. Ajoutez la page à l'écran d'accueil pour un usage PWA.

Si vous préférez un déploiement automatique, un workflow GitHub Actions est déjà fourni dans `.github/workflows/pages.yml`.

Les notes sont stockées localement dans le navigateur / l'application mobile. La suppression des données du navigateur ou de l'application supprime aussi l'historique.

## Tester sur smartphone

- Ouvrez l'URL publique GitHub Pages sur votre mobile.
- Le micro, le PWA et les traductions fonctionnent sous HTTPS.
- Ajoutez l'application à l'écran d'accueil pour un accès rapide.

## A brancher plus tard

- Remplacer `fakeTranscribe` dans `app.js` par un appel a `/api/transcribe`.
- Remplacer `fakeSummarize` dans `app.js` par un appel a `/api/summarize`.
- Remplacer `localStorage` par IndexedDB ou SQLite chiffre si les notes deviennent sensibles.
