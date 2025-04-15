# --- Start of File: config.py ---
import os
import torch
from dotenv import load_dotenv
import logging # Import logging standard library

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("Loaded configuration settings from .env file.")
else:
    print("Warning: .env file not found. Using system environment variables or default settings.")


class Config:
    """ Application Configuration Class """

    # --- Core Flask Settings ---
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'default-insecure-key-please-change')
    if SECRET_KEY == 'default-insecure-key-please-change':
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("WARNING: FLASK_SECRET_KEY is not set securely in your .env file!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    PORT = int(os.environ.get('PORT', 5001))

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
    print(f"Configuration: Celery Broker='{CELERY_BROKER_URL}', Result Backend='{CELERY_RESULT_BACKEND}'")

    # --- Processing & AI Model Settings ---
    try:
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        print(f"Warning: Error checking torch/cuda availability: {e}. Defaulting device to 'cpu'.")
        DEVICE = "cpu"
    print(f"Configuration: Determined processing device: {DEVICE.upper()}")

    # --- Faster-Whisper (Transcription) Settings ---
    FASTER_WHISPER_MODEL = os.environ.get('FASTER_WHISPER_MODEL', 'base.en')
    FASTER_WHISPER_COMPUTE_TYPE = os.environ.get('FASTER_WHISPER_COMPUTE_TYPE', 'int8' if DEVICE == 'cpu' else 'float16')
    print(f"Configuration: FasterWhisper Model='{FASTER_WHISPER_MODEL}', ComputeType='{FASTER_WHISPER_COMPUTE_TYPE}'")

    # --- Pyannote (Speaker Diarization) Settings ---
    HUGGING_FACE_TOKEN = os.environ.get('HUGGING_FACE_TOKEN')
    PYANNOTE_PIPELINE = os.environ.get('PYANNOTE_PIPELINE', 'pyannote/speaker-diarization@2.1')
    if not HUGGING_FACE_TOKEN:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("WARNING: HUGGING_FACE_TOKEN environment variable is not set in .env file.")
        print("         Speaker diarization (Pyannote) WILL LIKELY FAIL.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        token_display = HUGGING_FACE_TOKEN[:4] + "..." + HUGGING_FACE_TOKEN[-4:] if len(HUGGING_FACE_TOKEN) > 8 else "Token Set"
        print(f"Configuration: Pyannote Pipeline='{PYANNOTE_PIPELINE}', HF Token='{token_display}'")

    # --- Media Utilities (FFmpeg) Settings ---
    FFMPEG_PATH = os.environ.get('FFMPEG_PATH', 'ffmpeg')
    print(f"Configuration: FFmpeg Path='{FFMPEG_PATH}' (ffprobe assumed relative)")

    # --- Clipping Defaults ---
    CLIP_MAX_DURATION_SECONDS = float(os.environ.get('CLIP_MAX_DURATION_SECONDS', 60.0))
    CLIP_MIN_DURATION_SECONDS = float(os.environ.get('CLIP_MIN_DURATION_SECONDS', 15.0))
    CLIP_MANUAL_MAX_DURATION_SECONDS = float(os.environ.get('CLIP_MANUAL_MAX_DURATION_SECONDS', 120.0))
    print(f"Configuration: Clip Duration Range Min={CLIP_MIN_DURATION_SECONDS}s, ShortsMax={CLIP_MAX_DURATION_SECONDS}s, ManualMax={CLIP_MANUAL_MAX_DURATION_SECONDS}s")

    # --- User Interface / Real-time Updates --- <<< ADDED >>>
    SSE_POLL_INTERVAL_SECONDS = float(os.environ.get('SSE_POLL_INTERVAL_SECONDS', 3.0)) # Interval for checking DB updates for SSE stream
    print(f"Configuration: SSE Poll Interval={SSE_POLL_INTERVAL_SECONDS}s")

    # --- Static Method for Directory Creation ---
    @staticmethod
    def check_and_create_dirs():
        """ Checks if essential application directories exist and creates them if missing. """
        dirs_to_create = [
            Config.INSTANCE_FOLDER_PATH,
            Config.DOWNLOAD_DIR,
            Config.PROCESSED_CLIPS_DIR,
            os.path.dirname(Config.LOG_FILE_PATH)
        ]
        print("Checking/Creating necessary directories...")
        for dir_path in dirs_to_create:
            if dir_path and not os.path.exists(dir_path):
                try:
                    os.makedirs(dir_path, exist_ok=True)
                    print(f" -> Created directory: {dir_path}")
                except OSError as e:
                    print(f"ERROR: Failed to create directory {dir_path}: {e}. Check permissions.")
            elif dir_path:
                 print(f" -> Directory exists: {dir_path}")


# --- Ensure directories are checked/created when this module is imported ---
Config.check_and_create_dirs()

# --- Helper function to get config instance easily (optional) ---
def get_config():
    """Returns an instance of the Config class."""
    return Config()

# --- END OF FILE: config.py ---