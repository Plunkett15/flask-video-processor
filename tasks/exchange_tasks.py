# --- Start of File: tasks/exchange_tasks.py ---
import logging
import os
import json
import time
import datetime
from celery import Task
from celery.exceptions import Ignore

# Project specific imports
import database as db
from utils import media_utils, error_utils
from analysis import clip_logic # Import the clip definition logic
from config import Config

# --- Celery App Instance ---
from celery_app import celery_app

# Configure logger for this tasks module
logger = logging.getLogger(__name__)
config = Config()

# =============================================================================
# === Helper: Get Required Path (Copied for self-containment) ===
# =============================================================================
# Duplicated from video_tasks.py for self-containment. Consider a shared util later.
def _get_required_path(video_id, path_type, step_name_for_error):
    """ Fetches a required file path (video or audio) from DB, raising error if missing. """
    video_data = db.get_video_by_id(video_id)
    if not video_data: raise ValueError(f"Video record {video_id} not found.")

    path_col = 'file_path' if path_type == 'video' else 'audio_path'
    file_path = video_data.get(path_col)

    if not file_path: raise ValueError(f"Required {path_type} path is missing in DB for video {video_id}.")
    if not os.path.exists(file_path): raise RuntimeError(f"Required {path_type} file not found on disk at '{file_path}' for video {video_id}.")
    if os.path.getsize(file_path) == 0: raise RuntimeError(f"Required {path_type} file is empty (0 bytes) at '{file_path}' for video {video_id}.")

    logger.debug(f"Verified required {path_type} file: {file_path}")
    return file_path, video_data

# =============================================================================
# === Phase 2 Celery Tasks (Exchange Level Processing) ===
# =============================================================================

# --- Retry Policy Defaults ---
RETRYABLE_EXCEPTIONS = (RuntimeError, ConnectionError, TimeoutError, OSError)
NON_RETRYABLE_EXCEPTIONS = (ValueError, TypeError, KeyError, json.JSONDecodeError)

@celery_app.task(
    bind=True,
    name='tasks.exchange_tasks.process_exchange_diarization_task',
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_kwargs={'max_retries': 2, 'countdown': 10}
)
def process_exchange_diarization_task(self: Task, long_exchange_db_id: int):
    """ (Celery Task) Filters full diarization result for a specific exchange. """
    substep_name = 'diarization' # Matches the substep status/error columns
    logger.info(f"--- Starting {substep_name} Substep Task (Attempt {self.request.retries + 1}) for Exchange DB ID: {long_exchange_db_id} ---")
    filtered_diar_result = None
    try:
        if self.request.retries == 0:
            db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')

        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.") # Non-retryable
        video_id = exchange_data.get('video_id')
        if not video_id: raise ValueError(f"Parent video ID missing for exchange {long_exchange_db_id}.") # Non-retryable

        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError(f"Parent video record {video_id} not found.") # Non-retryable

        # Check prerequisite: Full diarization must be complete
        if video_data.get('diarization_status') != 'Complete':
            raise Ignore("Cannot process exchange diarization: Parent video full diarization is not 'Complete'.") # Non-retryable state

        full_diar_json = video_data.get('full_diarization_result')
        if not full_diar_json: raise ValueError("Full diarization result missing in DB.") # Non-retryable

        # JSON parsing errors are not retryable
        full_diar_segments = json.loads(full_diar_json)

        exchange_start = exchange_data.get('start_time'); exchange_end = exchange_data.get('end_time')
        if exchange_start is None or exchange_end is None: raise ValueError("Exchange start/end times missing.") # Non-retryable

        logger.info(f"Filtering full diarization ({len(full_diar_segments)} segments) for exchange {long_exchange_db_id} ({exchange_start:.3f}s - {exchange_end:.3f}s)")

        # Filtering logic (moved from pipeline.py)
        filtered_diar_result = []
        tolerance = 0.01
        for seg in full_diar_segments:
             try:
                 seg_start = float(seg.get('start'))
                 seg_end = float(seg.get('end'))
                 if seg_start is None or seg_end is None or seg_end <= seg_start: continue

                 overlaps = seg_start < (exchange_end + tolerance) and seg_end > (exchange_start - tolerance)
                 if overlaps:
                    clipped_start = max(seg_start, exchange_start)
                    clipped_end = min(seg_end, exchange_end)
                    if clipped_end > clipped_start:
                         new_seg = seg.copy()
                         new_seg['start'] = round(clipped_start, 3)
                         new_seg['end'] = round(clipped_end, 3)
                         filtered_diar_result.append(new_seg)
             except (TypeError, ValueError, KeyError) as e: # Treat segment processing errors as warnings, not task failures
                 logger.warning(f"Skipping segment during filtering due to parsing error or missing key: {seg} - Error: {e}")
                 continue

        logger.info(f"Found {len(filtered_diar_result)} diarization segments within exchange boundaries.")
        # DB updates could be retryable if DB connection blips
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, filtered_diar_result)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Complete')
        logger.info(f"--- {substep_name} Substep Task SUCCESS for Exchange DB ID: {long_exchange_db_id} ---")

    except NON_RETRYABLE_EXCEPTIONS as e:
        logger.error(f"--- {substep_name} Substep Task NON-RETRYABLE FAIL for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=error_msg)
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)
        raise Ignore()
    except Exception as e:
        logger.warning(f"--- {substep_name} Substep Task FAILED (Will Retry If Possible) for Exchange DB ID: {long_exchange_db_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)
        raise e


@celery_app.task(
    bind=True,
    name='tasks.exchange_tasks.define_short_clips_task',
    autoretry_for=(RuntimeError,), # Less likely to need retries here unless DB fails
    retry_kwargs={'max_retries': 1, 'countdown': 5}
)
def define_short_clips_task(self: Task, long_exchange_db_id: int):
    """ (Celery Task) Defines short clips based on processed exchange diarization. """
    substep_name = 'clip_definition'
    logger.info(f"--- Starting {substep_name} Substep Task (Attempt {self.request.retries + 1}) for Exchange DB ID: {long_exchange_db_id} ---")
    short_clip_definitions = None
    try:
        if self.request.retries == 0:
            db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')

        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.") # Non-retryable

        # Check prerequisite
        if exchange_data.get('diarization_status') != 'Complete':
             raise Ignore("Cannot define short clips: Exchange diarization processing is not 'Complete'.") # Non-retryable state

        diar_result_json = exchange_data.get('diarization_result')
        if diar_result_json is None: raise ValueError("Exchange diarization result is missing in DB.") # Non-retryable

        # JSON parsing errors are not retryable
        exchange_diar_segments = json.loads(diar_result_json)

        logger.info(f"Defining short clips from {len(exchange_diar_segments)} processed diarization segments for exchange {long_exchange_db_id}.")
        # Call the dedicated function from clip_logic
        short_clip_definitions = clip_logic.define_short_clips_from_segments(exchange_diar_segments, config)

        # Store the definitions (DB operations might be retryable)
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, short_clip_definitions)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Complete')
        logger.info(f"--- {substep_name} Substep Task SUCCESS for Exchange DB ID: {long_exchange_db_id} --- Defined {len(short_clip_definitions)} clips.")

    except NON_RETRYABLE_EXCEPTIONS as e:
        logger.error(f"--- {substep_name} Substep Task NON-RETRYABLE FAIL for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=error_msg)
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)
        raise Ignore()
    except Exception as e:
        logger.warning(f"--- {substep_name} Substep Task FAILED (Will Retry If Possible) for Exchange DB ID: {long_exchange_db_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)
        raise e


@celery_app.task(
    bind=True,
    name='tasks.exchange_tasks.cut_short_clips_task',
    autoretry_for=RETRYABLE_EXCEPTIONS, # FFmpeg/IO errors might be transient
    retry_kwargs={'max_retries': 2, 'countdown': 20}
)
def cut_short_clips_task(self: Task, long_exchange_db_id: int):
    """ (Celery Task) Cuts the defined short clips using FFmpeg, with retries. """
    substep_name = 'clip_cutting'
    logger.info(f"--- Starting {substep_name} Substep Task (Attempt {self.request.retries + 1}) for Exchange DB ID: {long_exchange_db_id} ---")
    failed_clips = 0; successful_clips = 0
    final_status = 'Pending'; final_error_message = None
    error_messages = []

    try:
        if self.request.retries == 0:
            db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')

        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.") # Non-retryable
        video_id = exchange_data.get('video_id')
        if not video_id: raise ValueError(f"Parent video ID missing for exchange {long_exchange_db_id}.") # Non-retryable

        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError(f"Parent video record {video_id} not found.") # Non-retryable

        # Check prerequisite
        if exchange_data.get('clip_definition_status') != 'Complete':
            raise Ignore("Cannot cut clips: Clip definition step is not 'Complete'.") # Non-retryable state

        definitions_json = exchange_data.get('short_clip_definitions')
        if not definitions_json: raise ValueError("Short clip definitions missing in DB.") # Non-retryable

        # JSON parsing errors are not retryable
        short_clip_definitions = json.loads(definitions_json)
        if not isinstance(short_clip_definitions, list): raise ValueError("Parsed short clip definitions is not a list.") # Non-retryable

        if not short_clip_definitions:
            logger.info(f"No short clips defined for exchange {long_exchange_db_id}. Skipping cutting.")
            final_status = 'Skipped'
            # Jump directly to final status update
            db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=None)
            logger.info(f"--- {substep_name} Substep Task Finished (Skipped) for Exchange DB ID: {long_exchange_db_id} ---")
            return # Exit the task successfully

        # Proceed with cutting if definitions exist
        # Get video path (can raise retryable RuntimeError or non-retryable ValueError)
        source_video_path, _ = _get_required_path(video_id, 'video', substep_name)
        exchange_label = exchange_data.get('exchange_label', f'exch_{long_exchange_db_id}')

        short_clip_output_dir = os.path.join(config.PROCESSED_CLIPS_DIR, f"video_{video_id}", f"{exchange_label}")
        try:
            os.makedirs(short_clip_output_dir, exist_ok=True)
            logger.info(f"Output directory for short clips: {short_clip_output_dir}")
        except OSError as e:
             # Treat directory creation failure as potentially retryable
            raise RuntimeError(f"Failed to create output directory '{short_clip_output_dir}': {e}") from e

        total_clips = len(short_clip_definitions)
        logger.info(f"Starting to cut {total_clips} short clips for exchange {long_exchange_db_id}...")

        for idx, short_def in enumerate(short_clip_definitions):
            try:
                abs_start = short_def['absolute_start']; abs_end = short_def['absolute_end']
                speaker = short_def.get('speaker', 'UNK'); duration = short_def.get('duration', 0)

                start_str = f"{abs_start:.1f}".replace('.', 'p'); end_str = f"{abs_end:.1f}".replace('.', 'p')
                short_filename = f"clip_{idx}_{speaker}_{start_str}-{end_str}_v{video_id}e{long_exchange_db_id}.mp4"
                short_filename = media_utils.sanitize_filename(short_filename)
                short_output_path = os.path.join(short_clip_output_dir, short_filename)

                logger.info(f"Cutting clip {idx+1}/{total_clips}: {short_filename} ({duration:.2f}s)")
                # FFmpeg call can raise RuntimeError on failure, which is retryable
                short_cut_success, short_result = media_utils.create_clip(
                    source_video_path, short_output_path, abs_start, abs_end, re_encode=True
                )

                if short_cut_success:
                    successful_clips += 1
                    # Add generated clip path to the main video record (DB update might be retryable)
                    db.add_generated_clip(video_id, short_output_path)
                else:
                    failed_clips += 1
                    err_msg = f"Failed clip {idx+1}: {str(short_result)}"
                    logger.error(f"{err_msg} (Exchange: {long_exchange_db_id})")
                    error_messages.append(err_msg) # Collect errors but continue processing other clips

            except NON_RETRYABLE_EXCEPTIONS as clip_err: # Catch definition errors immediately
                failed_clips += 1
                err_msg = f"Invalid definition for clip {idx+1}: {clip_err}"
                logger.error(f"{err_msg} (Exchange: {long_exchange_db_id}) - Definition: {short_def}")
                error_messages.append(err_msg)
                continue # Skip to next clip definition

        # Determine final status after loop finishes
        if failed_clips == 0 and successful_clips > 0: final_status = 'Complete'
        elif failed_clips > 0 and successful_clips > 0: final_status = 'Completed with Errors'
        elif failed_clips > 0 and successful_clips == 0: final_status = 'Error'
        elif failed_clips == 0 and successful_clips == 0: final_status = 'Complete' # Should have been caught by 'Skipped' logic earlier unless all defs were invalid
        else: final_status = 'Error' # Fallback

        if error_messages:
             final_error_message = "; ".join(error_messages[:3]) + ('...' if len(error_messages) > 3 else '')
             logger.warning(f"{failed_clips} clip(s) failed for exchange {long_exchange_db_id}. Sample error: {final_error_message}")

        # Final DB update
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=final_error_message)
        logger.info(f"--- {substep_name} Substep Task Finished for Exchange DB ID: {long_exchange_db_id} --- Status: {final_status} (Success: {successful_clips}, Failed: {failed_clips})")

    except NON_RETRYABLE_EXCEPTIONS as e:
        logger.error(f"--- {substep_name} Substep Task NON-RETRYABLE FAIL for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        final_status = 'Error'
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=error_msg)
        raise Ignore()
    except Exception as e:
        logger.warning(f"--- {substep_name} Substep Task FAILED (Will Retry If Possible) for Exchange DB ID: {long_exchange_db_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        final_status = 'Error'
        error_msg = error_utils.format_error(e)
        # Update status with attempt number
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        raise e

# --- END OF FILE: tasks/exchange_tasks.py ---