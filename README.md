# 🚀 PostFlow Backend API

Backend Django REST API pour PostFlow - L'assistant IA pour créer des posts LinkedIn engageants.

## 🌟 Fonctionnalités

- **Génération de posts IA** avec Claude Sonnet 4 (Vision API)
- **Analyse d'images** pour extraction de contexte
- **Génération de variantes** multiples avec recommandations
- **Authentification JWT** avec refresh tokens
- **LinkedIn OAuth** pour publication directe
- **Programmation de posts** avec APScheduler
- **Analytics** avec suivi des performances
- **Templates** personnalisables
- **Recherche d'images** (Pexels API)
- **Génération d'images IA** (Google Gemini)

## 🛠️ Technologies

- **Django 5.0** - Framework web
- **Django REST Framework** - API REST
- **PostgreSQL** - Base de données
- **Anthropic Claude API** - Génération de contenu IA
- **Google Gemini** - Génération d'images
- **LinkedIn API** - OAuth et publication
- **APScheduler** - Tâches planifiées
- **JWT** - Authentification

## 📦 Installation Locale

### Prérequis

- Python 3.10+
- PostgreSQL (ou SQLite pour dev)
- Clés API (Anthropic, LinkedIn, Pexels, Google AI)

### Étapes

1. **Cloner le repository**

```bash
git clone https://github.com/TokDar2410621/postflowBackend.git
cd postflowBackend
```

2. **Créer un environnement virtuel**

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. **Installer les dépendances**

```bash
pip install -r requirements.txt
```

4. **Configurer les variables d'environnement**

Copier `.env.example` vers `.env` et remplir les valeurs :

```bash
cp .env.example .env
```

Variables obligatoires :
- `SECRET_KEY` - Clé secrète Django
- `ANTHROPIC_API_KEY` - Clé API Claude
- `LINKEDIN_CLIENT_ID` - Client ID LinkedIn
- `LINKEDIN_CLIENT_SECRET` - Secret LinkedIn

5. **Appliquer les migrations**

```bash
python manage.py migrate
```

6. **Créer un superuser (optionnel)**

```bash
python manage.py createsuperuser
```

7. **Lancer le serveur**

```bash
python manage.py runserver
```

L'API sera accessible sur `http://localhost:8000/api/`

## 🌐 Déploiement sur Railway

### Configuration rapide

1. **Créer un nouveau projet sur [Railway](https://railway.app)**

2. **Connecter ce repository GitHub**

3. **Ajouter PostgreSQL**
   - Cliquer sur "+ New"
   - Sélectionner "Database" → "PostgreSQL"
   - Railway va automatiquement créer `DATABASE_URL`

4. **Configurer les variables d'environnement**

Ajouter dans Railway Variables :

```bash
DEBUG=False
SECRET_KEY=votre-secret-key-forte
USE_SQLITE=False
ALLOWED_HOSTS=votre-app.railway.app
CORS_ALLOWED_ORIGINS=https://votre-frontend.vercel.app
CSRF_TRUSTED_ORIGINS=https://votre-frontend.vercel.app
FRONTEND_URL=https://votre-frontend.vercel.app
ANTHROPIC_API_KEY=sk-ant-xxxxx
LINKEDIN_CLIENT_ID=xxxxx
LINKEDIN_CLIENT_SECRET=xxxxx
LINKEDIN_REDIRECT_URI=https://votre-app.railway.app/api/auth/linkedin/callback
PEXELS_API_KEY=xxxxx
GOOGLE_API_KEY=xxxxx
```

5. **Déployer**

Railway détectera automatiquement le `Procfile` et `railway.json` et lancera le déploiement.

## 📚 Documentation API

### Authentification

#### Register
```
POST /api/auth/register/
{
  "username": "user",
  "email": "user@example.com",
  "password": "password123"
}
```

#### Login
```
POST /api/auth/login/
{
  "username": "user",
  "password": "password123"
}
```

### Posts

#### Générer un post
```
POST /api/generate/
Content-Type: multipart/form-data

summary: "Votre résumé"
tone: "professionnel"
images: [files]
template_id: 1 (optionnel)
```

#### Générer des variantes
```
POST /api/generate/variants/
Content-Type: multipart/form-data

summary: "Votre résumé"
tone: "professionnel"
num_variants: 3
images: [files]
```

#### Lister les posts
```
GET /api/posts/
GET /api/posts/?tone=professionnel&date_range=7&search=keyword
```

### LinkedIn

#### Connecter LinkedIn
```
GET /api/auth/linkedin/
```

#### Publier sur LinkedIn
```
POST /api/linkedin/publish/
{
  "content": "Votre post",
  "images": [files]
}
```

#### Programmer un post
```
POST /api/scheduled/create/
{
  "content": "Votre post",
  "scheduled_time": "2024-12-31T12:00:00Z"
}
```

### Templates

#### Lister les templates
```
GET /api/templates/
```

#### Créer un template
```
POST /api/templates/create/
{
  "name": "Mon Template",
  "prompt_prefix": "Prefix",
  "prompt_suffix": "Suffix",
  "default_tone": "professionnel",
  "is_default": false
}
```

### Analytics

#### Récupérer les statistiques
```
GET /api/analytics/
GET /api/analytics/?tone=professionnel&date_range=30
```

#### Top posts
```
GET /api/analytics/top/?metric=engagement_rate&limit=10
```

## 🔐 Sécurité

- ✅ HTTPS forcé en production
- ✅ CSRF protection
- ✅ CORS configuré
- ✅ JWT avec refresh tokens
- ✅ Variables d'environnement sécurisées
- ✅ Rate limiting (à implémenter)

## 🧪 Tests

```bash
# Lancer les tests
python manage.py test

# Avec coverage
coverage run --source='.' manage.py test
coverage report
```

## 📊 Structure du Projet

```
backend/
├── api/                      # Application principale
│   ├── migrations/          # Migrations de base de données
│   ├── management/          # Commandes personnalisées
│   │   └── commands/
│   │       ├── publish_scheduled.py  # Publication programmée
│   │       └── update_stats.py       # Mise à jour analytics
│   ├── models.py           # Modèles de données
│   ├── views.py            # Génération de posts
│   ├── auth.py             # Authentification
│   ├── linkedin.py         # Intégration LinkedIn
│   ├── schedule.py         # Programmation
│   ├── templates.py        # Gestion templates
│   ├── analytics.py        # Statistiques
│   ├── images.py           # Pexels + Gemini
│   ├── serializers.py      # Sérialiseurs DRF
│   └── urls.py             # Routes API
├── config/                  # Configuration Django
│   ├── settings.py         # Settings
│   ├── urls.py             # URLs racine
│   └── wsgi.py             # WSGI
├── Procfile                # Configuration Railway
├── railway.json            # Build Railway
├── requirements.txt        # Dépendances Python
├── .env.example            # Exemple de configuration
└── manage.py               # CLI Django
```

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.

## 📝 License

MIT

## 🔗 Liens Utiles

- [Documentation Django](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [LinkedIn API](https://learn.microsoft.com/en-us/linkedin/)
- [Railway Docs](https://docs.railway.app/)

---

Développé avec ❤️ pour simplifier la création de contenu LinkedIn
