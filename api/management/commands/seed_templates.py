from django.core.management.base import BaseCommand
from api.models import PromptTemplate


GLOBAL_TEMPLATES = [
    {
        'name': 'Post technique',
        'description': 'Pour partager des connaissances techniques et des tutoriels',
        'default_tone': 'educatif',
        'prompt_prefix': (
            "Tu es un expert technique reconnu dans ton domaine. "
            "Écris un post LinkedIn pédagogique qui vulgarise un concept technique. "
            "Utilise des exemples concrets, du code si pertinent, et des analogies simples. "
            "Structure le post avec un hook technique surprenant."
        ),
        'prompt_suffix': (
            "Termine par une question ouverte pour engager les développeurs et techniciens. "
            "Ajoute un CTA du type : 'Quel concept technique vous a le plus surpris récemment ?'"
        ),
    },
    {
        'name': 'Thought Leadership',
        'description': "Pour partager une vision stratégique et se positionner comme leader d'opinion",
        'default_tone': 'professionnel',
        'prompt_prefix': (
            "Tu es un leader d'opinion dans ton domaine. "
            "Partage une vision stratégique ou une analyse de fond sur un sujet business. "
            "Prends position avec conviction, appuie-toi sur des données ou des tendances. "
            "Le hook doit être une déclaration forte ou contre-intuitive."
        ),
        'prompt_suffix': (
            "Finis par un appel à la réflexion qui pousse le lecteur à repenser ses certitudes. "
            "Pose une question qui invite au débat constructif."
        ),
    },
    {
        'name': 'Storytelling personnel',
        'description': "Pour raconter une expérience personnelle marquante et inspirante",
        'default_tone': 'storytelling',
        'prompt_prefix': (
            "Raconte une expérience personnelle ou professionnelle marquante. "
            "Utilise la structure : situation initiale → défi/problème → tournant → résolution. "
            "Sois authentique et vulnérable. Le lecteur doit se reconnaître dans ton histoire. "
            "Le hook doit être une phrase qui donne envie de connaître la suite."
        ),
        'prompt_suffix': (
            "Termine par la leçon apprise et un message inspirant. "
            "Ajoute une question : 'Et toi, as-tu déjà vécu une situation similaire ?'"
        ),
    },
    {
        'name': 'Quick Tips / Astuces',
        'description': 'Pour partager des astuces concrètes et actionnables',
        'default_tone': 'educatif',
        'prompt_prefix': (
            "Partage 3 à 5 astuces concrètes et actionnables que le lecteur peut appliquer immédiatement. "
            "Chaque astuce doit être claire, courte et illustrée par un exemple. "
            "Utilise des numéros ou des emojis pour structurer. "
            "Le hook doit promettre une transformation rapide."
        ),
        'prompt_suffix': (
            "Ajoute un CTA pour que les lecteurs partagent leurs propres astuces en commentaire. "
            "Par exemple : 'Quelle astuce ajouterais-tu à cette liste ?'"
        ),
    },
    {
        'name': 'Actualité / Tendance',
        'description': 'Pour commenter une actualité ou tendance de votre secteur',
        'default_tone': 'professionnel',
        'prompt_prefix': (
            "Commente une actualité ou tendance récente de ton secteur. "
            "Apporte ton analyse personnelle : pourquoi c'est important, quel impact, quelles opportunités. "
            "Ne te contente pas de relayer l'info, ajoute ta perspective unique. "
            "Le hook doit créer un sentiment d'urgence ou de curiosité."
        ),
        'prompt_suffix': (
            "Pose une question ouverte sur l'avenir de cette tendance. "
            "Invite les lecteurs à partager leur point de vue."
        ),
    },
    {
        'name': 'Lancement produit',
        'description': "Pour annoncer un produit, une feature ou un projet",
        'default_tone': 'inspirant',
        'prompt_prefix': (
            "Annonce un produit, une feature ou un projet avec enthousiasme et authenticité. "
            "Raconte le 'pourquoi' avant le 'quoi' : quel problème tu résous, pour qui. "
            "Montre les coulisses du développement si possible. "
            "Le hook doit créer de l'anticipation."
        ),
        'prompt_suffix': (
            "Termine par un CTA clair : lien, inscription, ou invitation à tester. "
            "Ajoute une touche personnelle sur ce que ce lancement représente pour toi."
        ),
    },
    {
        'name': "Retour d'expérience",
        'description': 'Pour partager un retour concret problème → solution → résultat',
        'default_tone': 'storytelling',
        'prompt_prefix': (
            "Partage un retour d'expérience concret avec la structure : "
            "Problème rencontré → Solution mise en place → Résultat obtenu. "
            "Sois précis sur les chiffres et les détails. "
            "Le hook doit poser le problème de manière relatable."
        ),
        'prompt_suffix': (
            "Finis par les 3 enseignements clés que tu en retires. "
            "Demande aux lecteurs s'ils ont vécu une situation similaire."
        ),
    },
    {
        'name': 'Conseil carrière',
        'description': 'Pour partager un conseil de carrière ou de management',
        'default_tone': 'inspirant',
        'prompt_prefix': (
            "Partage un conseil de carrière ou de management basé sur ton vécu. "
            "Sois concret : donne un exemple réel qui illustre ton propos. "
            "Évite les clichés et les platitudes. "
            "Le hook doit être un conseil contre-intuitif ou une leçon apprise à la dure."
        ),
        'prompt_suffix': (
            "Termine par une question engageante : "
            "'Et toi, quel conseil aurais-tu aimé recevoir plus tôt dans ta carrière ?'"
        ),
    },
]


class Command(BaseCommand):
    help = 'Crée les templates globaux prêts à l\'emploi pour tous les utilisateurs'

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for tpl_data in GLOBAL_TEMPLATES:
            _, was_created = PromptTemplate.objects.get_or_create(
                name=tpl_data['name'],
                is_global=True,
                defaults={
                    'user': None,
                    'description': tpl_data['description'],
                    'default_tone': tpl_data['default_tone'],
                    'prompt_prefix': tpl_data['prompt_prefix'],
                    'prompt_suffix': tpl_data['prompt_suffix'],
                    'is_default': False,
                    'is_global': True,
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(f'{created} templates créés, {skipped} déjà existants')
        )
