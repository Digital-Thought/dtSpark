"""
Action Scheduler Manager module.

Provides APScheduler wrapper for scheduling autonomous actions.


"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    BackgroundScheduler = None
    MemoryJobStore = None
    DateTrigger = None
    CronTrigger = None


class ActionSchedulerManager:
    """
    Manages scheduled autonomous actions using APScheduler.

    Uses BackgroundScheduler with SQLAlchemyJobStore for persistence.
    Supports both one-off (DateTrigger) and recurring (CronTrigger) schedules.
    """

    def __init__(self, db_path: str, execution_callback: Callable[[int, str], None]):
        """
        Initialise the action scheduler manager.

        Args:
            db_path: Path to SQLite database for job persistence
            execution_callback: Callback function(action_id, user_guid) to execute actions
        """
        if not APSCHEDULER_AVAILABLE:
            raise ImportError(
                "APScheduler is required for autonomous actions. "
                "Install it with: pip install APScheduler>=3.10.0"
            )

        self.db_path = db_path
        self.execution_callback = execution_callback
        self.scheduler: Optional[BackgroundScheduler] = None
        self._is_running = False

        logging.info("ActionSchedulerManager initialised (using in-memory job store)")

    def initialise(self):
        """
        Initialise the APScheduler with in-memory job store.

        We use MemoryJobStore instead of SQLAlchemyJobStore because:
        1. We already persist action configurations in our own database
        2. On startup, we reload all actions from our database
        3. MemoryJobStore avoids pickling issues with callbacks
        """
        if self.scheduler is not None:
            logging.warning("Scheduler already initialised")
            return

        job_stores = {
            'default': MemoryJobStore()
        }

        job_defaults = {
            'coalesce': True,  # Combine missed runs into one
            'max_instances': 1,  # Only one instance of each job at a time
            'misfire_grace_time': 3600  # Allow 1 hour grace time for missed jobs
        }

        self.scheduler = BackgroundScheduler(
            jobstores=job_stores,
            job_defaults=job_defaults,
            timezone='UTC'
        )

        # Add event listeners for logging
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)

        logging.info("APScheduler initialised with in-memory job store")

    def start(self):
        """
        Start the scheduler.
        """
        if self.scheduler is None:
            raise RuntimeError("Scheduler not initialised. Call initialise() first.")

        if self._is_running:
            logging.warning("Scheduler already running")
            return

        self.scheduler.start()
        self._is_running = True
        logging.info("Action scheduler started")

    def stop(self):
        """
        Stop the scheduler gracefully.
        """
        if self.scheduler is None or not self._is_running:
            return

        self.scheduler.shutdown(wait=True)
        self._is_running = False
        logging.info("Action scheduler stopped")

    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._is_running

    def schedule_action(self, action_id: int, action_name: str,
                        schedule_type: str, schedule_config: Dict[str, Any],
                        user_guid: str) -> bool:
        """
        Schedule an action for execution.

        Args:
            action_id: ID of the action
            action_name: Name of the action (for job ID)
            schedule_type: 'one_off' or 'recurring'
            schedule_config: Schedule configuration
            user_guid: User GUID for execution context

        Returns:
            True if scheduled successfully
        """
        if self.scheduler is None:
            logging.error("Cannot schedule action: scheduler not initialised")
            return False

        job_id = f"action_{action_id}"

        try:
            # Remove existing job if any
            self._remove_job_if_exists(job_id)

            if schedule_type == 'one_off':
                trigger = self._create_date_trigger(schedule_config)
            elif schedule_type == 'recurring':
                trigger = self._create_cron_trigger(schedule_config)
            else:
                logging.error(f"Unknown schedule type: {schedule_type}")
                return False

            if trigger is None:
                return False

            self.scheduler.add_job(
                func=self._execute_action_wrapper,
                trigger=trigger,
                id=job_id,
                name=action_name,
                args=[action_id, user_guid],
                replace_existing=True
            )

            next_run = self.scheduler.get_job(job_id).next_run_time
            logging.info(f"Scheduled action {action_id} ({action_name}), next run: {next_run}")
            return True

        except Exception as e:
            logging.error(f"Failed to schedule action {action_id}: {e}")
            return False

    def unschedule_action(self, action_id: int) -> bool:
        """
        Remove a scheduled action.

        Args:
            action_id: ID of the action

        Returns:
            True if removed successfully
        """
        if self.scheduler is None:
            return False

        job_id = f"action_{action_id}"
        return self._remove_job_if_exists(job_id)

    def run_action_now(self, action_id: int, user_guid: str) -> bool:
        """
        Trigger an action to run immediately.

        Args:
            action_id: ID of the action
            user_guid: User GUID for execution context

        Returns:
            True if triggered successfully
        """
        if self.scheduler is None:
            logging.error("Cannot run action: scheduler not initialised")
            return False

        try:
            # Add a one-time job that runs immediately
            job_id = f"action_{action_id}_manual"
            self._remove_job_if_exists(job_id)

            self.scheduler.add_job(
                func=self._execute_action_wrapper,
                trigger='date',  # Run immediately
                id=job_id,
                name=f"Manual run of action {action_id}",
                args=[action_id, user_guid]
            )

            logging.info(f"Triggered manual run of action {action_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to trigger manual run of action {action_id}: {e}")
            return False

    def get_next_run_time(self, action_id: int) -> Optional[datetime]:
        """
        Get the next scheduled run time for an action.

        Args:
            action_id: ID of the action

        Returns:
            Next run time or None if not scheduled
        """
        if self.scheduler is None:
            return None

        job_id = f"action_{action_id}"
        job = self.scheduler.get_job(job_id)

        if job:
            return job.next_run_time
        return None

    def reload_all_actions(self, actions: List[Dict[str, Any]]):
        """
        Reload all enabled actions from database.

        Args:
            actions: List of action dictionaries
        """
        if self.scheduler is None:
            logging.warning("Cannot reload actions: scheduler not initialised")
            return

        loaded_count = 0
        for action in actions:
            if action.get('is_enabled', False):
                success = self.schedule_action(
                    action_id=action['id'],
                    action_name=action['name'],
                    schedule_type=action['schedule_type'],
                    schedule_config=action['schedule_config'],
                    user_guid=action.get('user_guid', '')
                )
                if success:
                    loaded_count += 1

        logging.info(f"Reloaded {loaded_count} scheduled actions")

    def get_scheduled_jobs(self) -> List[Dict[str, Any]]:
        """
        Get list of all scheduled jobs.

        Returns:
            List of job information dictionaries
        """
        if self.scheduler is None:
            return []

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time,
                'trigger': str(job.trigger)
            })
        return jobs

    def _execute_action_wrapper(self, action_id: int, user_guid: str):
        """
        Wrapper function called by APScheduler to execute an action.

        Args:
            action_id: ID of the action
            user_guid: User GUID for execution context
        """
        try:
            logging.info(f"Scheduler triggering action {action_id} for user {user_guid}")
            self.execution_callback(action_id, user_guid)
        except Exception as e:
            logging.error(f"Error in action execution wrapper for action {action_id}: {e}")
            raise

    def _create_date_trigger(self, config: Dict[str, Any]) -> Optional[DateTrigger]:
        """
        Create a DateTrigger for one-off scheduling.

        Args:
            config: Configuration with 'run_date' key

        Returns:
            DateTrigger or None if invalid
        """
        try:
            run_date = config.get('run_date')
            if isinstance(run_date, str):
                run_date = datetime.fromisoformat(run_date)
            elif not isinstance(run_date, datetime):
                logging.error(f"Invalid run_date format: {run_date}")
                return None

            return DateTrigger(run_date=run_date)

        except Exception as e:
            logging.error(f"Failed to create date trigger: {e}")
            return None

    def _create_cron_trigger(self, config: Dict[str, Any]) -> Optional[CronTrigger]:
        """
        Create a CronTrigger for recurring scheduling.

        Args:
            config: Configuration with cron fields or 'cron_expression' key

        Returns:
            CronTrigger or None if invalid
        """
        try:
            # Support both individual fields and expression
            if 'cron_expression' in config:
                # Parse cron expression (minute hour day month day_of_week)
                parts = config['cron_expression'].split()
                if len(parts) >= 5:
                    return CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4]
                    )

            # Individual fields
            return CronTrigger(
                minute=config.get('minute', '*'),
                hour=config.get('hour', '*'),
                day=config.get('day', '*'),
                month=config.get('month', '*'),
                day_of_week=config.get('day_of_week', '*')
            )

        except Exception as e:
            logging.error(f"Failed to create cron trigger: {e}")
            return None

    def _remove_job_if_exists(self, job_id: str) -> bool:
        """
        Remove a job if it exists.

        Args:
            job_id: Job ID to remove

        Returns:
            True if removed, False if didn't exist
        """
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logging.debug(f"Removed existing job: {job_id}")
                return True
        except Exception as e:
            logging.debug(f"Job {job_id} not found or could not be removed: {e}")
        return False

    def _on_job_executed(self, event: 'JobExecutionEvent'):
        """Handle successful job execution event."""
        logging.info(f"Job {event.job_id} executed successfully")

    def _on_job_error(self, event: 'JobExecutionEvent'):
        """Handle job error event."""
        logging.error(f"Job {event.job_id} raised an exception: {event.exception}")
