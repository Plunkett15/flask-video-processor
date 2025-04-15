# --- Start of File: analysis/qna_segmentation.py ---
import logging

logger = logging.getLogger(__name__)

# --- NEW CORE FUNCTION ---

def filter_diarization_by_exchange(full_diarization_segments, exchange_start, exchange_end, tolerance=0.01):
    """
    Filters a list of diarization segments (from the full audio) to include only
    those that overlap with the given exchange time boundaries.

    Args:
        full_diarization_segments (list): List of segment dictionaries from full diarization,
                                          each expected to have 'start', 'end', 'label'.
                                          Timestamps MUST be absolute (relative to video start).
        exchange_start (float): The absolute start time of the exchange in seconds.
        exchange_end (float): The absolute end time of the exchange in seconds.
        tolerance (float): Small tolerance (in seconds) for boundary checks to handle
                           potential floating point inaccuracies. Defaults to 0.01.

    Returns:
        list: A new list containing copies of the overlapping segment dictionaries.
              Segment times within the returned list remain ABSOLUTE relative to the
              start of the original video. Segments partially overlapping are included.
    """
    filtered_segments = []
    if not isinstance(full_diarization_segments, list):
        logger.warning("Invalid 'full_diarization_segments' input (not a list). Returning empty list.")
        return filtered_segments
    if exchange_start is None or exchange_end is None or exchange_end <= exchange_start:
        logger.warning(f"Invalid exchange boundaries provided: start={exchange_start}, end={exchange_end}. Returning empty list.")
        return filtered_segments

    logger.debug(f"Filtering {len(full_diarization_segments)} full diar segments for exchange ({exchange_start:.3f}s - {exchange_end:.3f}s)")

    for seg in full_diarization_segments:
        try:
            seg_start = float(seg.get('start'))
            seg_end = float(seg.get('end'))
            # Basic validation of segment data
            if seg_start is None or seg_end is None or seg_end <= seg_start:
                 logger.warning(f"Skipping invalid segment in full diarization data: {seg}")
                 continue

            # Check for overlap:
            # Segment starts before the exchange ends AND Segment ends after the exchange starts
            overlaps = seg_start < (exchange_end + tolerance) and seg_end > (exchange_start - tolerance)

            if overlaps:
                # Create a copy to avoid modifying original list (if passed by reference)
                filtered_segments.append(seg.copy())
                # logger.debug(f"  Included segment: {seg} (Overlap detected)") # Verbose logging

        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Skipping segment due to parsing error or missing key: {seg} - Error: {e}")
            continue

    logger.debug(f"Found {len(filtered_segments)} overlapping diarization segments for the exchange.")
    return filtered_segments

# --- CLEANUP: Remove old, unused functions ---
# def _get_segment_speaker_simple(...): -> REMOVED (Diarization handles speaker labels)
# def _determine_segment_type(...): -> REMOVED (Not relevant to filtering)
# def analyze_q_and_a(...): -> REMOVED (Superseded by granular pipeline)
# def pair_qa_exchanges(...): -> REMOVED (Superseded by exchange identification)
# def generate_short_clips_from_exchanges(...): -> REMOVED (Logic moved to define/cut tasks)

logger.info("qna_segmentation.py loaded (Refactored for diarization filtering).")

# --- END OF FILE: analysis/qna_segmentation.py ---