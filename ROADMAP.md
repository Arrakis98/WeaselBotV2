# Weasel Bot V2 — Roadmap à partir de la version actuelle

## Phase 5.5 — Stabilisation de la version actuelle

* Finaliser le commit contenant Components V2, le hard stop, la queue propre, le loop fonctionnel et les volumes mémorisés par piste. 🛡️
* Push sur `main` et création d’un nouveau tag stable. 🏷️
* Vérifier les migrations SQLite, les tests, la restauration depuis la sauvegarde et les documents de déploiement. ✅
* Documenter les dernières modifications importantes dans `arcadia-infra`. 🗂️

## Phase 6 — Weasel Galaxy : identité et expérience Discord

### Phase 6.1 — Direction artistique

* Palette magenta, violet électrique et ambiance galaxy. 🌌
* Pack d’icônes personnalisées sans texte pour les contrôles. ✨
* Mascotte Weasel statique, puis test d’une variante animée. 🐾
* Amélioration de la hiérarchie, de l’espacement et des états visuels du panneau Components V2. 🎨
* Remplacement progressif des emojis Unicode génériques par des emojis d’application personnalisés. 💎

### Phase 6.2 — Expérience d’utilisation

* Petit message public compact lors d’un ajout, d’un skip ou d’un changement de piste. ✅
* Bouton permettant d’ouvrir un centre de contrôle éphémère complet, à la manière de Rythm. ✅
* Panneau public principal plus léger et panneau personnel détaillé pour les actions avancées. ✅
* Réponses éphémères sobres, sans accumulation inutile. ✅
* Menu `⋯` pour queue, informations, même auteur, même catégorie, playlists et future radio. 📋

### Phase 6.3 — Présence dans le salon vocal

* Mettre à jour le statut du salon vocal avec le morceau en cours. ✅
* Effacer le statut lorsque le bot stoppe ou quitte. ✅
* Ajouter éventuellement durée, artiste ou état du player dans une version compacte. ⏱️

### Phase 6.4 — Modération réversible des SuperDislikes

* Quarantaine SQLite auditée pour les morceaux SuperDisliked. ✅
* `/purge_superdisliked` en prévisualisation puis exécution administrative. ✅
* `/quarantine_list` et `/restore_quarantined` pour rendre la modération réversible. ✅
* Aucun effacement définitif des fichiers musicaux. ✅

## Phase 7 — Profils et préférences musicales

* `/my_preferences` ou `/profile`. 👤
* Affichage des Likes, SuperLikes, Dislikes et SuperDislikes de l’utilisateur. ❤️
* Listes paginées avec recherche et filtres. 🔍
* Artistes, catégories et morceaux les mieux notés. 📊
* Commandes `/my_likes`, `/my_dislikes`, `/my_superlikes`. 🗃️
* Statistiques globales du serveur et profils séparés par utilisateur Discord. 👥
* Préparation du moteur de recommandations, sans encore modifier automatiquement la lecture. 🧠

## Phase 8 — Playlists modernes

* Création, renommage, suppression et duplication de playlists. 📚
* Ajout et retrait de morceaux depuis Discord. ➕
* Playlists personnelles et playlists partagées au serveur. 🤝
* Lecture dans l’ordre, aléatoire ou pondérée par ratings. 🔀
* Import des anciennes playlists JSON de la V1. 📥
* Boutons et menus pour gérer les playlists sans multiplier les commandes. 🎚️

## Phase 9 — Gestion avancée de la bibliothèque

* Lecture des tags ID3 : artiste, titre, album, année et pochette. 🏷️
* Détection plus fiable des catégories et artistes. 🎤
* Remplacement automatique de `Divers` lorsque de meilleures métadonnées existent. 🧾
* Détection de doublons et outils de nettoyage. 🧼
* Historique d’écoute réel, statistiques et morceaux récemment joués. 🕘
* Recherche améliorée avec filtres par dossier, catégorie, artiste ou rating. 🔎

## Phase 10 — Weasel Effects Studio

* Bass Boost avec plusieurs intensités. 💥
* Speed Control. ⏩
* Pitch Shift. 🎼
* Nightcore et Slowed. 🌙
* Karaoke, tremolo, vibrato, rotation stéréo et low-pass. 🌀
* Presets d’effets enregistrés. 💾
* Interface éphémère dédiée avec sliders, menus ou modales lorsque Discord le permet. 🎛️
* Effets gratuits et exécutés localement par Lavalink. 🏠
* Étude séparée pour reverb, crossfade réel et traitements FFmpeg plus complexes. 🧪

## Phase 11 — Lecture unifiée et sources web

* Remplacer progressivement `/play_local` par une commande principale `/play`. ▶️
* Recherche locale prioritaire. 💿
* Lecture d’URL compatibles. 🔗
* YouTube via un module séparé et remplaçable. 🌐
* Autres fournisseurs via les plugins Lavalink appropriés lorsque cela reste fiable. 🎧
* Une panne de source web ne doit jamais casser la bibliothèque locale. 🛡️
* Cache contrôlé et aucun téléchargement permanent par défaut. 📦

## Phase 12 — Radio intelligente et recommandations

* `Same artist`. 🎙️
* `Same category`. 🗂️
* Radio locale basée sur les dossiers et métadonnées. 📻
* Favoriser Likes et SuperLikes. ❤️
* Exclusions d'artistes à l'invocation pour `/play_all`, exceptions persistantes par piste et gestion compacte via Discord. ✅
* Réduire ou exclure Dislikes et SuperDislikes selon les réglages. 🚫
* Tenir compte des utilisateurs présents dans le salon vocal. 👥
* Éviter les répétitions trop fréquentes. 🔁
* Mode découverte et mélange contrôlé. 🌠

## Phase 13 — Personnalité et Chaos Mode

* Messages et réactions légèrement espiègles. 🐾
* Personnalité configurable et désactivable. 🎭
* Événements surprises, votes et challenges musicaux. 🎲
* Mode DJ autonome. 🔥
* Chaos Mode sécurisé avec cooldowns et permissions. ⚠️
* Aucun comportement destructif ou incontrôlable sur la bibliothèque. 🔒

## Phase 14 — Durcissement production

* Health checks Docker. 🩺
* Reconnexion et récupération après perte de Lavalink ou Discord. 🔄
* Sauvegardes automatiques de la base et des configurations privées. 💾
* Logs structurés et rotation des journaux. 📜
* Métriques simples : mémoire, CPU, files, erreurs et lecteurs actifs. 📈
* Déploiement stable et redémarrage automatique sur Arcadia. 🏗️
* Documentation finale dans le repo projet et `arcadia-infra`. 🗂️

## Phase 15 — Weasel Web Control Center

### Phase 15.1 — API de contrôle

* Créer une API privée autour des services existants du bot. 🔌
* Exposer état du player, queue, bibliothèque, playlists, ratings, volumes et effets. 📡
* Ne jamais exposer Lavalink directement au navigateur. 🛡️
* Authentifier et autoriser chaque action sensible. 🔐

### Phase 15.2 — Connexion au portfolio

* Ajouter une zone privée au futur site personnel. 🌐
* Connexion avec le compte Discord. 🪪
* Autoriser uniquement les utilisateurs ou rôles choisis. ✅
* Session web sécurisée et bouton de déconnexion. 🚪

### Phase 15.3 — Dashboard temps réel

* Morceau actuel, progression, volume et effets. 🎶
* Contrôles play, pause, skip, back et stop. 🎛️
* Queue réorganisable par glisser-déposer. ↕️
* Mises à jour temps réel lorsque Discord ou un autre utilisateur agit. ⚡
* Affichage des personnes présentes dans le salon vocal si utile. 👥

### Phase 15.4 — Bibliothèque et playlists web

* Recherche et navigation dans toutes les musiques. 🔍
* Création et édition de playlists depuis le navigateur. 📚
* Modification des catégories, artistes et tags. 🏷️
* Gestion des volumes par piste et des ratings. 🎚️
* Import de nouveaux fichiers et déclenchement d’un nouveau scan. 📥
* Corbeille et confirmations avant toute suppression. 🗑️

### Phase 15.5 — Atelier audio web

* Création de versions ralenties, accélérées, pitchées ou bass boosted. 🧪
* Prévisualisation avant export. 🎧
* Travaux en arrière-plan avec progression visible. ⏳
* Enregistrement des créations dans un dossier dédié sur HDD. 💽
* Ajout automatique à la bibliothèque après validation. ➕

## Phase 16 — IA locale optionnelle

* Ollama pour les messages, résumés de goûts et suggestions. 🤖
* Aide à la création de playlists. 🧠
* Personnalité plus dynamique. 🎭
* L’IA reste facultative et ne doit jamais devenir nécessaire à la lecture musicale. 🛡️
