# Guide d'installation — Veille stages

Durée totale : **45 à 60 minutes, une seule fois**. Aucune ligne de commande : tout se fait dans le navigateur.
Coût : **0 €** (ntfy, Supabase et GitHub en version gratuite).

Tu vas installer 3 briques :

| Brique | Rôle | Où |
|---|---|---|
| **ntfy** | t'envoie une notification sur ton téléphone à chaque nouvelle offre | appli mobile |
| **Supabase** | la base de données : offres, doublons, statuts de candidature | supabase.com |
| **GitHub** | fait tourner la veille toutes les 30 min et héberge le dashboard | github.com |

> Garde ce guide ouvert à côté, et note au fur et à mesure les 5 valeurs demandées dans un fichier texte temporaire
> (que tu supprimeras à la fin) : **sujet ntfy, Project URL, Publishable key, Secret key, mot de passe du dashboard**.

---

## Étape 1 — Notifications ntfy (2 min)

1. Installe l'application **ntfy** sur ton téléphone (App Store ou Google Play, éditeur « Philipp Heckel »).
2. Ouvre-la, touche **+** (s'abonner à un sujet).
3. Nom du sujet : **`veille-stg-w1srjvqr72rlus`**
   (généré aléatoirement pour toi : ne le partage avec personne, il sert de mot de passe).
4. Laisse le serveur par défaut (ntfy.sh) et valide.
5. Sur iPhone, accepte les notifications quand l'appli le demande.

Test : ouvre `https://ntfy.sh/veille-stg-w1srjvqr72rlus` dans un navigateur, écris « test » dans le champ en bas et envoie : ton téléphone doit sonner.

---

## Étape 2 — Base de données Supabase (15 min)

### 2.1 Créer le projet
1. Va sur **supabase.com** → **Start your project** → connecte-toi avec ton compte GitHub (crée d'abord le compte GitHub de l'étape 3.1 si tu n'en as pas) ou avec ton e-mail.
2. **New project** :
   - *Name* : `veille-stages`
   - *Database password* : clique sur **Generate a password** (tu n'en auras pas besoin ensuite)
   - *Region* : **West EU (Paris)**
   - Plan : **Free** → **Create new project**. Attends 1 à 2 minutes.

### 2.2 Créer les tables
1. Menu de gauche → **SQL Editor** → **New query**.
2. Ouvre le fichier `supabase/schema.sql` du dossier du projet, copie **tout** son contenu, colle-le dans l'éditeur.
3. Clique sur **Run**. Le message doit être « Success. No rows returned ».

### 2.3 Créer ton compte pour le dashboard
1. Menu de gauche → **Authentication** → **Users** → **Add user** → **Create new user**.
2. Ton e-mail + un mot de passe solide, coche **Auto Confirm User** → **Create user**.
3. Toujours dans **Authentication** → **Sign In / Providers** (ou **Settings**) : **désactive « Allow new users to sign up »** puis **Save**.
   Ainsi, personne d'autre ne peut se créer un compte sur ta base.

### 2.4 Récupérer les clés
1. Clique sur **Connect** en haut de l'écran (ou **Project Settings → Data API**) : copie la **Project URL**
   (de la forme `https://abcdefgh.supabase.co`).
2. **Project Settings → API Keys** :
   - copie la **Publishable key** (`sb_publishable_…`) : elle ira dans le dashboard ;
   - copie la **Secret key** (`sb_secret_…`, bouton « Reveal ») : elle ira **uniquement** dans les Secrets GitHub.
     ⚠️ Ne la colle jamais dans un fichier du projet : elle donne un accès total à la base.

---

## Étape 3 — GitHub : la veille automatique et le dashboard (25 min)

### 3.1 Compte
Crée un compte sur **github.com** si besoin. (Le pack GitHub Student n'est pas nécessaire avec cette configuration.)

### 3.2 Créer le dépôt
1. En haut à droite **+** → **New repository**.
2. *Repository name* : `veille-stages` · Visibilité : **Public** · ne coche rien d'autre → **Create repository**.

> **Pourquoi public ?** Un dépôt public a des minutes d'exécution illimitées et un hébergement de page gratuit.
> Il ne contient **que du code et ta liste de banques** : tes candidatures, tes notes et ton CV restent dans Supabase
> ou dans les Secrets GitHub, jamais dans le code. Si tu préfères un dépôt privé, voir « Questions fréquentes ».

### 3.3 Envoyer les fichiers
1. Sur la page du dépôt vide, clique sur le lien **uploading an existing file**.
2. Dans le Finder, ouvre le dossier `veille-stages` (dans `Quant_Projects`).
   **Important : appuie sur `Cmd + Maj + .`** pour afficher les fichiers cachés : le dossier **`.github`** doit apparaître.
3. Sélectionne **tout le contenu** du dossier (`Cmd + A`, y compris `.github`) et glisse-le dans la page GitHub.
4. Attends la fin du chargement → **Commit changes**.
5. Vérifie que tu vois bien les dossiers `.github`, `docs`, `engine`, `supabase` et les fichiers `config.yaml`, `requirements.txt`.

> Si le dossier `.github` n'a pas été envoyé : **Add file → Create new file**, nom
> `.github/workflows/veille.yml`, colle le contenu du fichier `veille.yml`, puis **Commit changes**.

### 3.4 Ajouter les secrets
**Settings** (onglet du dépôt) → **Secrets and variables** → **Actions** → **New repository secret**, trois fois :

| Name | Secret |
|---|---|
| `SUPABASE_URL` | ta Project URL |
| `SUPABASE_SERVICE_KEY` | ta **Secret key** `sb_secret_…` |
| `NTFY_TOPIC` | `veille-stg-w1srjvqr72rlus` |

### 3.5 Relier le dashboard à la base
1. Dans le dépôt, ouvre `docs/config.js` → icône **crayon** (Edit).
2. Remplis les deux valeurs entre guillemets :
   ```js
   supabaseUrl: "https://abcdefgh.supabase.co",
   supabaseAnonKey: "sb_publishable_xxxxxxxx",
   ```
3. **Commit changes**.

### 3.6 Mettre le dashboard en ligne
1. **Settings** → **Pages**.
2. *Source* : **Deploy from a branch** · *Branch* : **main** et dossier **/docs** → **Save**.
3. Après 1 à 2 minutes, l'adresse s'affiche en haut : `https://TON-PSEUDO.github.io/veille-stages/`.
4. (Facultatif) Ouvre `config.yaml` → crayon → colle cette adresse dans `url_dashboard: ""` → Commit.
   Elle servira de lien dans les notifications récapitulatives.

### 3.7 Premier lancement
1. Onglet **Actions**. Si GitHub demande d'activer les workflows, clique sur **I understand my workflows, go ahead and enable them**.
2. À gauche **Veille stages** → bouton **Run workflow** :
   - coche **Essai à blanc** → **Run workflow**.
3. Clique sur l'exécution qui apparaît (rond jaune puis vert, 3 à 6 min) → **veille** → **Lancer la veille** :
   tu vois chaque source avec `[OK ]` ou `[ERR]`, puis la liste des offres pertinentes trouvées. Rien n'est enregistré à ce stade.
4. Si le résultat te convient, relance **Run workflow** **sans** cocher « Essai à blanc ».
   Les offres arrivent dans le dashboard et tu reçois les premières notifications
   (au premier passage, il peut y en avoir beaucoup : au-delà de 8, tu reçois un récapitulatif).
5. Ensuite, la veille tourne **toute seule toutes les 30 minutes**, même ton ordinateur éteint.

---

## Étape 4 — Ouvrir le dashboard (2 min)

- **Sur ton PC** : ouvre l'adresse GitHub Pages et connecte-toi avec l'e-mail et le mot de passe de l'étape 2.3. Mets-la en favori.
- **Sur ton iPhone** : ouvre l'adresse dans Safari → bouton **Partager** → **Sur l'écran d'accueil**.
  Sur Android : Chrome → menu ⋮ → **Ajouter à l'écran d'accueil**.

Tu peux supprimer le fichier texte temporaire où tu avais noté tes clés.

---

## Utilisation au quotidien

**Onglet Offres** : une ligne par offre (première apparition).
- Clique sur une ligne pour voir le détail : description, autres apparitions, historique, notes, date limite.
- **Statut** : change-le directement dans le tableau. Il est **automatiquement appliqué aux doublons** de l'offre.
- Badges : **Nouveau** (depuis ta dernière visite), **Repost** (offre réapparue après une absence, souvent un désistement),
  **Mise à jour** (contenu modifié de façon importante), **Expirée** (l'offre n'est plus en ligne).
- **Début · période** : 🟢 OK (le stage tient entre mai et décembre 2027), 🟠 À vérifier (date non précisée), 🔴 Incompatible.
- Filtres combinables et tri par colonne ; **CSV** exporte la vue filtrée.
- Case **Écartées** : montre les offres collectées mais rejetées par tes critères, avec la raison. Utile pour vérifier qu'aucune bonne offre n'est filtrée par erreur.

**Onglet Doublons** : les autres apparitions (LinkedIn, re-publications…), avec l'offre principale correspondante et la raison.

**Onglet Statistiques** : offres détectées et candidatures par semaine, entonnoir, taux de réponse, délai moyen de réponse, répartition par poste, desk, ville et entreprise.
Pour des statistiques justes, pense à passer le statut à **Postulée** quand tu envoies une candidature,
puis **Test en ligne / Entretien / Refusée / Offre reçue** à chaque réponse.

**Onglet Sources** : état de chaque source au dernier passage. Une source en erreur n'empêche pas les autres de fonctionner.

**Bouton Ajouter** : pour un **post LinkedIn d'un stagiaire** ou une offre vue ailleurs. Colle le texte du post et le lien :
au passage suivant (30 min max), la veille en extrait le poste, le desk, la date de début, la dédoublonne et la range dans le tableau.

---

## Modifier tes critères (fichier `config.yaml`)

Sur GitHub, ouvre `config.yaml` → crayon → modifie → **Commit changes**. Les changements s'appliquent au passage suivant.

- **Villes, postes, période** : section `recherche`.
- **Ajouter une entreprise** : ajoute une ligne dans `entreprises` (même format que les autres). Elle sera suivie via LinkedIn.
- **Ajouter un site Workday** (adresse en `….myworkdayjobs.com/…`) : ajoute une ligne dans `sources > workday > sites`.
- **Fréquence** : `toutes_les_minutes` par source. Pour tout mettre en pause : onglet **Actions** → **Veille stages** → **⋯** → **Disable workflow**.
- Respecte bien l'indentation (2 espaces). Si tu fais une erreur, l'exécution suivante échoue avec un message clair dans l'onglet Actions : il suffit de corriger le fichier.

---

## Activer l'analyse de compatibilité avec ton CV (plus tard)

1. Crée un compte sur **console.anthropic.com**, ajoute un petit crédit (5 $) et fixe une **limite de dépense mensuelle** (Settings → Limits).
2. Crée une clé API (**API Keys → Create Key**).
3. Dans GitHub → Settings → Secrets → Actions, ajoute :
   - `ANTHROPIC_API_KEY` : la clé ;
   - `CV_TEXT` : le texte de ton CV (copie-colle depuis ton PDF).
4. Dans `config.yaml`, section `analyse_ia`, passe `actif: false` à `actif: true`.

Au passage suivant, chaque offre pertinente reçoit un score de compatibilité, avec tes points forts, les écarts et les mots-clés manquants
(visibles dans le détail de l'offre). Une colonne **Match** et un filtre « Match ≥ x % » apparaissent dans le dashboard.
Les offres déjà en base sont analysées progressivement (25 par passage).

---

## Questions fréquentes

**Une source est en erreur dans l'onglet Sources.** Les sites carrière changent parfois leur structure ou bloquent temporairement
les robots. Si l'erreur persiste plusieurs jours, la source est à corriger : les offres de cette banque continuent en général
d'arriver par LinkedIn en attendant.

**Je reçois trop (ou pas assez) de notifications.** Dans `config.yaml` → `notifications` :
`notifier_periode_incompatible` et `max_notifications_par_passage`. Pour ne plus être notifié la nuit, active le mode
« Ne pas déranger » de ton téléphone pour l'appli ntfy.

**Je veux un dépôt privé.** C'est possible, mais un dépôt privé gratuit est limité à 2 000 minutes d'exécution par mois
(3 000 avec le pack Student) et la page GitHub Pages privée demande le pack Student. Dans ce cas, passe la fréquence à
1 heure dans `.github/workflows/veille.yml` (ligne `cron: "7 * * * *"`) et `toutes_les_minutes: 120` pour LinkedIn.

**GitHub a désactivé la veille ?** GitHub suspend les tâches planifiées d'un dépôt public inactif depuis 60 jours.
Le workflow se réactive lui-même à chaque passage, mais si cela arrive : onglet **Actions** → **Enable workflow**.

**Combien ça coûte ?** Rien. Seule l'analyse IA (optionnelle) est payante, de l'ordre de quelques euros par mois au maximum.
