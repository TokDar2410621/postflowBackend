import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_started = False


def start():
    """Start the scheduler with periodic jobs."""
    global _started
    if _started:
        logger.info('Scheduler already started in this process, skipping.')
        return
    _started = True

    from api.schedule import publish_scheduled_posts
    scheduler.add_job(
        publish_scheduled_posts,
        trigger=IntervalTrigger(minutes=1),
        id='publish_scheduled',
        name='Publish scheduled posts',
        replace_existing=True,
    )

    from api.linkedin import update_all_post_stats
    scheduler.add_job(
        update_all_post_stats,
        trigger=IntervalTrigger(hours=6),
        id='update_linkedin_stats',
        name='Update LinkedIn stats',
        replace_existing=True,
    )

    scheduler.start()
    logger.info('Scheduler started: publish_scheduled (1min) + update_linkedin_stats (6h)')
