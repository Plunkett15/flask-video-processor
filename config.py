# --- Start of File: config.py ---
import os
import torch
from dotenv import load_dotenv
import logging

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print("Warning: .env file not found. Using system environment variables or default settings.")

class Config:
    """ Application Configuration Class """

    # --- Core Flask Settings ---
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'default-insecure-key-please-change')
    PORT = int(os.environ.get('PORT', 5001))
    # --- ADD THIS LINE BACK ---
    APP_THREADS = int(os.environ.get('APP_THREADS', 8)) # Number of threads for the Waitress server

    # --- Application Paths ---
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    INSTANCE_FOLDER_PATH = os.path.join(APP_ROOT, 'instance')
    DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(INSTANCE_FOLDER_PATH, 'videos.db'))
    DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR', os.path.join(APP_ROOT, 'downloads'))
    PROCESSED_CLIPS_DIR = os.environ.get('PROCESSED_CLIPS_DIR', os.path.join(APP_ROOT, 'processed_clips'))

    # --- Logging Settings ---
    LOG_FILE_PATH = os.environ.get('LOG_FILE_PATH', os.path.join(INSTANCE_FOLDER_PATH, 'app.log'))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

    # --- Celery / Background Task Settings ---
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

    # --- Processing & AI Model Settings ---
    try:
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"Warning: Error checking torch/cuda availability: {e}. Defaulting device to 'cpu'.")
        DEVICE = "cpu"

    # --- Faster-Whisper (Transcription) Settings ---
    FASTER_WHISPER_MODEL = os.environ.get('FASTER_WHISPER_MODEL', 'tiny.en') # Defaulting to tiny.en
    FASTER_WHISPER_COMPUTE_TYPE = os.environ.get('FASTER_WHISPER_COMPUTE_TYPE', 'int8' if DEVICE == 'cpu' else 'float16')

    # --- Pyannote (Speaker Diarization) Settings ---
    HUGGING_FACE_TOKEN = os.environ.get('HUGGING_FACE_TOKEN')
    PYANNOTE_PIPELINE = os.environ.get('PYANNOTE_PIPELINE', 'pyannote/speaker-diarization@2.1')

    # --- Media Utilities (FFmpeg) Settings ---
    FFMPEG_PATH = os.environ.get('FFMPEG_PATH', 'ffmpeg')

    # --- Clipping Defaults ---
    # Removed specific limits, can be added back if needed
    # CLIP_MIN_DURATION_SECONDS = float(os.environ.get('CLIP_MIN_DURATION_SECONDS', 1.0)) # Example minimum
    # CLIP_MANUAL_MAX_DURATION_SECONDS = float(os.environ.get('CLIP_MANUAL_MAX_DURATION_SECONDS', 300.0)) # Example max

    # --- User Interface / Real-time Updates ---
    SSE_POLL_INTERVAL_SECONDS = float(os.environ.get('SSE_POLL_INTERVAL_SECONDS', 3.0))

    # --- Static Method for Directory Creation ---
    @staticmethod
    def check_and_create_dirs():
        logger = logging.getLogger(__name__)
        dirs_to_create = [
            Config.INSTANCE_FOLDER_PATH,
            Config.DOWNLOAD_DIR,
            Config.PROCESSED_CLIPS_DIR,
            os.path.dirname(Config.LOG_FILE_PATH)
        ]
        logger.info("Checking/Creating necessary directories...")
        for dir_path in dirs_to_create:
            if dir_path and not os.path.exists(dir_path):
                try:
                    os.makedirs(dir_path, exist_ok=True)
                    logger.info(f" -> Created directory: {dir_path}")
                except OSError as e:
                    logger.error(f" -> Failed to create directory {dir_path}: {e}. Check permissions.")
            # else: logger.info(f" -> Directory exists: {dir_path}")


# Ensure directories are checked/created explicitly in app.py or worker startup if needed.
# Config.check_and_create_dirs() # Call removed from here

def get_config():
    return Config()

# --- END OF FILE: config.py ---