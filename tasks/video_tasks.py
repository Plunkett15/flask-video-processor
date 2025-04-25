# --- Start of File: tasks/video_tasks.py ---
import logging
import os
import json
import time
from celery import Task # Import Task base class
from celery.exceptions import Ignore # Import Ignore for non-retryable errors

# Project specific imports
import database as db
from utils import download, media_utils, error_utils
# <<< MODIFIED: Import alignment utils, remove old exchange utils >>>
from analysis import transcription, diarization, alignment_utils
from config import Config

# --- Celery App Instance ---
from celery_app import celery_app

# Configure logger for this tasks module
logger = logging.getLogger(__name__)
config = Config()

# =============================================================================
# === Helper: Get Required Path (Copied for self-containment) ===
# =============================================================================
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
# === Phase 1 Celery Tasks (Video Level Processing) ===
# =============================================================================

# --- Retry Policy Defaults ---
RETRYABLE_EXCEPTIONS = (RuntimeError, ConnectionError, TimeoutError, OSError)
NON_RETRYABLE_EXCEPTIONS = (ValueError, TypeError, KeyError, json.JSONDecodeError)

@celery_app.task(
    bind=True,
    name='tasks.video_tasks.download_task',
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_kwargs={'max_retries': 3, 'countdown': 30}
)
def download_task(self: Task, video_id: int):
    """ (Celery Task) Downloads the video from YouTube with retries. """
    step_name = 'download'
    logger.info(f"--- Starting {step_name} Task (Attempt {self.request.retries + 1}) for Video ID: {video_id} ---")
    try:
        if self.request.retries == 0:
            db.update_video_step_status(video_id, step_name, 'Running')

        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError("Video record not found.")

        youtube_url = video_data.get('youtube_url'); resolution = video_data.get('resolution')
        target_base_path = video_data.get('file_path')
        if not target_base_path: raise ValueError("Target file path missing in DB.")

        output_dir = os.path.dirname(target_base_path)
        filename_base = os.path.splitext(os.path.basename(target_base_path))[0]
        if not output_dir or not filename_base: raise ValueError("Could not parse output directory/filename.")

        try:
             if not os.path.exists(output_dir):
                  os.makedirs(output_dir, exist_ok=True)
                  logger.info(f"Created download directory: {output_dir}")
        except OSError as dir_err:
            raise RuntimeError(f"Failed to create output directory '{output_dir}': {dir_err}") from dir_err

        dl_success, dl_error, actual_downloaded_path = download.download_video(
            youtube_url, output_dir, filename_base, resolution
        )

        if not dl_success: raise RuntimeError(f"Download Failed: {dl_error}")

        final_path = None
        if actual_downloaded_path and os.path.exists(actual_downloaded_path) and os.path.getsize(actual_downloaded_path) > 0:
            final_path = actual_downloaded_path
        elif os.path.exists(target_base_path) and os.path.getsize(target_base_path) > 0:
             final_path = target_base_path

        if not final_path: raise RuntimeError("Download reported success, but final video file missing/empty.")

        if final_path != target_base_path:
            path_update_ok = db.update_video_path(video_id, final_path)
            if not path_update_ok:
                raise Ignore(f"DB Error updating file path (likely UNIQUE conflict): {final_path}")

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} --- File: {final_path}")

    except NON_RETRYABLE_EXCEPTIONS as e:
         logger.error(f"--- {step_name} Task NON-RETRYABLE FAIL for Video ID: {video_id} --- Error: {e}", exc_info=True)
         error_msg = error_utils.format_error(e)
         db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
         raise Ignore()
    except Exception as e:
        logger.warning(f"--- {step_name} Task FAILED (Will Retry If Possible) for Video ID: {video_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        raise e


@celery_app.task(
    bind=True,
    name='tasks.video_tasks.extract_audio_task',
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_kwargs={'max_retries': 2, 'countdown': 15}
)
def extract_audio_task(self: Task, video_id: int):
    """ (Celery Task) Extracts audio from the video file, uses caching, with retries. """
    step_name = 'audio'
    logger.info(f"--- Starting {step_name} Task (Attempt {self.request.retries + 1}) for Video ID: {video_id} ---")
    audio_cache_path = None
    try:
        if self.request.retries == 0:
            db.update_video_step_status(video_id, step_name, 'Running')

        video_path, video_data = _get_required_path(video_id, 'video', step_name)

        video_dir = os.path.dirname(video_path)
        audio_cache_filename = "audio_16khz_mono.wav"
        audio_cache_path = os.path.join(video_dir, audio_cache_filename)
        logger.info(f"Target audio path (cache): {audio_cache_path}")

        if os.path.exists(audio_cache_path) and os.path.getsize(audio_cache_path) > 0:
            logger.info(f"Found valid cached audio: {audio_cache_path}. Skipping extraction.")
            if video_data.get('audio_path') != audio_cache_path:
                 db.update_video_audio_path(video_id, audio_cache_path)
        else:
            logger.info(f"Cached audio not found or invalid. Extracting to {audio_cache_path}...")
            start_time = time.time()
            success, error = media_utils.extract_audio(video_path, audio_cache_path, sample_rate=16000, channels=1)
            if not success:
                raise RuntimeError(f"Audio Extraction Failed: {error}")
            logger.info(f"Audio extraction successful ({time.time() - start_time:.2f}s).")
            db.update_video_audio_path(video_id, audio_cache_path)

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except NON_RETRYABLE_EXCEPTIONS as e:
         logger.error(f"--- {step_name} Task NON-RETRYABLE FAIL for Video ID: {video_id} --- Error: {e}", exc_info=True)
         error_msg = error_utils.format_error(e)
         db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
         raise Ignore()
    except Exception as e:
        logger.warning(f"--- {step_name} Task FAILED (Will Retry If Possible) for Video ID: {video_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        raise e


@celery_app.task(
    bind=True,
    name='tasks.video_tasks.transcribe_task',
    autoretry_for=RETRYABLE_EXCEPTIONS,
    retry_kwargs={'max_retries': 2, 'countdown': 60}
)
def transcribe_task(self: Task, video_id: int):
    """ (Celery Task) Transcribes the audio file, uses caching, with retries. """
    step_name = 'transcript'
    logger.info(f"--- Starting {step_name} Task (Attempt {self.request.retries + 1}) for Video ID: {video_id} ---")
    transcript_cache_path = None
    transcript_result_list = None
    try:
        if self.request.retries == 0:
            db.update_video_step_status(video_id, step_name, 'Running')

        audio_path, video_data = _get_required_path(video_id, 'audio', step_name)

        audio_dir = os.path.dirname(audio_path)
        transcript_cache_filename = "transcript.json"
        transcript_cache_path = os.path.join(audio_dir, transcript_cache_filename)
        logger.info(f"Transcript cache path: {transcript_cache_path}")

        cache_loaded = False
        if os.path.exists(transcript_cache_path) and os.path.getsize(transcript_cache_path) > 0:
            logger.info(f"Attempting to load cached transcript: {transcript_cache_path}")
            try:
                with open(transcript_cache_path, 'r', encoding='utf-8') as f:
                    transcript_result_list = json.load(f)
                if isinstance(transcript_result_list, list) and all(isinstance(seg, dict) for seg in transcript_result_list):
                    logger.info(f"Successfully loaded {len(transcript_result_list)} segments from cache.")
                    cache_loaded = True
                else:
                    logger.warning("Cached transcript file has invalid format. Re-transcribing.")
                    transcript_result_list = None
            except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to load/parse cached transcript: {e}. Re-transcribing.")
                transcript_result_list = None

        if not cache_loaded:
            logger.info(f"Starting transcription for audio: {os.path.basename(audio_path)}...")
            start_time = time.time()
            trans_success, transcript_segments_list_raw, trans_error = transcription.transcribe_audio(audio_path)
            if not trans_success: raise RuntimeError(f"Transcription Failed: {trans_error}")
            logger.info(f"Transcription successful ({time.time() - start_time:.2f}s). Processing results...")
            try:
                transcript_result_list = [{'start': seg.start, 'end': seg.end, 'text': seg.text} for seg in transcript_segments_list_raw]
                logger.info(f"Processed {len(transcript_result_list)} segments.")
                try:
                    if not os.path.exists(audio_dir):
                         os.makedirs(audio_dir, exist_ok=True)
                         logger.info(f"Created directory for transcript cache: {audio_dir}")
                    with open(transcript_cache_path, 'w', encoding='utf-8') as f:
                        json.dump(transcript_result_list, f, ensure_ascii=False, indent=2)
                    logger.info(f"Saved transcript result to cache: {transcript_cache_path}")
                except (IOError, TypeError, OSError) as e: logger.error(f"Failed to save transcript to cache (non-fatal): {e}")
            except Exception as proc_err:
                raise ValueError(f"Failed to process transcript segments: {proc_err}") from proc_err

        if transcript_result_list is not None:
            db.update_video_step_result(video_id, step_name, transcript_result_list)
        else:
             raise ValueError("Transcript result is unexpectedly None after processing.")

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except NON_RETRYABLE_EXCEPTIONS as e:
         logger.error(f"--- {step_name} Task NON-RETRYABLE FAIL for Video ID: {video_id} --- Error: {e}", exc_info=True)
         error_msg = error_utils.format_error(e)
         db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
         if 'transcript_result_list' in locals() and transcript_result_list is not None:
             db.update_video_step_result(video_id, step_name, None)
         raise Ignore()
    except Exception as e:
        logger.warning(f"--- {step_name} Task FAILED (Will Retry If Possible) for Video ID: {video_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        if 'transcript_result_list' in locals() and transcript_result_list is not None:
             db.update_video_step_result(video_id, step_name, None)
        raise e


@celery_app.task(
    bind=True,
    name='tasks.video_tasks.diarize_full_audio_task',
    autoretry_for=RETRYABLE_EXCEPTIONS + (ImportError,),
    retry_kwargs={'max_retries': 2, 'countdown': 60}
)
def diarize_full_audio_task(self: Task, video_id: int):
    """ (Celery Task) Performs speaker diarization on the full audio file, with retries. """
    step_name = 'diarization'
    logger.info(f"--- Starting {step_name} Task (Attempt {self.request.retries + 1}) for Video ID: {video_id} ---")
    try:
        if self.request.retries == 0:
            db.update_video_step_status(video_id, step_name, 'Running')

        audio_path, video_data = _get_required_path(video_id, 'audio', step_name)
        logger.info(f"Starting full audio diarization for: {os.path.basename(audio_path)}...")
        start_time = time.time()

        diar_success, segments_list, segments_json, diar_error = diarization.diarize_audio(audio_path)

        if not diar_success: raise RuntimeError(f"Diarization Failed: {diar_error}")
        if segments_json is None:
             raise ValueError("Diarization successful but failed to produce valid JSON result.")

        logger.info(f"Full audio diarization successful ({time.time() - start_time:.2f}s). Found {len(segments_list or [])} speaker turns.")
        db.update_video_step_result(video_id, step_name, segments_json)
        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except NON_RETRYABLE_EXCEPTIONS as e:
         logger.error(f"--- {step_name} Task NON-RETRYABLE FAIL for Video ID: {video_id} --- Error: {e}", exc_info=True)
         error_msg = error_utils.format_error(e)
         db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
         db.update_video_step_result(video_id, step_name, None)
         raise Ignore()
    except Exception as e:
        logger.warning(f"--- {step_name} Task FAILED (Will Retry If Possible) for Video ID: {video_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        db.update_video_step_result(video_id, step_name, None)
        raise e


# <<< MODIFIED: identify_exchanges_task >>>
@celery_app.task(
    bind=True,
    name='tasks.video_tasks.identify_exchanges_task',
    autoretry_for=(RuntimeError,), # Only retry runtime errors, not ValueErrors from bad data
    retry_kwargs={'max_retries': 1, 'countdown': 10}
)
def identify_exchanges_task(self: Task, video_id: int):
    """
    (Celery Task) Identifies long exchanges using speaker changes and simple
    question detection rules.
    """
    step_name = 'exchange_id'
    logger.info(f"--- Starting {step_name} Task (Attempt {self.request.retries + 1}) for Video ID: {video_id} ---")
    try:
        if self.request.retries == 0:
            db.update_video_step_status(video_id, step_name, 'Running')

        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError("Video record not found.")

        # --- Check Prerequisites ---
        if video_data.get('transcript_status') != 'Complete':
            raise Ignore("Prerequisite Failed: Transcript step is not 'Complete'.")
        if video_data.get('diarization_status') != 'Complete':
             # If diarization failed, we can't use speaker changes. Could fall back to keywords?
             # For now, treat it as a failure for this method.
            raise Ignore("Prerequisite Failed: Diarization step is not 'Complete'.")

        transcript_json = video_data.get('transcript')
        diarization_json = video_data.get('full_diarization_result')

        if not transcript_json: raise ValueError("Transcript data is missing in DB.")
        if not diarization_json: raise ValueError("Diarization data is missing in DB.")

        # --- Load Data ---
        try: transcript_segments = json.loads(transcript_json)
        except json.JSONDecodeError as e: raise ValueError(f"Failed to parse transcript JSON: {e}") from e
        try: diarization_segments = json.loads(diarization_json)
        except json.JSONDecodeError as e: raise ValueError(f"Failed to parse diarization JSON: {e}") from e

        if not transcript_segments:
            logger.warning(f"Transcript for video {video_id} is empty. Cannot identify exchanges.")
            db.update_video_step_status(video_id, step_name, 'Complete') # Mark as complete, no exchanges
            return # Exit successfully

        # --- Align Transcript and Diarization ---
        logger.info("Aligning transcript and diarization results...")
        start_time = time.time()
        # Use the alignment utility function
        aligned_segments = alignment_utils.align_transcript_diarization(transcript_segments, diarization_segments)
        logger.info(f"Alignment finished ({time.time() - start_time:.2f}s).")

        if not aligned_segments:
            logger.warning(f"Alignment resulted in empty segments for video {video_id}. Cannot identify exchanges.")
            db.update_video_step_status(video_id, step_name, 'Complete')
            return # Exit successfully

        # --- Identify Exchanges based on Speaker Change + Question Rule ---
        logger.info("Identifying exchanges based on speaker change + question rule...")
        start_time = time.time()
        potential_starts = [] # Store {'start_time': float, 'segment_index': int}
        current_speaker = None
        if aligned_segments: # Set initial speaker
             current_speaker = aligned_segments[0].get('speaker', 'UNKNOWN')

        for i, seg in enumerate(aligned_segments):
            speaker = seg.get('speaker', 'UNKNOWN')
            text = seg.get('text', '')
            seg_start = seg.get('start')

            if speaker != current_speaker and seg_start is not None:
                 # Speaker change detected! Check if the new speaker's segment is a question.
                 # Look ahead slightly? Maybe combine text from next few segments by same speaker? For now, just check current.
                 is_q = alignment_utils.is_likely_question(text)

                 if is_q:
                     logger.info(f"--> Potential exchange start: Speaker change to '{speaker}' at segment {i} ({seg_start:.2f}s) - likely question found.")
                     potential_starts.append({'start_time': seg_start, 'segment_index': i})
                 # else: logger.debug(f"Speaker change to '{speaker}' at seg {i}, but not flagged as question.")

                 current_speaker = speaker # Update current speaker

        # --- Define Exchange Boundaries ---
        long_exchange_definitions = []
        num_starts = len(potential_starts)
        logger.info(f"Found {num_starts} potential exchange starting points.")

        for k in range(num_starts):
            current_start_info = potential_starts[k]
            exchange_start_time = current_start_info['start_time']
            exchange_label = f"spkchg_{k}" # New label format

            # Determine end time: End is the start time of the *next* potential exchange,
            # or the end time of the very last segment if this is the last identified start.
            if k + 1 < num_starts:
                next_start_info = potential_starts[k+1]
                exchange_end_time = next_start_info['start_time']
            else:
                # Use the end time of the last segment in the *entire aligned transcript*
                last_aligned_segment = aligned_segments[-1]
                exchange_end_time = last_aligned_segment.get('end')
                if exchange_end_time is None:
                     logger.warning(f"Could not determine end time for last potential exchange {exchange_label} (last segment invalid). Skipping.")
                     continue

            # Basic validation and formatting
            if exchange_end_time > exchange_start_time:
                 duration = round(exchange_end_time - exchange_start_time, 3)
                 # Optional: Add minimum duration filter if needed
                 # if duration < min_exchange_duration: continue

                 long_exchange_definitions.append({
                     'id': exchange_label, # Use the generated label
                     'start': round(exchange_start_time, 3),
                     'end': round(exchange_end_time, 3),
                     'marker': None, # No keyword marker for this method
                     'duration': duration,
                 })
                 logger.debug(f"Defined Exchange {exchange_label}: {exchange_start_time:.3f}s - {exchange_end_time:.3f}s (Duration: {duration:.3f}s)")
            else:
                 logger.warning(f"Skipping potential exchange {exchange_label} starting at {exchange_start_time:.3f}s because calculated end time ({exchange_end_time:.3f}s) is not valid.")

        logger.info(f"Exchange identification logic finished ({time.time() - start_time:.2f}s). Defined {len(long_exchange_definitions)} exchanges.")

        # --- Update Database ---
        # Clear previous 'auto' exchanges (as this method replaces the keyword-based 'auto' type)
        db.clear_long_exchanges_for_video(video_id, type_filter='auto')
        if long_exchange_definitions:
            # Need to ensure db.add_long_exchanges can handle marker=None
            add_success = db.add_long_exchanges(video_id, long_exchange_definitions)
            if not add_success: raise RuntimeError("DB error adding/updating 'auto' exchange definitions.")
        else:
             logger.info(f"No exchanges identified or added for video {video_id} using speaker change method.")

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except NON_RETRYABLE_EXCEPTIONS as e:
         logger.error(f"--- {step_name} Task NON-RETRYABLE FAIL for Video ID: {video_id} --- Error: {e}", exc_info=True)
         error_msg = error_utils.format_error(e)
         db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
         raise Ignore()
    except Exception as e:
        logger.warning(f"--- {step_name} Task FAILED (Will Retry If Possible) for Video ID: {video_id} (Attempt {self.request.retries + 1}) --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"[Attempt {self.request.retries + 1}] {error_msg}")
        raise e

# --- END OF FILE: tasks/video_tasks.py ---