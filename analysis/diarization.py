# --- Start of File: analysis/diarization.py ---
import logging
import torch
import os
import json
import time
import threading # Used for thread-safe pipeline loading
from pyannote.audio import Pipeline # The core diarization pipeline class
from pyannote.core import Annotation # Type hint for clarity
from config import Config # Application configuration settings

logger = logging.getLogger(__name__)

# ================================================
# === Pipeline Loading (Lazy Initialization) ===
# ================================================
# Similar to transcription, we use lazy initialization for the Pyannote pipeline.
# Diarization models can also be large and require authentication, so loading
# only when needed saves resources and avoids startup delays/errors if not used.

# Global variable to hold the single pipeline instance. Initialized to None.
_pipeline_instance: Pipeline | None = None # Type hint for clarity
# Thread lock: Ensures only one thread loads the pipeline at a time.
_pipeline_load_lock = threading.Lock()

def _load_pipeline() -> Pipeline | None:
    """
    Loads the Pyannote pipeline instance if it hasn't been loaded yet. Thread-safe.
    Handles authentication using the Hugging Face token from config.

    Uses the same double-checked locking pattern as the transcription model loading.

    Returns:
        Pipeline | None: The loaded pipeline instance, or None if loading fails (e.g., bad token, model not found).
                        Returning None signals to the caller that diarization should be skipped.
    """
    global _pipeline_instance
    # --- Fast path check ---
    if _pipeline_instance:
        return _pipeline_instance

    # --- Acquire lock for potential loading ---
    with _pipeline_load_lock:
        # --- Second check (after acquiring lock) ---
        if _pipeline_instance:
            return _pipeline_instance

        # --- Load Pipeline ---
        logger.info("Attempting to load Pyannote diarization pipeline (first diarization request or reload)...")
        config = Config()
        hf_token = config.HUGGING_FACE_TOKEN
        pipeline_name = config.PYANNOTE_PIPELINE
        # Determine device ('cuda' or 'cpu') based on global config and availability.
        # Pyannote uses PyTorch, so Config.DEVICE should align.
        try:
            device = torch.device(config.DEVICE)
        except Exception as device_err:
            logger.error(f"Failed to create torch device '{config.DEVICE}': {device_err}. Defaulting to CPU.")
            device = torch.device("cpu")

        # --- CRITICAL: Check for Hugging Face Token ---
        # Pyannote pipelines require authentication for model access.
        if not hf_token:
            logger.critical("CRITICAL: Hugging Face Token (HUGGING_FACE_TOKEN) is missing in config/.env.")
            logger.critical("Pyannote pipeline loading REQUIRES this token.")
            logger.critical("Diarization steps will be skipped.")
            _pipeline_instance = None # Ensure instance remains None
            return None # Signal loading failure

        logger.info(f"Pipeline: '{pipeline_name}', Target Device: '{device}'. Using Hugging Face Token: Yes")
        logger.info("Model weights may be downloaded from Hugging Face Hub if not cached.")
        start_time = time.time()

        try:
            # --- Initialize the Pipeline ---
            # `from_pretrained` downloads/loads the specified pipeline.
            # `use_auth_token` passes the HF token for authentication.
            pipeline: Pipeline = Pipeline.from_pretrained(
                pipeline_name,
                use_auth_token=hf_token
            )

            # --- Move Pipeline to Target Device ---
            # Attempt to move the pipeline's components (models) to the configured device (GPU or CPU).
            try:
                 pipeline.to(device)
                 logger.info(f"Pyannote pipeline components successfully moved to device: {device}")
            except Exception as move_err:
                # Log error but potentially allow fallback to CPU if possible (depends on error)
                logger.error(f"Failed to move Pyannote pipeline to device '{device}': {move_err}. Pipeline might run on CPU or fail later.", exc_info=True)

            # Optional: Check pipeline state after loading/moving?
            # logger.debug(f"Pipeline device state after load/move: {pipeline.device}") # Actual device might vary

            load_time = time.time() - start_time
            logger.info(f"Pyannote pipeline '{pipeline_name}' loaded successfully in {load_time:.2f} seconds.")
            _pipeline_instance = pipeline # Assign to the global variable
            return _pipeline_instance

        # --- Handle Specific Loading Errors ---
        except ImportError as e:
             logger.critical(f"ImportError loading Pyannote - dependency likely missing: {e}", exc_info=True)
             _pipeline_instance = None
             return None # Indicate failure
        except ValueError as e:
            # E.g., Invalid pipeline name format in config.
            logger.critical(f"ValueError loading pipeline (invalid name '{pipeline_name}'?): {e}", exc_info=True)
            _pipeline_instance = None
            return None
        except Exception as e:
            # Handle common errors related to Hugging Face Hub access/authentication.
            msg = str(e)
            # Check for authentication errors (401/403) or specific messages.
            if "401" in msg or "403" in msg or "User Access Registration Required" in msg or "authentication" in msg.lower():
                 # Construct likely model page URL for user to check terms.
                 hf_model_id = pipeline_name.replace('@', '/') # Convert 'name@version' to 'name/version' if needed
                 hf_url = f"https://huggingface.co/{hf_model_id}"
                 logger.critical(f"Authentication FAILED for Pyannote model '{pipeline_name}'.")
                 logger.critical("1. Ensure HUGGING_FACE_TOKEN in .env is correct and has 'read' permissions.")
                 logger.critical(f"2. CRITICAL: Ensure you have accepted the model's terms of use on Hugging Face: {hf_url}")
            # Check for model not found errors.
            elif "not found" in msg.lower() or "repository not found" in msg.lower():
                 logger.critical(f"Pyannote pipeline model '{pipeline_name}' NOT FOUND on Hugging Face Hub. Check spelling and version in config.")
            # Check for network connection errors.
            elif "connection error" in msg.lower() or "timed out" in msg.lower() or "offline" in msg.lower():
                 logger.critical(f"Network error connecting to Hugging Face Hub to download/verify '{pipeline_name}': {e}")
            else:
                 # Log other unexpected errors with full traceback.
                 logger.critical(f"Unexpected error loading Pyannote pipeline '{pipeline_name}': {e}", exc_info=True)

            _pipeline_instance = None # Ensure instance is None on any load failure
            return None # Indicate failure

# ================================================
# === Main Diarization Function ===
# ================================================
def diarize_audio(audio_path) -> tuple[bool, list | None, str | None, str | None]:
    """
    Performs speaker diarization on the audio file using the loaded Pyannote pipeline.

    Args:
        audio_path (str): Path to the audio file (WAV format, 16kHz mono recommended for most Pyannote pipelines).

    Returns:
        tuple: (success (bool), segments_list (list[dict] | None), segments_json (str | None), error_message (str | None))
               - success: True if diarization completed successfully (even if no speakers were found), False on critical error.
               - segments_list: List of dictionaries [{'start': float, 'end': float, 'label': str}] on success, None on failure.
               - segments_json: JSON string representation of segments_list on success, None on failure.
               - error_message: String describing the error if success is False, otherwise None.
    """
    # --- Input Validation ---
    if not os.path.exists(audio_path):
        err = f"Audio file not found for diarization: {audio_path}"
        logger.error(err)
        return False, None, None, err
    if os.path.getsize(audio_path) == 0:
         err = f"Audio file is empty (0 bytes), cannot diarize: {audio_path}"
         logger.error(err)
         return False, None, None, err
    # Note: Pyannote pipelines often expect specific audio formats (e.g., 16kHz mono WAV).
    # The audio extraction step should ideally produce this format.

    logger.info(f"Starting speaker diarization for: {os.path.basename(audio_path)}")
    diarization_start_time = time.time()

    try:
        # --- Get Pipeline Instance ---
        # This attempts to load the pipeline if not already loaded.
        pipeline = _load_pipeline()
        # Check if loading failed (e.g., missing token). _load_pipeline logs critical errors.
        if pipeline is None:
             # Signal failure for this step as the pipeline isn't available.
             err_msg = "Pyannote diarization pipeline is not available (failed to load/authenticate)."
             logger.warning(f"{err_msg} Skipping diarization for {os.path.basename(audio_path)}.")
             # Return False for success, but provide the error message.
             # The pipeline can continue without speaker info if designed to handle it.
             return False, None, None, err_msg

        config = Config() # For logging config details during execution
        pipeline_device = pipeline.device # Get the actual device the pipeline is on
        logger.info(f"Applying diarization pipeline '{config.PYANNOTE_PIPELINE}' on device '{pipeline_device}'...")

        # --- Run Diarization Pipeline ---
        # The pipeline object is callable and takes the audio path as input.
        # Optional: Provide hints like number of speakers if known.
        try:
            # For PyTorch >= 2.0, `torch.compile` might speed up inference, but needs testing.
            # pipeline_compiled = torch.compile(pipeline) # Example
            # diarization_annotation: Annotation = pipeline_compiled(audio_path, ...)
            diarization_annotation: Annotation = pipeline(
                audio_path,
                # num_speakers=2,      # Optional: Provide known speaker count if available
                # min_speakers=1,      # Optional: Constrain expected speaker count
                # max_speakers=5,
            )
            # This call performs the main diarization computation.
        except Exception as pipeline_exec_err:
            # Catch errors specifically during pipeline *execution* (vs. loading).
            # These might be related to audio format issues, resource limits, etc.
             logger.error(f"Error occurred during Pyannote pipeline execution for '{audio_path}': {pipeline_exec_err}", exc_info=True)
             err_msg = f"Pyannote pipeline execution failed: {pipeline_exec_err}"
             return False, None, None, err_msg # Return failure

        processing_time = time.time() - diarization_start_time
        logger.info(f"Diarization computation finished in {processing_time:.2f} seconds.")

        # --- Process Output Annotation ---
        segments_list = [] # Initialize list to store processed segments
        # The result `diarization_annotation` is a Pyannote Annotation object.
        # It might be empty or None if no speech/speakers were detected.
        if diarization_annotation:
             # Iterate through speaker turns using itertracks().
             # `yield_label=True` provides the speaker label (e.g., 'SPEAKER_00').
             rounding_digits = 3 # Round timestamps for cleaner output (milliseconds)
             num_turns_raw = 0
             filtered_short_turns = 0
             # Define a minimum duration to filter out very short, potentially noisy segments.
             min_turn_duration = 0.1 # seconds (e.g., 100ms)

             for turn, track_id, speaker_label in diarization_annotation.itertracks(yield_label=True):
                 num_turns_raw += 1
                 segment_duration = turn.end - turn.start
                 # Filter out segments shorter than the minimum duration.
                 if segment_duration >= min_turn_duration:
                     segments_list.append({
                         "start": round(turn.start, rounding_digits),
                         "end": round(turn.end, rounding_digits),
                         "label": speaker_label # Pyannote's assigned speaker ID
                         # 'track_id': track_id # Could include track ID if needed
                     })
                 else:
                     filtered_short_turns += 1
                     # Log filtered turns sparingly if there are many.
                     # logger.debug(f"Skipping short diarization turn: {speaker_label} "
                     #             f"[{turn.start:.3f}-{turn.end:.3f}], duration={segment_duration:.3f}s")

             # Log summary of diarization results.
             speaker_labels_found = diarization_annotation.labels() # Get unique speaker labels found
             num_speakers_found = len(speaker_labels_found)
             logger.info(f"Processed diarization results: Found {num_speakers_found} distinct speaker label(s): {speaker_labels_found}")
             logger.info(f"Extracted {len(segments_list)} speaker segments (filtered {filtered_short_turns}/{num_turns_raw} turns shorter than {min_turn_duration}s).")
        else:
            # Handle cases where the pipeline ran but returned an empty result.
            logger.warning(f"Diarization result annotation was empty for {audio_path}. No speaker turns detected (audio might be silent, contain non-speech, or only one speaker?).")
            # segments_list remains empty []

        # --- Serialize Results to JSON ---
        # Convert the list of segment dictionaries into a JSON string for storage in the database.
        segments_json = None
        try:
             # Use `allow_nan=False` for better JSON standard compliance.
             segments_json = json.dumps(segments_list, allow_nan=False)
        except (TypeError, ValueError) as json_err:
             # Handle errors during JSON serialization.
             logger.error(f"Failed to serialize processed diarization segments to JSON: {json_err}", exc_info=True)
             # If results can't be stored reliably, signal an error for this step.
             err_msg = f"JSON serialization error for diarization results: {json_err}"
             # Return the list itself, but indicate failure and provide no JSON string.
             return False, segments_list, None, err_msg

        # --- Success ---
        # Diarization step is considered successful even if segments_list is empty (no speakers found).
        # The tuple returned includes the success flag, the list of segments, the JSON string, and no error message.
        return True, segments_list, segments_json, None

    except RuntimeError as e:
        # --- Handle Specific Runtime Errors during Diarization Execution ---
        error_str = str(e).lower()
        # Check for CUDA OOM errors.
        if "cuda" in error_str and "out of memory" in error_str:
             err_msg = "CUDA Out Of Memory during diarization processing. Check GPU memory usage or try processing on CPU."
             logger.error(err_msg, exc_info=False) # No traceback needed for OOM
             return False, None, None, err_msg
        # Add more specific catches based on observed runtime errors if needed.
        else:
             err_msg = f"RuntimeError during diarization execution: {e}"
             logger.error(err_msg, exc_info=True) # Log full traceback
             return False, None, None, err_msg
    except Exception as e:
        # --- Catch-all for any other unexpected errors during diarization ---
        err_msg = f"An unexpected error occurred during diarization: {type(e).__name__}: {e}"
        logger.error(err_msg, exc_info=True) # Log with full traceback
        return False, None, None, err_msg
# --- END OF FILE: analysis/diarization.py ---