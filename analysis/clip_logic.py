# --- Start of File: analysis/clip_logic.py ---
import logging
from config import Config # Import configuration settings

logger = logging.getLogger(__name__)

def define_short_clips_from_segments(diarization_segments, config):
    """
    Analyzes diarization segments (within a specific exchange) to define
    potential short clips based on duration criteria.

    Args:
        diarization_segments (list): A list of dictionaries, each representing a
                                     diarization segment. Expected keys:
                                     'start' (float, absolute time),
                                     'end' (float, absolute time),
                                     'label' (str, speaker label).
        config (Config): The application configuration object to access clip limits.

    Returns:
        list: A list of dictionaries, each representing a defined short clip
              candidate meeting the duration criteria. Each dict contains:
              'absolute_start', 'absolute_end', 'speaker', 'duration'.
              Returns an empty list if no segments meet the criteria or input is empty.
    """
    definitions = []
    if not diarization_segments:
        logger.info("No diarization segments provided for short clip definition. Returning empty list.")
        return definitions
    if not isinstance(diarization_segments, list):
        logger.warning("Invalid 'diarization_segments' input (not a list). Returning empty list.")
        return definitions

    # Get duration limits from config, with safe defaults
    min_dur = getattr(config, 'CLIP_MIN_DURATION_SECONDS', 1.0)
    max_dur = getattr(config, 'CLIP_MAX_DURATION_SECONDS', 60.0) # Example default max
    logger.info(f"Defining short clips using duration limits: min={min_dur}s, max={max_dur}s")

    skipped_count = 0
    for seg in diarization_segments:
        try:
            # Use .get() for safety, though keys should be present from filtering step
            start = float(seg.get('start'))
            end = float(seg.get('end'))
            label = seg.get('label', 'UNKNOWN') # Default if label missing

            if start is None or end is None:
                raise ValueError("Segment missing 'start' or 'end' key.")

            duration = round(end - start, 3)

            # Check if duration meets criteria
            if min_dur <= duration <= max_dur:
                definitions.append({
                    'absolute_start': round(start, 3), # Keep absolute times
                    'absolute_end': round(end, 3),
                    'speaker': label,
                    'duration': duration
                })
                # logger.debug(f"Defined clip candidate: Speaker {label}, {start:.3f}s - {end:.3f}s ({duration:.3f}s)")
            else:
                skipped_count += 1
                # logger.debug(f"Segment duration {duration:.2f}s outside range ({min_dur}-{max_dur}). Skipping.")

        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Skipping invalid diarization segment during clip definition: {seg} - Error: {e}")
            skipped_count += 1
            continue

    logger.info(f"Defined {len(definitions)} short clip candidates (skipped {skipped_count} segments based on duration/errors).")
    return definitions

# --- END OF FILE: analysis/clip_logic.py ---