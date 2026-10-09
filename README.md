# Veille stages — Sales & Trading · Risk · Middle Office

Outil de veille qui détecte les offres de stage (sites carrière des banques, plateformes, LinkedIn, ajouts manuels),
élimine les doublons, notifie sur téléphone (ntfy) et alimente un dashboard de suivi de candidatures.

- **Installation** : voir [GUIDE.md](GUIDE.md)
- **Critères et sources** : [config.yaml](config.yaml)
- **Moteur** : `engine/` (Python, lancé par GitHub Actions toutes les 30 min — `.github/workflows/veille.yml`)
- **Base de données** : `supabase/schema.sql`
- **Dashboard** : `docs/index.html` (publié par GitHub Pages ; `docs/index.html?demo=1` pour la démo)
- **Tests** : `pip install pytest && python -m pytest -q`
