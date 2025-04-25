# --- Start of File: celery_app.py ---
from celery import Celery
from config import Config # Import your configuration class

# Instantiate the configuration
config = Config()

# Create the Celery application instance
# The first argument is the traditional name of the main module (often app name)
# It's used for generating automatic task names.
celery_app = Celery(
    'video_processor_tasks', # Can be any name, helps identify workers/logs
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    # <<< MODIFIED: Point to the new task modules >>>
    include=['tasks.video_tasks', 'tasks.exchange_tasks'] # List of modules where tasks are defined
)

# Load Celery configuration from the Config object
# The namespace='CELERY' means Celery looks for config keys starting with CELERY_
celery_app.config_from_object(config, namespace='CELERY')

# Optional: Configure task serialization (JSON is default and usually fine)
# celery_app.conf.update(
#     task_serializer='json',
#     accept_content=['json'],  # Ensure accepts json content
#     result_serializer='json',
#     timezone='UTC', # Example: Set timezone if needed
#     enable_utc=True,
# )

# Optional: Auto-discover tasks from modules listed in 'include'
# celery_app.autodiscover_tasks() # Might not be needed if 'include' is used directly

if __name__ == '__main__':
    # This allows running the worker directly using `python celery_app.py worker`
    # although `celery -A celery_app.celery_app worker ...` is more common.
    celery_app.start()
# --- END OF FILE: celery_app.py ---