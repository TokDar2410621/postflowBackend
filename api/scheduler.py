import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_started = False


def start():
    """Démarre le scheduler avec les tâches périodiques."""
    global _started
    if _started:
        return
    _started = True

    # Job 1 : Publier les posts programmés (toutes les 2 minutes)
    from api.schedule import publish_scheduled_posts
    scheduler.add_job(
        publish_scheduled_posts,
        trigger=IntervalTrigger(minutes=2),
        id='publish_scheduled',
        name='Publier les posts programmés',
        replace_existing=True,
    )

    # Job 2 : Mettre à jour les stats LinkedIn (toutes les 6 heures)
    from api.linkedin import update_all_post_stats
    scheduler.add_job(
        update_all_post_stats,
        trigger=IntervalTrigger(hours=6),
        id='update_linkedin_stats',
        name='MAJ stats LinkedIn',
        replace_existing=True,
    )

    scheduler.start()
    logger.info('Scheduler démarré : publish_scheduled (2min) + update_linkedin_stats (6h)')
