# --- Start of File: pipeline.py ---
import logging
import database as db # Module for database interactions (uses updated functions)
from utils import download, media_utils, error_utils # Utility modules
from analysis import transcription, diarization, exchange_segmentation # Analysis modules
import os
import json
import time
import datetime # Needed for short clip filename generation
from config import Config # Import configuration settings
from celery import group # Keep if needed for future parallelization

# Configure logger specifically for the pipeline module
logger = logging.getLogger(__name__)
config = Config() # Get config instance

# --- Celery Task Definition ---
from celery_app import celery_app

# =============================================================================
# === Helper: Get Required Path ===
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
    return file_path, video_data # Return path and the fetched data

# =============================================================================
# === Granular Celery Tasks ===
# =============================================================================

# --- Phase 1 Tasks ---

@celery_app.task(bind=True, name='pipeline.download_task')
def download_task(self, video_id):
    """ (Celery Task) Downloads the video from YouTube. """
    step_name = 'download'
    logger.info(f"--- Starting {step_name} Task for Video ID: {video_id} ---")
    try:
        db.update_video_step_status(video_id, step_name, 'Running')
        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError("Video record not found.")

        youtube_url = video_data.get('youtube_url'); resolution = video_data.get('resolution')
        # Use the file_path stored during initial job creation as the target base
        target_base_path = video_data.get('file_path')
        if not target_base_path: raise ValueError("Target file path missing in DB.")

        output_dir = os.path.dirname(target_base_path)
        filename_base = os.path.splitext(os.path.basename(target_base_path))[0]
        if not output_dir or not filename_base: raise ValueError("Could not parse output directory/filename from DB path.")

        dl_success, dl_error, actual_downloaded_path = download.download_video(
            youtube_url, output_dir, filename_base, resolution
        )

        if not dl_success: raise RuntimeError(f"Download Failed: {dl_error}")

        # Verify final path and update DB if downloader used a different extension/name
        final_path = None
        if actual_downloaded_path and os.path.exists(actual_downloaded_path) and os.path.getsize(actual_downloaded_path) > 0:
            final_path = actual_downloaded_path
        elif os.path.exists(target_base_path) and os.path.getsize(target_base_path) > 0:
             # Check if the original path is now valid (e.g., if hook failed but download worked)
             final_path = target_base_path

        if not final_path: raise RuntimeError("Download reported success, but final video file missing/empty.")

        if final_path != target_base_path:
            db.update_video_path(video_id, final_path) # Update path in DB

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} --- File: {final_path}")

    except Exception as e:
        logger.error(f"--- {step_name} Task FAILED for Video ID: {video_id} --- Error: {e}", exc_info=True)
        # Format error before storing
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)

@celery_app.task(bind=True, name='pipeline.extract_audio_task')
def extract_audio_task(self, video_id):
    """ (Celery Task) Extracts audio from the video file, uses caching. """
    step_name = 'audio'
    logger.info(f"--- Starting {step_name} Task for Video ID: {video_id} ---")
    audio_cache_path = None
    try:
        db.update_video_step_status(video_id, step_name, 'Running')
        # Get video path, raising error if missing/invalid
        video_path, video_data = _get_required_path(video_id, 'video', step_name)

        # Define cache path within the video's download directory
        video_dir = os.path.dirname(video_path)
        audio_cache_filename = "audio_16khz_mono.wav" # Standardized cache name
        audio_cache_path = os.path.join(video_dir, audio_cache_filename)
        logger.info(f"Target audio path (cache): {audio_cache_path}")

        # Check Cache
        if os.path.exists(audio_cache_path) and os.path.getsize(audio_cache_path) > 0:
            logger.info(f"Found valid cached audio: {audio_cache_path}. Skipping extraction.")
            # Ensure path is stored in DB if it wasn't (e.g., previous run failed after extraction)
            if video_data.get('audio_path') != audio_cache_path:
                 db.update_video_audio_path(video_id, audio_cache_path)
        else:
            # Cache Miss - Extract Audio
            logger.info(f"Cached audio not found or invalid. Extracting to {audio_cache_path}...")
            start_time = time.time()
            success, error = media_utils.extract_audio(video_path, audio_cache_path, sample_rate=16000, channels=1)
            if not success: raise RuntimeError(f"Audio Extraction Failed: {error}")
            logger.info(f"Audio extraction successful ({time.time() - start_time:.2f}s).")
            # Store path in DB *after* successful extraction
            db.update_video_audio_path(video_id, audio_cache_path)

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except Exception as e:
        logger.error(f"--- {step_name} Task FAILED for Video ID: {video_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)


@celery_app.task(bind=True, name='pipeline.transcribe_task')
def transcribe_task(self, video_id):
    """ (Celery Task) Transcribes the audio file, uses caching. """
    step_name = 'transcript'
    logger.info(f"--- Starting {step_name} Task for Video ID: {video_id} ---")
    transcript_cache_path = None
    transcript_result_list = None
    try:
        db.update_video_step_status(video_id, step_name, 'Running')
        # Get audio path, raising error if missing/invalid
        audio_path, video_data = _get_required_path(video_id, 'audio', step_name)

        # Define cache path
        audio_dir = os.path.dirname(audio_path)
        transcript_cache_filename = "transcript.json" # Standardized cache name
        transcript_cache_path = os.path.join(audio_dir, transcript_cache_filename)
        logger.info(f"Transcript cache path: {transcript_cache_path}")

        # Check Cache
        cache_loaded = False
        if os.path.exists(transcript_cache_path) and os.path.getsize(transcript_cache_path) > 0:
            logger.info(f"Attempting to load cached transcript: {transcript_cache_path}")
            try:
                with open(transcript_cache_path, 'r', encoding='utf-8') as f:
                    transcript_result_list = json.load(f)
                # Basic validation
                if isinstance(transcript_result_list, list) and all(isinstance(seg, dict) for seg in transcript_result_list):
                    logger.info(f"Successfully loaded {len(transcript_result_list)} segments from cache.")
                    cache_loaded = True
                else:
                    logger.warning("Cached transcript file has invalid format. Re-transcribing.")
                    transcript_result_list = None # Invalidate bad data
            except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to load/parse cached transcript: {e}. Re-transcribing.")
                transcript_result_list = None

        # Run Transcription if Cache Missed
        if not cache_loaded:
            logger.info(f"Starting transcription for audio: {os.path.basename(audio_path)}...")
            start_time = time.time()
            trans_success, transcript_segments_list_raw, trans_error = transcription.transcribe_audio(audio_path)
            if not trans_success: raise RuntimeError(f"Transcription Failed: {trans_error}")
            logger.info(f"Transcription successful ({time.time() - start_time:.2f}s). Processing results...")
            try:
                # Process raw segments into list of dicts
                transcript_result_list = [{'start': seg.start, 'end': seg.end, 'text': seg.text} for seg in transcript_segments_list_raw]
                logger.info(f"Processed {len(transcript_result_list)} segments.")
                # Save to Cache
                try:
                    with open(transcript_cache_path, 'w', encoding='utf-8') as f:
                        json.dump(transcript_result_list, f, ensure_ascii=False, indent=2)
                    logger.info(f"Saved transcript result to cache: {transcript_cache_path}")
                except (IOError, TypeError) as e: logger.error(f"Failed to save transcript to cache: {e}") # Non-fatal error
            except Exception as proc_err: raise RuntimeError(f"Failed to process transcript segments: {proc_err}")

        # Store result in DB (regardless of source: cache or new)
        if transcript_result_list is not None:
            db.update_video_step_result(video_id, step_name, transcript_result_list)
        else:
             # This case indicates a failure even if transcription itself didn't error
             raise RuntimeError("Transcript result is unexpectedly None after processing.")

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except Exception as e:
        logger.error(f"--- {step_name} Task FAILED for Video ID: {video_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
        # Also clear potentially partial results
        if 'transcript_result_list' in locals(): # Check if defined before error
             db.update_video_step_result(video_id, step_name, None)

@celery_app.task(bind=True, name='pipeline.diarize_full_audio_task')
def diarize_full_audio_task(self, video_id):
    """ (Celery Task) Performs speaker diarization on the full audio file. """
    step_name = 'diarization'
    logger.info(f"--- Starting {step_name} Task for Video ID: {video_id} ---")
    try:
        db.update_video_step_status(video_id, step_name, 'Running')
        # Get audio path, raising error if missing/invalid
        audio_path, video_data = _get_required_path(video_id, 'audio', step_name)
        logger.info(f"Starting full audio diarization for: {os.path.basename(audio_path)}...")
        start_time = time.time()

        # Run Diarization
        diar_success, segments_list, segments_json, diar_error = diarization.diarize_audio(audio_path)

        # Note: diarize_audio returns success=False if pipeline fails to load/run,
        # but success=True even if no speakers are found (segments_list is empty).
        if not diar_success:
            # If diar_success is False, diar_error should contain the message.
            raise RuntimeError(f"Diarization Failed: {diar_error}")
        # If success is True, segments_json should contain the JSON string (even '[]')
        if segments_json is None:
             # This case shouldn't happen if diar_success is True based on diarization.py logic
             logger.error(f"Internal inconsistency: Diarization reported success but JSON result is None for video {video_id}.")
             raise RuntimeError("Diarization successful but failed to produce valid JSON result.")

        logger.info(f"Full audio diarization successful ({time.time() - start_time:.2f}s). Found {len(segments_list or [])} speaker turns.")
        # Store the JSON result
        db.update_video_step_result(video_id, step_name, segments_json)
        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except Exception as e:
        logger.error(f"--- {step_name} Task FAILED for Video ID: {video_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)
        # Clear potentially partial results
        db.update_video_step_result(video_id, step_name, None)


@celery_app.task(bind=True, name='pipeline.identify_exchanges_task')
def identify_exchanges_task(self, video_id):
    """ (Celery Task) Identifies long exchanges based on transcript markers (Auto-Detect). """
    step_name = 'exchange_id'
    logger.info(f"--- Starting {step_name} Task for Video ID: {video_id} ---")
    try:
        db.update_video_step_status(video_id, step_name, 'Running')
        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError("Video record not found.")

        # Check transcript status
        if video_data.get('transcript_status') != 'Complete':
            raise RuntimeError("Cannot identify exchanges: Transcript step is not 'Complete'.")

        transcript_json = video_data.get('transcript')
        if not transcript_json: raise ValueError("Transcript data is missing in DB.")

        try: transcript_segments = json.loads(transcript_json)
        except json.JSONDecodeError: raise ValueError("Failed to parse transcript JSON from DB.")

        if not transcript_segments: logger.warning(f"Transcript for video {video_id} is empty. No exchanges will be identified."); long_exchange_definitions = []
        else:
            logger.info(f"Identifying exchanges from {len(transcript_segments)} transcript segments...")
            start_time = time.time()
            long_exchange_definitions = exchange_segmentation.identify_long_exchanges(transcript_segments)
            logger.info(f"Exchange identification finished ({time.time() - start_time:.2f}s). Found {len(long_exchange_definitions)} exchanges.")

        # Clear previous 'auto' exchanges and add new ones
        db.clear_long_exchanges_for_video(video_id, type_filter='auto')
        if long_exchange_definitions:
            add_success = db.add_long_exchanges(video_id, long_exchange_definitions)
            if not add_success: raise RuntimeError("DB error adding/updating 'auto' exchange definitions.")
        else:
             logger.info(f"No 'auto' exchanges identified or added for video {video_id}.")

        db.update_video_step_status(video_id, step_name, 'Complete')
        logger.info(f"--- {step_name} Task SUCCESS for Video ID: {video_id} ---")

    except Exception as e:
        logger.error(f"--- {step_name} Task FAILED for Video ID: {video_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=error_msg)


# --- Phase 2 Tasks ---

@celery_app.task(bind=True, name='pipeline.process_exchange_diarization_task')
def process_exchange_diarization_task(self, long_exchange_db_id):
    """ (Celery Task) Filters full diarization result for a specific exchange. """
    substep_name = 'diarization' # Matches the substep status/error columns
    logger.info(f"--- Starting {substep_name} Substep Task for Exchange DB ID: {long_exchange_db_id} ---")
    filtered_diar_result = None # Define for potential error clearing
    try:
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')
        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.")
        video_id = exchange_data['video_id']
        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError(f"Parent video {video_id} not found.")

        # Check prerequisite: Full diarization must be complete
        if video_data.get('diarization_status') != 'Complete':
            raise RuntimeError("Cannot process exchange diarization: Parent video full diarization is not 'Complete'.")

        full_diar_json = video_data.get('full_diarization_result')
        if not full_diar_json: raise ValueError("Full diarization result missing in DB.")

        try: full_diar_segments = json.loads(full_diar_json)
        except json.JSONDecodeError: raise ValueError("Failed to parse full diarization JSON from DB.")

        exchange_start = exchange_data.get('start_time'); exchange_end = exchange_data.get('end_time')
        if exchange_start is None or exchange_end is None: raise ValueError("Exchange start/end times missing.")

        logger.info(f"Filtering full diarization ({len(full_diar_segments)} segments) for exchange {long_exchange_db_id} ({exchange_start:.3f}s - {exchange_end:.3f}s)")
        filtered_diar_result = []
        # Tolerance for matching segment boundaries (optional)
        tolerance = 0.01
        for seg in full_diar_segments:
             seg_start = seg.get('start'); seg_end = seg.get('end')
             if seg_start is None or seg_end is None: continue
             # Check for overlap: segment starts before exchange ends AND segment ends after exchange starts
             if seg_start < (exchange_end + tolerance) and seg_end > (exchange_start - tolerance):
                  # Adjust start/end times relative to exchange start? Or keep absolute? Keep absolute for now.
                  # Optionally, clip segment times to exchange boundaries if they extend beyond
                  clipped_start = max(seg_start, exchange_start)
                  clipped_end = min(seg_end, exchange_end)
                  # Only include if the clipped segment has positive duration
                  if clipped_end > clipped_start:
                       new_seg = seg.copy() # Avoid modifying original list
                       new_seg['start'] = round(clipped_start, 3)
                       new_seg['end'] = round(clipped_end, 3)
                       filtered_diar_result.append(new_seg)

        logger.info(f"Found {len(filtered_diar_result)} diarization segments within exchange boundaries.")
        # Store the filtered result
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, filtered_diar_result)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Complete')
        logger.info(f"--- {substep_name} Substep Task SUCCESS for Exchange DB ID: {long_exchange_db_id} ---")

    except Exception as e:
        logger.error(f"--- {substep_name} Substep Task FAILED for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=error_msg)
        # Clear potentially partial results
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)


@celery_app.task(bind=True, name='pipeline.define_short_clips_task')
def define_short_clips_task(self, long_exchange_db_id):
    """ (Celery Task) Defines short clips based on processed exchange diarization. """
    substep_name = 'clip_definition'
    logger.info(f"--- Starting {substep_name} Substep Task for Exchange DB ID: {long_exchange_db_id} ---")
    short_clip_definitions = None # Define for potential error clearing
    try:
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')
        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.")

        # Check prerequisite
        if exchange_data.get('diarization_status') != 'Complete':
             raise RuntimeError("Cannot define short clips: Exchange diarization processing is not 'Complete'.")

        diar_result_json = exchange_data.get('diarization_result')
        # It's okay if diar_result_json is '[]' (empty list)
        if diar_result_json is None: raise ValueError("Exchange diarization result is missing in DB.")

        try: exchange_diar_segments = json.loads(diar_result_json)
        except json.JSONDecodeError: raise ValueError("Failed to parse exchange diarization JSON from DB.")

        # Assume define_short_clips_from_diarization needs absolute times
        # The helper function should be adapted if it expects relative times
        # Current helper `define_short_clips_from_diarization` takes absolute segments and *offset*
        # Needs rework: either pass absolute segments here, or rework helper
        # Let's adapt the call here: we already have absolute times in exchange_diar_segments
        # Helper function rework (simplified call):
        def define_short_clips(diarization_segments):
            definitions = []
            if not diarization_segments: return definitions
            min_dur = config.CLIP_MIN_DURATION_SECONDS
            max_dur = config.CLIP_MAX_DURATION_SECONDS
            for seg in diarization_segments:
                 try:
                     start = float(seg['start']); end = float(seg['end']); label = seg.get('label', 'UNKNOWN')
                     duration = end - start
                     if min_dur <= duration <= max_dur:
                         definitions.append({
                             'absolute_start': round(start, 3), # Already absolute
                             'absolute_end': round(end, 3),     # Already absolute
                             'speaker': label,
                             'duration': round(duration, 3)
                         })
                 except (KeyError, TypeError, ValueError) as e: logger.warning(f"Skipping invalid diar segment: {seg} - Error: {e}")
            return definitions

        logger.info(f"Defining short clips from {len(exchange_diar_segments)} processed diarization segments for exchange {long_exchange_db_id}.")
        short_clip_definitions = define_short_clips(exchange_diar_segments)
        logger.info(f"Defined {len(short_clip_definitions)} short clips meeting criteria.")

        # Store the definitions
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, short_clip_definitions)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Complete')
        logger.info(f"--- {substep_name} Substep Task SUCCESS for Exchange DB ID: {long_exchange_db_id} ---")

    except Exception as e:
        logger.error(f"--- {substep_name} Substep Task FAILED for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Error', error_message=error_msg)
        # Clear potentially partial results
        db.update_exchange_substep_result(long_exchange_db_id, substep_name, None)


@celery_app.task(bind=True, name='pipeline.cut_short_clips_task')
def cut_short_clips_task(self, long_exchange_db_id):
    """ (Celery Task) Cuts the defined short clips using FFmpeg. """
    substep_name = 'clip_cutting'
    logger.info(f"--- Starting {substep_name} Substep Task for Exchange DB ID: {long_exchange_db_id} ---")
    failed_clips = 0; successful_clips = 0
    final_status = 'Pending' # Should be updated
    error_messages = []

    try:
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, 'Running')
        exchange_data = db.get_long_exchange_by_id(long_exchange_db_id)
        if not exchange_data: raise ValueError("Exchange record not found.")
        video_id = exchange_data['video_id']
        video_data = db.get_video_by_id(video_id)
        if not video_data: raise ValueError(f"Parent video {video_id} not found.")

        # Check prerequisite
        if exchange_data.get('clip_definition_status') != 'Complete':
            raise RuntimeError("Cannot cut clips: Clip definition step is not 'Complete'.")

        definitions_json = exchange_data.get('short_clip_definitions')
        if not definitions_json: raise ValueError("Short clip definitions missing in DB.")

        try: short_clip_definitions = json.loads(definitions_json)
        except json.JSONDecodeError: raise ValueError("Failed to parse short clip definitions JSON from DB.")

        if not isinstance(short_clip_definitions, list): raise ValueError("Parsed short clip definitions is not a list.")

        if not short_clip_definitions:
            logger.info(f"No short clips defined for exchange {long_exchange_db_id}. Skipping cutting.")
            final_status = 'Skipped'
        else:
            source_video_path, _ = _get_required_path(video_id, 'video', substep_name) # Get video path
            exchange_label = exchange_data.get('exchange_label', f'exch_{long_exchange_db_id}')

            # Create output directory: processed_clips/video_<vid>/<exchange_label>/
            short_clip_output_dir = os.path.join(config.PROCESSED_CLIPS_DIR, f"video_{video_id}", f"{exchange_label}")
            try:
                os.makedirs(short_clip_output_dir, exist_ok=True)
                logger.info(f"Output directory for short clips: {short_clip_output_dir}")
            except OSError as e: raise RuntimeError(f"Failed to create output directory '{short_clip_output_dir}': {e}")

            total_clips = len(short_clip_definitions)
            logger.info(f"Starting to cut {total_clips} short clips for exchange {long_exchange_db_id}...")

            for idx, short_def in enumerate(short_clip_definitions):
                # Update status frequently (optional, maybe less frequent)
                # db.update_exchange_substep_status(long_exchange_db_id, substep_name, f'Running ({idx+1}/{total_clips})')

                try:
                    abs_start = short_def['absolute_start']; abs_end = short_def['absolute_end']
                    speaker = short_def.get('speaker', 'UNK'); duration = short_def.get('duration', 0)

                    # Filename construction
                    start_str = f"{abs_start:.1f}".replace('.', 'p'); end_str = f"{abs_end:.1f}".replace('.', 'p')
                    # Make unique: idx_speaker_start_end_vid_exch.mp4
                    short_filename = f"clip_{idx}_{speaker}_{start_str}-{end_str}_v{video_id}e{long_exchange_db_id}.mp4"
                    # Sanitize just in case speaker label has odd chars
                    short_filename = media_utils.sanitize_filename(short_filename)
                    short_output_path = os.path.join(short_clip_output_dir, short_filename)

                    logger.info(f"Cutting clip {idx+1}/{total_clips}: {short_filename} ({duration:.2f}s)")
                    short_cut_success, short_result = media_utils.create_clip(
                        source_video_path, short_output_path, abs_start, abs_end, re_encode=True
                    )

                    if short_cut_success:
                        successful_clips += 1
                        # Add generated clip path to the main video record
                        db.add_generated_clip(video_id, short_output_path)
                    else:
                        failed_clips += 1
                        err_msg = f"Failed clip {idx+1}: {short_result}"
                        logger.error(f"{err_msg} (Exchange: {long_exchange_db_id})")
                        error_messages.append(err_msg) # Collect errors

                except (KeyError, ValueError, TypeError) as clip_err:
                    failed_clips += 1
                    err_msg = f"Invalid definition for clip {idx+1}: {clip_err}"
                    logger.error(f"{err_msg} (Exchange: {long_exchange_db_id}) - Definition: {short_def}")
                    error_messages.append(err_msg)
                    continue # Skip to next clip definition

            # Determine final status based on outcomes
            if failed_clips == 0 and successful_clips > 0: final_status = 'Complete'
            elif failed_clips > 0 and successful_clips > 0: final_status = 'Completed with Errors'
            elif failed_clips > 0 and successful_clips == 0: final_status = 'Error'
            elif failed_clips == 0 and successful_clips == 0: final_status = 'Complete' # No clips to cut, technically complete
            else: final_status = 'Error' # Should not happen

        # Update final status and potentially aggregated error messages
        final_error_message = None
        if error_messages:
             # Join first few errors for summary
             final_error_message = "; ".join(error_messages[:3]) + ('...' if len(error_messages) > 3 else '')
             logger.warning(f"{failed_clips} clip(s) failed for exchange {long_exchange_db_id}. Sample error: {final_error_message}")

        db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=final_error_message)
        logger.info(f"--- {substep_name} Substep Task Finished for Exchange DB ID: {long_exchange_db_id} --- Status: {final_status} (Success: {successful_clips}, Failed: {failed_clips})")

    except Exception as e:
        final_status = 'Error'
        logger.error(f"--- {substep_name} Substep Task FAILED for Exchange DB ID: {long_exchange_db_id} --- Error: {e}", exc_info=True)
        error_msg = error_utils.format_error(e)
        db.update_exchange_substep_status(long_exchange_db_id, substep_name, final_status, error_message=error_msg)

# --- END OF FILE: pipeline.py ---