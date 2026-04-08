"""
Seed the database with demo accounts and content.
Creates realistic profiles with generated posts, published posts with engagement stats.
Safe to run multiple times (idempotent).
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from api.models import UserProfile, Subscription, GeneratedPost, PublishedPost, ScheduledPost


DEMO_PROFILES = [
    {
        'username': 'demo_sarah_coach',
        'first_name': 'Sarah',
        'last_name': 'Morel',
        'role': 'Coach en leadership',
        'industry': 'Coaching / Développement personnel',
        'expertise': 'Leadership, gestion d\'équipe, prise de parole en public',
        'target_audience': 'Managers et cadres en transition',
        'bio': 'J\'accompagne les leaders à révéler leur potentiel. +500 personnes coachées.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_marc_dev',
        'first_name': 'Marc',
        'last_name': 'Dubois',
        'role': 'Développeur Fullstack',
        'industry': 'Tech / SaaS',
        'expertise': 'React, Node.js, Architecture logicielle, DevOps',
        'target_audience': 'Développeurs et CTOs de startups',
        'bio': '10 ans de dev. Je partage ce que j\'aurais aimé savoir au début.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_julie_marketing',
        'first_name': 'Julie',
        'last_name': 'Petit',
        'role': 'Directrice Marketing',
        'industry': 'Marketing Digital',
        'expertise': 'Growth marketing, SEO, Content strategy, Social media',
        'target_audience': 'Marketeurs et fondateurs de startups',
        'bio': 'CMO @TechStartup. J\'ai fait passer notre MRR de 0 à 200K en 18 mois.',
        'platform_focus': 'instagram',
    },
    {
        'username': 'demo_alex_recruiter',
        'first_name': 'Alexandre',
        'last_name': 'Martin',
        'role': 'Talent Acquisition Manager',
        'industry': 'Recrutement Tech',
        'expertise': 'Sourcing, employer branding, entretiens structurés',
        'target_audience': 'Candidats tech et RH',
        'bio': '+300 recrutements tech. Je démystifie le process de recrutement.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_nadia_design',
        'first_name': 'Nadia',
        'last_name': 'Ben Ali',
        'role': 'Designer Freelance',
        'industry': 'Design UX/UI',
        'expertise': 'Design system, UX research, Figma, Branding',
        'target_audience': 'Startups et PME qui veulent un produit beau et fonctionnel',
        'bio': 'Freelance depuis 5 ans. Design is not how it looks, it\'s how it works.',
        'platform_focus': 'instagram',
    },
    {
        'username': 'demo_thomas_ceo',
        'first_name': 'Thomas',
        'last_name': 'Laurent',
        'role': 'CEO & Co-founder',
        'industry': 'Fintech',
        'expertise': 'Levée de fonds, product-market fit, scaling',
        'target_audience': 'Entrepreneurs et investisseurs',
        'bio': 'Co-fondateur @PayFlow. Série A bouclée. Je partage les coulisses.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_camille_rh',
        'first_name': 'Camille',
        'last_name': 'Rousseau',
        'role': 'DRH',
        'industry': 'Ressources Humaines',
        'expertise': 'Culture d\'entreprise, remote work, bien-être au travail',
        'target_audience': 'RH et managers',
        'bio': 'DRH chez une scale-up de 200 personnes. Le remote, c\'est mon quotidien.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_youssef_data',
        'first_name': 'Youssef',
        'last_name': 'Amrani',
        'role': 'Data Scientist',
        'industry': 'Intelligence Artificielle',
        'expertise': 'Machine Learning, NLP, Python, MLOps',
        'target_audience': 'Data scientists et décideurs tech',
        'bio': 'Senior DS @BigTech. Je vulgarise l\'IA pour que tout le monde comprenne.',
        'platform_focus': 'x',
    },
    {
        'username': 'demo_emma_content',
        'first_name': 'Emma',
        'last_name': 'Garcia',
        'role': 'Content Manager',
        'industry': 'E-commerce',
        'expertise': 'Content strategy, copywriting, email marketing, social media',
        'target_audience': 'E-commerçants et créateurs de contenu',
        'bio': 'Je transforme des marques invisibles en marques inoubliables.',
        'platform_focus': 'facebook',
    },
    {
        'username': 'demo_lucas_sales',
        'first_name': 'Lucas',
        'last_name': 'Bernard',
        'role': 'Sales Manager',
        'industry': 'SaaS B2B',
        'expertise': 'Social selling, closing, pipe management, outbound',
        'target_audience': 'Sales et business developers',
        'bio': 'De 0 à 2M€ ARR en solo. Le social selling a tout changé.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_ines_consultant',
        'first_name': 'Inès',
        'last_name': 'Karim',
        'role': 'Consultante en stratégie',
        'industry': 'Conseil',
        'expertise': 'Transformation digitale, stratégie d\'entreprise, innovation',
        'target_audience': 'Dirigeants et cadres de grandes entreprises',
        'bio': 'Ex-McKinsey. J\'aide les entreprises à se réinventer.',
        'platform_focus': 'linkedin',
    },
    {
        'username': 'demo_paul_trainer',
        'first_name': 'Paul',
        'last_name': 'Lefevre',
        'role': 'Formateur & Conférencier',
        'industry': 'Formation professionnelle',
        'expertise': 'Prise de parole, storytelling, formation de formateurs',
        'target_audience': 'Professionnels qui veulent mieux communiquer',
        'bio': '+100 conférences. Je forme ceux qui forment.',
        'platform_focus': 'facebook',
    },
]

DEMO_POSTS = {
    'linkedin': [
        {
            'summary': 'Les erreurs de management',
            'content': """J'ai viré mon meilleur développeur. Pire décision de ma carrière.

Il était brillant. Rapide. Efficace.

Mais il ne "fittait" pas avec l'équipe.

Alors je l'ai laissé partir.

6 mois plus tard, j'ai compris :

→ Le problème, c'était pas lui
→ Le problème, c'était moi
→ Je n'avais jamais défini ce que "fitter avec l'équipe" voulait dire

Aujourd'hui, avant de recruter, je me pose 3 questions :
1. Est-ce que je recrute pour des compétences ou pour du confort ?
2. Est-ce que la diversité d'opinions est bienvenue ?
3. Est-ce que "culture fit" = "pense comme moi" ?

Le meilleur recrutement que j'ai fait ensuite ? Quelqu'un qui me contredisait à chaque réunion.

Et devinez quoi ? Nos résultats ont explosé.

#management #recrutement #leadership""",
            'tone': 'storytelling',
            'views': 12400, 'likes': 342, 'comments': 87, 'shares': 45,
        },
        {
            'summary': 'Le cold outreach est mort',
            'content': """Arrêtez le cold outreach. Sérieusement.

J'ai envoyé 2000 emails en 3 mois.
Résultat : 3 rendez-vous. 0 client.

Puis j'ai changé de stratégie :
→ 1 post LinkedIn par jour pendant 90 jours
→ 0 message de prospection

Résultat au bout de 90 jours :
• 47 demandes de démo entrantes
• 12 clients signés
• 180K€ de pipe

La différence ? Les gens achètent à ceux qu'ils connaissent.

Publier du contenu, c'est pas du "personal branding".
C'est la meilleure stratégie commerciale qui existe.

Qui d'autre a fait cette transition ?

#socialselling #linkedin #b2b""",
            'tone': 'professionnel',
            'views': 8900, 'likes': 567, 'comments': 124, 'shares': 67,
        },
        {
            'summary': 'Freelance et syndrome de l\'imposteur',
            'content': """"Tu factures combien de l'heure ?"

Quand on m'a posé cette question pour la première fois en freelance, j'ai répondu 35€.

Je valais au minimum 80€.

Pourquoi j'ai dit 35€ ?

Le syndrome de l'imposteur.

Cette petite voix qui dit :
- "T'as pas assez d'expérience"
- "Ils vont trouver quelqu'un de mieux"
- "C'est déjà bien qu'ils te paient"

Voici ce que j'ai appris en 5 ans de freelance :

1. Ton prix = ta confiance en toi
2. Personne ne te donnera la permission de facturer plus
3. Les clients qui négocient ton prix sont rarement les meilleurs

Aujourd'hui je facture 3x ce premier tarif.
Et mes clients sont meilleurs.

Le prix n'est pas un chiffre. C'est un message.

#freelance #pricing #entrepreneuriat""",
            'tone': 'inspirant',
            'views': 15200, 'likes': 890, 'comments': 156, 'shares': 98,
        },
        {
            'summary': 'L\'IA va-t-elle remplacer les développeurs ?',
            'content': """L'IA ne va pas remplacer les développeurs.

Mais les développeurs qui utilisent l'IA vont remplacer ceux qui ne l'utilisent pas.

Voici mon workflow quotidien depuis 6 mois :

→ Claude pour le code boilerplate : -60% de temps
→ Copilot pour les tests : -40% de temps
→ ChatGPT pour la documentation : -70% de temps

Est-ce que je code moins ? Non.
Je code MIEUX. Plus vite. Avec moins de bugs.

Le temps gagné, je le passe sur :
• L'architecture
• La revue de code
• Le mentorat de juniors

L'IA est un multiplicateur, pas un remplaçant.

La vraie question n'est pas "l'IA va-t-elle me remplacer ?"
C'est "est-ce que j'apprends à l'utiliser ?"

#ia #developpement #tech""",
            'tone': 'educatif',
            'views': 21000, 'likes': 1200, 'comments': 234, 'shares': 156,
        },
        {
            'summary': 'Recruter sans CV',
            'content': """On a supprimé les CV de notre process de recrutement.

Les résultats 6 mois après :

✅ Diversité des profils : +40%
✅ Rétention à 6 mois : 92% (vs 71% avant)
✅ Temps de recrutement : -30%

Comment on fait ?

1. Un cas pratique anonymisé (pas de nom, pas de photo, pas d'école)
2. Un entretien structuré avec scorecard
3. Une demi-journée d'immersion dans l'équipe

Le CV, c'est un filtre à biais.
L'école, c'est un proxy de classe sociale.
L'expérience, c'est un chiffre qui ne dit rien sur le potentiel.

Les meilleurs recrutements qu'on a fait ?
Des reconvertis. Des autodidactes. Des profils atypiques.

Le talent n'a pas de template.

#recrutement #diversité #rh""",
            'tone': 'professionnel',
            'views': 9800, 'likes': 456, 'comments': 98, 'shares': 54,
        },
    ],
    'facebook': [
        {
            'summary': 'Storytelling personnel',
            'content': """Il y a 3 ans, j'étais au RSA.

Aujourd'hui je vis de ma passion.

Non, je n'ai pas trouvé une formule magique.
Non, je n'ai pas eu de coup de chance.

J'ai juste fait 3 choses :

1. J'ai arrêté d'écouter ceux qui disaient que c'était impossible
2. J'ai publié CHAQUE JOUR pendant 1 an (même quand personne ne lisait)
3. J'ai aidé les autres GRATUITEMENT

Le retour sur investissement est venu 8 mois plus tard.
Et il a tout changé.

Si vous lisez ça et que vous hésitez à vous lancer :
Lancez-vous. Le pire scénario, c'est de rester où vous êtes.

Qui est dans cette situation en ce moment ? 👇""",
            'tone': 'inspirant',
            'views': 5600, 'likes': 234, 'comments': 89, 'shares': 34,
        },
        {
            'summary': 'Sondage communauté',
            'content': """Petit sondage du dimanche 😄

Quel est votre plus gros frein pour publier sur les réseaux ?

1. 😰 Le syndrome de l'imposteur
2. ⏰ Le manque de temps
3. 🤷 Je ne sais pas quoi dire
4. 😱 La peur du jugement

Perso, c'était le 1 pendant longtemps. Et vous ?

Dites-moi en commentaire, ça m'intéresse vraiment !""",
            'tone': 'humoristique',
            'views': 3400, 'likes': 178, 'comments': 156, 'shares': 23,
        },
    ],
    'instagram': [
        {
            'summary': 'Tips design',
            'content': """3 erreurs de design que je vois PARTOUT 👇

1️⃣ Trop de polices différentes
→ Max 2 polices. Une pour les titres, une pour le corps.

2️⃣ Pas assez de blanc
→ L'espace vide n'est pas du gaspillage. C'est de la respiration.

3️⃣ Des couleurs qui crient
→ 1 couleur d'accent max. Le reste en neutre.

Le bon design, c'est pas "joli".
C'est clair. C'est lisible. C'est fonctionnel.

Enregistre ce post si tu veux t'en souvenir 💾

#design #uxdesign #freelancedesigner #tips""",
            'tone': 'educatif',
            'views': 7800, 'likes': 456, 'comments': 34, 'shares': 12,
        },
    ],
    'x': [
        {
            'summary': 'Hot take IA',
            'content': """Hot take : 90% des "experts IA" sur Twitter n'ont jamais deployé un modèle en production.

Tester GPT dans le playground ≠ faire de l'IA.

Les vrais problèmes : latence, coûts, hallucinations, monitoring, eval.

Mais ça, ça fait moins de likes.""",
            'tone': 'professionnel',
            'views': 4500, 'likes': 234, 'comments': 67, 'shares': 45,
        },
        {
            'summary': 'Thread productivité',
            'content': """Thread : 7 outils qui ont 10x ma productivité en 2026

1/ Claude Code — je code 3x plus vite
2/ Linear — gestion de projet sans friction
3/ Notion — mon second cerveau
4/ Cal.com — plus jamais de "t'es dispo quand ?"
5/ Loom — les réunions inutiles, c'est fini
6/ Publiar — mes posts se créent tout seuls
7/ Arc Browser — un navigateur qui pense

Le meilleur investissement, c'est les bons outils.""",
            'tone': 'educatif',
            'views': 8900, 'likes': 567, 'comments': 89, 'shares': 123,
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed the database with demo accounts and realistic content'

    def handle(self, *args, **options):
        created_users = 0
        created_posts = 0
        now = timezone.now()

        for profile_data in DEMO_PROFILES:
            username = profile_data['username']

            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': profile_data['first_name'],
                    'last_name': profile_data['last_name'],
                    'email': f"{username}@publiar.app",
                }
            )
            if user_created:
                user.set_unusable_password()
                user.save()
                created_users += 1

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.is_demo = True
            profile.role = profile_data['role']
            profile.industry = profile_data['industry']
            profile.expertise = profile_data['expertise']
            profile.target_audience = profile_data['target_audience']
            profile.bio = profile_data['bio']
            profile.onboarding_completed = True
            profile.save()

            Subscription.objects.get_or_create(
                user=user,
                defaults={'plan': 'pro', 'status': 'active'}
            )

            # Create published posts
            platform = profile_data['platform_focus']
            posts = DEMO_POSTS.get(platform, DEMO_POSTS['linkedin'])

            for i, post_data in enumerate(posts):
                days_ago = random.randint(1, 55)
                pub_date = now - timedelta(days=days_ago, hours=random.randint(6, 20))

                _, post_created = PublishedPost.objects.get_or_create(
                    user=user,
                    content=post_data['content'][:100],
                    defaults={
                        'content': post_data['content'],
                        'tone': post_data['tone'],
                        'platform': platform,
                        'published_at': pub_date,
                        'views': post_data['views'] + random.randint(-200, 500),
                        'likes': post_data['likes'] + random.randint(-20, 50),
                        'comments': post_data['comments'] + random.randint(-5, 15),
                        'shares': post_data['shares'] + random.randint(-3, 10),
                        'has_images': random.choice([True, False]),
                    }
                )
                if post_created:
                    created_posts += 1

                # Also create a GeneratedPost
                GeneratedPost.objects.get_or_create(
                    user=user,
                    summary=post_data['summary'],
                    defaults={
                        'tone': post_data['tone'],
                        'platform': platform,
                        'generated_content': post_data['content'],
                    }
                )

            # Create scheduled posts for some users
            if random.random() > 0.4:
                for j in range(random.randint(1, 3)):
                    sched_date = now + timedelta(days=random.randint(1, 7), hours=random.randint(8, 18))
                    ScheduledPost.objects.get_or_create(
                        user=user,
                        scheduled_at=sched_date,
                        defaults={
                            'content': random.choice(posts)['content'],
                            'status': 'pending',
                            'platform': platform,
                        }
                    )

        self.stdout.write(f'Demo data seeded: {created_users} users, {created_posts} posts created.')
