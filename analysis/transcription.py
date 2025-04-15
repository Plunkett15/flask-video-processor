# --- Start of File: analysis/transcription.py ---
import logging
import os
import torch
import threading # Used for thread-safe model loading
import time
from faster_whisper import WhisperModel # The core transcription model library
from faster_whisper.utils import format_timestamp # Utility for formatting timestamps if needed
from config import Config # Application configuration settings

logger = logging.getLogger(__name__)

# ================================================
# === Model Loading (Lazy Initialization) ===
# ================================================
# We use lazy initialization to avoid loading the potentially large transcription model
# into memory when the application starts, especially if it's not immediately needed.
# The model is loaded only when the `transcribe_audio` function is called for the first time.

# Global variable to hold the single model instance. Initialized to None.
_model_instance = None
# Thread lock: Ensures that only one thread can attempt to load the model at a time.
# This prevents race conditions if multiple requests/worker threads try to transcribe simultaneously
# before the model is fully loaded.
_model_load_lock = threading.Lock()

def _load_model():
    """
    Loads the FasterWhisper model instance if it hasn't been loaded yet.
    Uses a lock (`_model_load_lock`) to ensure thread-safety during initialization.

    This function implements a "double-checked locking" pattern:
    1. Check if the instance exists without acquiring the lock (fast path).
    2. If not, acquire the lock.
    3. Check again if the instance exists (in case another thread loaded it while waiting for the lock).
    4. If still not loaded, proceed with loading the model.

    Returns:
        WhisperModel: The loaded model instance.
    Raises:
        RuntimeError: If the model fails to load for any reason (config error, download error, etc.).
    """
    global _model_instance
    # --- Fast path check (no lock needed) ---
    if _model_instance:
        return _model_instance

    # --- Acquire lock for potential loading ---
    # `with` statement ensures the lock is automatically released.
    with _model_load_lock:
        # --- Second check (after acquiring lock) ---
        # Another thread might have loaded the model while this thread was waiting.
        if _model_instance:
            return _model_instance

        # --- Load Model ---
        logger.info("Attempting to load FasterWhisper model (first transcription request or reload)...")
        config = Config() # Get application configuration
        model_name = config.FASTER_WHISPER_MODEL
        device = config.DEVICE # 'cuda' or 'cpu'
        compute_type = config.FASTER_WHISPER_COMPUTE_TYPE # 'int8', 'float16', etc.

        logger.info(f"Model: '{model_name}', Device: '{device}', Compute Type: '{compute_type}'")
        logger.info("Model download may occur if not cached locally (~/.cache/huggingface/hub or similar).")
        start_time = time.time()

        try:
            # --- Determine Optimal Settings for FasterWhisper ---
            # Device index (primarily for multi-GPU setups, often 0 for single 'cuda' device)
            # device_index = 0 if device == "cuda" else None # Simple logic, adjust if using multiple GPUs

            # CPU threads: Can impact performance, especially for 'int8' compute type on CPU.
            # Setting to 0 lets FasterWhisper/underlying libraries decide (often based on OpenMP/MKL).
            # Explicitly setting can sometimes be beneficial but requires tuning.
            cpu_cores = os.cpu_count() or 4 # Get physical cores or default to 4
            threads = 0 # Default: Let FasterWhisper manage.
            if device == 'cpu':
                # Heuristic: More threads might help int8, maybe fewer for float types? Needs testing.
                 threads = cpu_cores if compute_type == 'int8' else max(1, cpu_cores // 2)
                 logger.info(f"CPU device detected. Setting cpu_threads={threads} (based on {cpu_cores} cores, compute type {compute_type}).")

            # --- Initialize the WhisperModel ---
            model = WhisperModel(
                model_name,
                device=device,
                # device_index=device_index, # Specify GPU index(es) if needed
                compute_type=compute_type,
                cpu_threads=threads, # Number of CPU threads to use for inference
                # num_workers=1, # For data loading, usually 1 is fine for inference
                # download_root="/path/to/custom/model/cache", # Specify custom cache dir if needed
            )

            # --- Optional: Verification ---
            # Could run a very short dummy inference here to confirm loading, but adds overhead.
            # Generally, if WhisperModel() doesn't raise an error, it's loaded okay.
            # logger.debug("Model loaded. Running quick dummy test...")
            # list(model.transcribe("path/to/short_dummy.wav", beam_size=1)) # Example test

            load_time = time.time() - start_time
            logger.info(f"FasterWhisper model '{model_name}' loaded successfully to {device} ({compute_type}) in {load_time:.2f} seconds.")
            _model_instance = model # Assign to the global variable
            return _model_instance

        except ImportError as e:
             # Catch missing dependencies (e.g., CUDA toolkit mismatch, libraries not found)
             logger.critical(f"ImportError during model loading - potential dependency issue: {e}", exc_info=True)
             _model_instance = None # Ensure instance remains None on failure
             # Re-raise as RuntimeError to signal catastrophic failure to the caller
             raise RuntimeError(f"Failed to load transcription model due to import error: {e}") from e
        except ValueError as e:
            # Catch invalid model names or configuration options passed to WhisperModel
            logger.critical(f"ValueError during model loading (invalid model name or config?): {e}", exc_info=True)
            _model_instance = None
            raise RuntimeError(f"Configuration error loading transcription model: {e}") from e
        except Exception as e:
             # Catch-all for other loading issues (network errors downloading, corrupted cache, etc.)
            logger.critical(f"CRITICAL: Unexpected error loading FasterWhisper model '{model_name}'. Transcription will fail. Error: {e}", exc_info=True)
            _model_instance = None
            # Re-raise to prevent the application continuing without a functional model
            raise RuntimeError(f"Unexpected error loading transcription model: {e}") from e

# ================================================
# === Main Transcription Function ===
# ================================================
def transcribe_audio(audio_path, language=None, vad_filter=True, beam_size=5):
    """
    Transcribes the given audio file using the loaded FasterWhisper model.

    Args:
        audio_path (str): Path to the input audio file (e.g., WAV, MP3).
        language (str, optional): Language code (e.g., 'en', 'es'). If None, detects automatically. Defaults to None.
        vad_filter (bool, optional): Whether to use Silero VAD (Voice Activity Detection)
                                     to filter out non-speech parts before transcription.
                                     Requires `silero-vad` package. Defaults to True.
        beam_size (int, optional): Beam size for decoding. Higher values might increase accuracy
                                   but are slower and use more memory. Default is 5.

    Returns:
        tuple: (success (bool), result (list | None), error_message (str | None))
               - success: True if transcription completed successfully, False otherwise.
               - result: A list of faster_whisper Segment objects if successful, otherwise None.
                         Each Segment object contains attributes like 'start', 'end', 'text', etc.
               - error_message: A string describing the error if success is False, otherwise None.
    """
    # --- Input Validation ---
    if not os.path.exists(audio_path):
        err = f"Audio file not found for transcription: {audio_path}"
        logger.error(err)
        return False, None, err
    if os.path.getsize(audio_path) == 0:
         err = f"Audio file is empty (0 bytes), cannot transcribe: {audio_path}"
         logger.error(err)
         return False, None, err
    # Could add more checks here (e.g., using soundfile/librosa to verify format/readability).

    logger.info(f"Starting transcription for: {os.path.basename(audio_path)}")
    logger.info(f"Transcription Parameters: Language='{language or 'auto-detect'}', VAD Filter={vad_filter}, Beam Size={beam_size}")
    transcription_start_time = time.time()

    try:
        # --- Get Model Instance (Ensures Model is Loaded) ---
        # This call will either return the loaded model or raise a RuntimeError if loading fails.
        model = _load_model()
        # No need to check `if model is None:` here, as _load_model handles failure by raising.

        config = Config() # Get config again for logging details during transcription itself
        logger.info(f"Performing transcription using model '{config.FASTER_WHISPER_MODEL}' "
                    f"on device '{config.DEVICE}' with compute type '{config.FASTER_WHISPER_COMPUTE_TYPE}'.")

        # --- Perform Transcription ---
        # Call the model's transcribe method with the specified audio path and parameters.
        # Refer to FasterWhisper documentation for all available parameters.
        # Key parameters explained:
        # - word_timestamps=False: SIGNIFICANTLY faster & uses less memory unless you absolutely need word-level timings.
        # - condition_on_previous_text=True: Standard Whisper behavior, helps maintain context across segments.
        # - temperature=(0.0, 0.2, ...): Controls randomness. Tuple allows fallbacks if sampling fails. Default 0.0 = greedy (most likely word).
        # - vad_filter=True: Uses VAD to preprocess audio, potentially improving accuracy on noisy audio or speeding up by skipping silence.
        # - vad_parameters={...}: Fine-tune VAD behavior if needed (defaults are usually okay).
        segments_generator, transcription_info = model.transcribe(
            audio=audio_path,
            language=language,           # Pass language code or None for auto-detect
            beam_size=beam_size,         # Controls search width during decoding
            vad_filter=vad_filter,       # Enable/disable VAD pre-processing
            vad_parameters={"min_silence_duration_ms": 500}, # Example VAD tuning parameter
            word_timestamps=False,       # Set True ONLY if word timings are essential (much slower)
            # condition_on_previous_text=True, # Default behavior, generally recommended
            # initial_prompt="Provide context...", # Optional: Give the model a hint about the content
            # temperature=0.0,             # Set sampling temperature if needed (0.0 = deterministic)
        )

        # --- Process Results ---
        logger.debug("Transcription processing started, consuming segment generator...")
        # The `transcribe` method returns a generator. We need to consume it to get the results.
        # Convert the generator to a list to hold all segments.
        # For very long audio files (> hours), processing the generator iteratively might save memory,
        # but downstream analysis often requires the full list anyway.
        segments_list = list(segments_generator) # This executes the main transcription computation.
        logger.debug("Segment generator consumed, transcription core processing complete.")

        # Log a summary of the transcription results.
        duration = time.time() - transcription_start_time
        num_segments = len(segments_list)
        detected_lang = transcription_info.language
        lang_prob = transcription_info.language_probability
        # Duration of audio processed (may differ from file duration if VAD is used)
        proc_duration = transcription_info.duration
        logger.info(f"Transcription completed in {duration:.2f} seconds.")
        logger.info(f"Detected language: {detected_lang} (Confidence: {lang_prob:.2f})")
        logger.info(f"Processed audio duration (after VAD if enabled): {proc_duration:.2f}s")
        logger.info(f"Generated {num_segments} transcript segments.")

        # Example: Log the first few segments at DEBUG level for inspection.
        # if num_segments > 0:
        #     logger.debug("First few transcript segments:")
        #     for i, seg in enumerate(segments_list[:3]):
        #         start_f = format_timestamp(seg.start) # Format seconds to HH:MM:SS.fff
        #         end_f = format_timestamp(seg.end)
        #         logger.debug(f"  {i}: [{start_f} -> {end_f}] {seg.text[:100].strip()}...")


        # Return success status, the list of Segment objects, and no error message.
        return True, segments_list, None

    except RuntimeError as e:
        # --- Handle Specific Runtime Errors during Transcription Execution ---
        error_str = str(e).lower()
        # Check for common errors like CUDA Out Of Memory (OOM).
        if "cuda" in error_str and "out of memory" in error_str:
             err_msg = "CUDA Out Of Memory during transcription. Try a smaller model, 'int8' compute type, reduce beam size, or ensure GPU has sufficient free memory."
             logger.error(err_msg, exc_info=False) # Don't need full traceback for common OOM
             return False, None, err_msg
        # Check for audio backend related errors.
        elif "coreaudio" in error_str or "audio backend" in error_str:
             err_msg = f"Audio backend error during transcription: {e}. Check audio file format/integrity or system audio libraries."
             logger.error(err_msg, exc_info=False)
             return False, None, err_msg
        # Check for errors related to CPU optimization libraries (MKL, oneDNN).
        elif "mkldnn" in error_str or "onednn" in error_str:
             err_msg = f"CPU optimization library (MKL/oneDNN) error: {e}. Check library installation/compatibility."
             logger.error(err_msg, exc_info=True) # Include traceback
             return False, None, err_msg
        # Check for VAD-specific errors if vad_filter was enabled.
        elif "vad" in error_str and ("fail" in error_str or "error" in error_str):
             err_msg = f"VAD filter processing failed during transcription: {e}."
             logger.error(err_msg, exc_info=True)
             return False, None, err_msg
        else:
            # Handle generic runtime errors not specifically caught above.
            err_msg = f"Runtime error during transcription execution: {e}"
            logger.error(err_msg, exc_info=True) # Log full traceback
            return False, None, err_msg
    except ImportError as e:
        # --- Handle Missing Dependencies during Execution ---
        # Example: If VAD filter=True but 'silero-vad' package isn't installed.
        if "silero_vad" in str(e).lower():
             err_msg = "Missing dependency 'silero-vad', required for 'vad_filter=True'. Please install it (`pip install -U silero-vad`)."
             logger.error(err_msg, exc_info=False) # No traceback needed
             return False, None, err_msg
        else:
             # Other potential import errors during runtime.
             err_msg = f"Import error during transcription execution, missing dependency?: {e}"
             logger.error(err_msg, exc_info=True)
             return False, None, err_msg
    except Exception as e:
        # --- Catch-all for any other unexpected errors during transcription ---
        err_msg = f"An unexpected error occurred during transcription: {type(e).__name__}: {e}"
        logger.error(err_msg, exc_info=True) # Log with full traceback
        return False, None, err_msg
# --- END OF FILE: analysis/transcription.py ---