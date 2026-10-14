# qa-agent-evals

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[RU](README.md) · [EN](README.en.md) · [中文](README.zh.md) · [Español](README.es.md) · **Français**

Un plugin Claude Code pour les tests d'acceptation de systèmes LLM par des sous-agents jouant des rôles. Vous désignez le système à tester (SUT). Le plugin établit son profil, génère des cartes de scénarios de cinq types, les exécute via un adaptateur isolé, rend des verdicts avec un juge tournant sur un autre modèle, et assemble un rapport avec taux de réussite et matrice de couverture.

Trois choses le distinguent de l'exécution manuelle de prompts : la réponse attendue de chaque carte est consignée avant la course (l'oracle), une couche machine vérifie les faits par grep avant que le juge ne voie la réponse, et le juge lui-même tourne sur un autre modèle et se calibre sur un échantillon de contrôle aux verdicts connus. Les confirmations humaines après acceptation font grossir cet échantillon. L'environnement est isolé des skills et du MCP du propriétaire. Les verdicts sont asymétriques : FAIL prouve un défaut, GOT signifie seulement « non réfuté ».

![Comment ça marche : le plugin étudie le système, écrit des tâches, un acteur joue l'utilisateur, le plugin étranger tourne derrière une vitre, un juge note les réponses, le rapport montre le résultat](assets/concept.en.gif)

*Un projet perso : comprendre les evals d'acceptation en construisant un outil fonctionnel et en l'exécutant sur lui-même.*

## Fonctionnement

```
[A : analyser le SUT] → [B : adaptateur + test de fumée] → [C : cartes] → [D : courses × N répétitions] → [E : rapport]
```

- **L'analyste** (étape A) lit le SUT et construit un profil : registre des fonctionnalités, carte des risques, surface d'attaque, points d'ambiguïté, options d'adaptateur.
- **Les cartes** (étape C) existent en cinq types : obvious (chemin nominal), convoluted (ambiguïté multi-tours), critical (zones de dommage), adversarial (une attaque par carte), out-of-scope (le SUT admet-il ce qu'il ne sait pas ?). Format : YAML avec un persona, une instruction, un oracle (faits requis et interdits + attente en prose) et un budget.
- **L'acteur role-user** joue le persona contre le SUT via l'adaptateur. Pour les systèmes CLI, c'est une session headless isolée : répertoire de travail neutre, sans accès aux skills ni au MCP du propriétaire. Les SUT web passent par un adaptateur navigateur à surface Playwright, voir `knowledge/adapters.md`. Les répétitions sont pilotées par `scripts/run-cards.sh`.
- **La couche machine** (`scripts/check-facts.py`) tourne avant le juge : elle grepe les marqueurs de l'oracle dans les transcriptions et dans les fichiers que le SUT a lui-même écrits. Ce que la machine prouve, le juge ne le re-juge pas, et une auto-contradiction (verdict positif sur une violation prouvée) déclenche un re-jugement automatique.
- **Le juge** tourne sur un autre modèle et travaille en deux temps : il note d'abord la réponse contre l'oracle sans connaître l'intention du scénario, puis supervise l'acteur. Avant chaque course d'acceptation, il est calibré sur un échantillon de contrôle : cas écrits à la main, cas issus de jeux de données ouverts (TruthfulQA, Apache 2.0 ; attaques HH-RLHF, MIT) et une section vivante alimentée par le retour humain.
- **Boucle de retour (Growing-Golden)** : après une course, le propriétaire confirme ou corrige les verdicts, via une page d'annotation cliquable ou du texte direct dans le chat. Seul un verdict humain devient un étalon ; celui du juge, jamais.
- **Rapport** : verdicts et votes des répétitions, matrice de couverture fonctionnalité par type, constats avec priorités, analyse des causes, limites de la course et son coût en jetons et en dollars (côté SUT et côté juge mesurés séparément).

La carte complète (isolation, hiérarchie des contextes, matrice de responsabilités) est dans [docs/architecture.md](docs/architecture.md). Version interactive : [docs/architecture.html](docs/architecture.html), chaque nœud montre quel fichier ou paramètre l'influence. Ouvrez le fichier localement dans un navigateur.

## Isolation d'exécution (v0.5.0)

Le plugin testé s'exécute à l'un de deux niveaux d'isolation, consigné dans le rapport de chaque course :

- **host** (par défaut) : sans Docker ni dépendances supplémentaires. Isolation de l'environnement comme avant : liste blanche de variables, MCP vide, répertoire de travail neutre, détecteur de manipulation. Il n'y a pas de barrière système de fichiers ni réseau, et le rapport marque ce niveau honnêtement « pas un bac à sable ». Suffisant pour des plugins publics de sources connues.
- **docker** (pour le contenu non fiable) : un conteneur ne montant que le répertoire de travail et une copie du plugin, racine en lecture seule, utilisateur non root, limites de ressources ; la seule sortie est un conteneur proxy interne vers la passerelle LLM. Si Docker est indisponible, la course refuse de démarrer (fail-closed), sans repli silencieux vers le mode non sûr.

Vérifié en courses réelles contre notre propre examples/evil-plugin (un plugin qui ne refuse jamais) : sous docker, lire un secret de l'hôte, l'accès réseau, l'écriture hors de l'espace de travail et la falsification de preuves ont tous été bloqués ; sur host, les mêmes attaques sont consignées honnêtement comme risques du niveau. Constat annexe : les outils côté serveur de la passerelle (lecture web) introduisent du contenu dans le réseau fermé, ils sont donc interdits en mode docker.

Durci en v0.5.1 : les sources du plugin sont montées en lecture seule avec une sonde d'écriture au démarrage (si l'écriture est possible, la course est refusée) ; la vraie clé de la passerelle ne vit que dans le conteneur proxy, le processus testé reçoit un fantôme ; le proxy n'accepte que les chemins de l'API LLM et limite les requêtes. Une suite de sécurité automatisée (`python scripts/sec-checks.py docker`) lance les six vérifications en une commande et en CI, au vert sur Windows comme sur le runner Linux (runs/2026-10-13-sec/). Durcissement final en v0.5.2 : la sonde d'écriture repose sur des preuves (succès seulement en cas de blocage confirmé), la normalisation des chemins du proxy ferme les traversées /../, limites de fréquence/volume/durée ajoutées, et le conteneur proxy lui-même tourne non root sans capabilities ; SEC-06 est scindé en une attaque de l'oracle et une falsification de verdict (toutes deux vérifiées par hachage) ; un test d'intégration lance le pipeline réel avec un vrai Claude Code (runs/2026-10-13-secint/).

## Démarrage rapide

Prérequis : Claude Code, bash, python3. Sous Windows, utilisez Git Bash ou WSL.

Installez le plugin (avec `--plugin-dir <chemin>` au lancement de la session ou via un marketplace), ouvrez une session dans le répertoire du système testé et écrivez :

```
lance les tests d'acceptation sur <chemin du SUT>
```

Le pipeline parcourt les étapes A-E tout seul et s'arrête exactement une fois, avant la revue des cartes : il vous les montre et attend votre approbation.

## Contenu

```
.claude-plugin/plugin.json    manifeste
skills/acceptance-test/       le pipeline en cinq étapes (orchestrateur)
agents/analyst.md             profileur du SUT
agents/role-user.md           acteur jouant des rôles
agents/judge.md               juge en deux temps (lié à un autre modèle)
knowledge/taxonomy.md         5 types de cartes, motifs, YAML de référence
knowledge/adapters.md         adaptateurs CLI et navigateur (Playwright), isolation d'environnement
knowledge/oracle.md           oracles, échelle des verdicts, modèles de rapport
knowledge/sandbox.md          niveaux host/docker : frontières, proxy, vérifications
knowledge/golden-live.md      section vivante de l'échantillon de contrôle (cas golden issus du retour)
scripts/run-cards.sh          lanceur CLI de cartes à un tour avec répétitions
scripts/run-integrity.sh      détecteur de manipulation du répertoire de course
scripts/parse-events.py       analyseur events.jsonl : réponses, provenance, diagnostics
scripts/check-facts.py        vérificateur de faits machine (transcriptions + fichiers écrits par le SUT)
scripts/judge-batch.py        lot du juge + re-jugement automatique des auto-contradictions
scripts/judge-control.py      échantillon de contrôle du juge (ensembles golden)
scripts/collect-feedback.py   retour humain : page d'annotation + candidats golden
scripts/build-index.py        index de course lisible par machine (index.jsonl)
scripts/cost-report.py        coût et durée de la course
scripts/judge-metrics.py      métriques d'accord du juge sur corpus
scripts/diff-runs.py          comparaison de deux courses (une vue, pas un critère)
scripts/make-golden-*.py      convertisseurs depuis les jeux de données ouverts (TruthfulQA, HH-RLHF)
scripts/sandbox.py            moteur des niveaux d'isolation pour les sessions du SUT
scripts/sandbox-proxy.py      proxy inverse vers la passerelle LLM pour le niveau docker
scripts/sec-checks.py         suite de sécurité de six vérifications de l'isolation docker
scripts/sec-integration.py    test d'intégration : pipeline réel dans le bac à sable docker
scripts/Dockerfile.sandbox    image du conteneur d'isolation
examples/evil-plugin          plugin cible pour vérifier l'isolation
tests/                        tests unitaires et réels du pipeline
docs/spec.md                  spécification
docs/plan.md                  plan d'implémentation
docs/architecture.md          fonctionnement : pipeline, isolation, responsabilités
docs/research-2026-10-09.md   revue des frameworks sources
docs/research-2026-10-10-rsi.md  notes sur les sources d'auto-amélioration
docs/research-2026-10-11-kaggle-golden.md  jeux de données ouverts pour les cas golden
docs/reviews/                 revues externes de la spec et revues de code
runs/                         artefacts des auto-acceptations et des courses tierces (logs bruts et données sensibles retirés)
```

## Statut

v0.5.2. Le pipeline a grandi sur des systèmes tiers et sur lui-même.

D'abord quatre auto-acceptations (v1-v4, rapports dans [runs/](runs/2026-10-08-qa-agent-evals-selftest/report.md)) : v1 a trouvé 3 vrais défauts (limites du périmètre, promettre le non-implémenté, contrôle d'approbation) ; chaque course suivante vérifiait les corrections précédentes et en cherchait de nouvelles.

Puis des systèmes tiers : un skill d'édition de prose (deux courses avec comparaison de versions, [runs/](runs/2026-10-11-stop-slop-r2/report.md)), un générateur de diapositives avec une injection par le contenu, un skill d'anglais technique, le classique 2048 via l'adaptateur navigateur (un SUT déterministe sans LLM) et des systèmes d'un périmètre fermé (détails non divulgués). Ces courses ont fait grandir v0.3-v0.4 : la couche machine de faits (fuites attrapées par grep, y compris dans des fichiers écrits par le SUT), l'échantillon de contrôle du juge issu de jeux de données ouverts (TruthfulQA 45/45 ; attaques HH-RLHF), la boucle de retour Growing-Golden avec page d'annotation, le re-jugement automatique des auto-contradictions et une économie mesurée : une acceptation typique coûte $0.6-1.8 côté SUT plus environ $0.4 par appel du juge, car un appel CLI du juge traîne ~75K jetons de préambule de session.

v0.5.0 a ajouté l'isolation d'exécution (host/docker) avec preuves réelles contre evil-plugin, et les pannes d'infrastructure sont désormais séparées des défauts du plugin (statuts BLOCKED/ERROR). v0.5.1 et v0.5.2 l'ont durcie : la clé de la passerelle ne vit que dans le conteneur proxy, les sources sont montées en lecture seule avec une sonde d'écriture fondée sur des preuves, la normalisation des chemins du proxy ferme les traversées /../, limites de fréquence/volume/durée ajoutées, et le proxy tourne non root sans capabilities. La suite de sécurité (`python scripts/sec-checks.py docker`) est au vert sur Windows et sur le runner CI Linux (runs/2026-10-13-sec/) ; un test d'intégration lance le pipeline réel avec un vrai Claude Code (runs/2026-10-13-secint/). Au total : 47 tests unitaires et 9 tests réels.

Ne fonctionne pas encore : seuls les adaptateurs CLI et navigateur sont implémentés ; l'isolation coupe l'invocation des skills mais pas la connaissance de leur existence ; le juge est câblé à la main (`--model` explicite ou choix du propriétaire à l'étape B), car le champ `model` de l'agent ne fonctionne pas dans tous les environnements.

Spec : [docs/spec.md](docs/spec.md), plan : [docs/plan.md](docs/plan.md).
