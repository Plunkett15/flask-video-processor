# --- Start of File: analysis/alignment_utils.py ---
import logging
import re

logger = logging.getLogger(__name__)

# ==============================================================================
# === Transcript & Diarization Alignment ===
# ==============================================================================

def align_transcript_diarization(transcript_segments, diarization_segments, default_speaker="UNKNOWN"):
    """
    Aligns transcript segments with speaker diarization segments based on time overlap.

    Assigns a speaker label to each transcript segment based on the speaker
    who spoke for the longest duration *within* that segment's timeframe.

    Args:
        transcript_segments (list): List of dicts [{'start': float, 'end': float, 'text': str}].
        diarization_segments (list): List of dicts [{'start': float, 'end': float, 'label': str}].
        default_speaker (str): Speaker label to assign if no overlap is found.

    Returns:
        list: A new list of transcript segments, each augmented with a 'speaker' key.
              Returns an empty list if transcript_segments is empty.
    """
    aligned_segments = []
    if not transcript_segments:
        logger.warning("align_transcript_diarization: No transcript segments provided.")
        return aligned_segments
    if not diarization_segments:
        logger.warning("align_transcript_diarization: No diarization segments provided. Assigning default speaker to all transcript segments.")
        # Assign default speaker if diarization is missing
        for t_seg in transcript_segments:
            new_seg = t_seg.copy()
            new_seg['speaker'] = default_speaker
            aligned_segments.append(new_seg)
        return aligned_segments

    logger.info(f"Aligning {len(transcript_segments)} transcript segments with {len(diarization_segments)} diarization segments...")

    # Sort diarization segments by start time for potentially faster searching (optional)
    # diarization_segments.sort(key=lambda x: x.get('start', 0))

    total_matched_time = 0
    unmatched_segments = 0

    for t_idx, t_seg in enumerate(transcript_segments):
        t_start = t_seg.get('start')
        t_end = t_seg.get('end')
        if t_start is None or t_end is None or t_end <= t_start:
            logger.warning(f"Skipping invalid transcript segment at index {t_idx}: {t_seg}")
            new_seg = t_seg.copy()
            new_seg['speaker'] = default_speaker # Assign default if invalid
            aligned_segments.append(new_seg)
            continue

        speaker_overlaps = {} # {speaker_label: total_overlap_duration}

        # Find overlapping diarization segments
        for d_seg in diarization_segments:
            d_start = d_seg.get('start')
            d_end = d_seg.get('end')
            d_label = d_seg.get('label', default_speaker)

            if d_start is None or d_end is None or d_end <= d_start:
                continue # Skip invalid diarization segments

            # Calculate overlap duration: max(0, min(end1, end2) - max(start1, start2))
            overlap_start = max(t_start, d_start)
            overlap_end = min(t_end, d_end)
            overlap_duration = max(0, overlap_end - overlap_start)

            if overlap_duration > 0.001: # Require minimal overlap (e.g., > 1ms)
                speaker_overlaps[d_label] = speaker_overlaps.get(d_label, 0) + overlap_duration
                # logger.debug(f"  T_Seg [{t_start:.2f}-{t_end:.2f}] overlaps D_Seg [{d_start:.2f}-{d_end:.2f}] ({d_label}) by {overlap_duration:.3f}s")


        # Determine speaker with maximum overlap
        assigned_speaker = default_speaker
        if speaker_overlaps:
            # Find the speaker label with the highest total overlap duration
            assigned_speaker = max(speaker_overlaps, key=speaker_overlaps.get)
            max_overlap = speaker_overlaps[assigned_speaker]
            total_matched_time += max_overlap
            # logger.debug(f"Assigned Speaker '{assigned_speaker}' to T_Seg {t_idx} (Max overlap: {max_overlap:.3f}s)")
        else:
            unmatched_segments += 1
            # logger.debug(f"No significant speaker overlap found for T_Seg {t_idx}. Assigning '{default_speaker}'.")

        # Add speaker to the transcript segment copy
        new_seg = t_seg.copy()
        new_seg['speaker'] = assigned_speaker
        aligned_segments.append(new_seg)

    # Log summary
    total_transcript_duration = sum(max(0, s.get('end', 0) - s.get('start', 0)) for s in transcript_segments)
    if total_transcript_duration > 0:
        match_percentage = (total_matched_time / total_transcript_duration) * 100
        logger.info(f"Alignment complete. Matched {total_matched_time:.2f}s of speaker time "
                    f"({match_percentage:.1f}%) across {len(transcript_segments)} segments.")
    else:
        logger.info("Alignment complete. No valid transcript duration to calculate match percentage.")
    if unmatched_segments > 0:
        logger.warning(f"{unmatched_segments} transcript segments had no significant speaker overlap.")

    return aligned_segments

# ==============================================================================
# === Simple Question Detection Rule ===
# ==============================================================================

# Pre-compile regex for efficiency
# Matches strings starting with common question words (case-insensitive) or ending with '?'
QUESTION_PATTERN = re.compile(
    r"^\s*(who|what|where|when|why|how|is|are|am|do|does|did|can|could|will|would|should|may|might|was|were|have|has|had)\b.*\??$|.*\?\s*$",
    re.IGNORECASE
)
# Reduced list of question words to minimize false positives on statements starting with these words.

def is_likely_question(text):
    """
    Uses simple rules (ending punctuation, starting words) to guess if text is a question.

    Args:
        text (str): The text content of a transcript segment.

    Returns:
        bool: True if the text is likely a question, False otherwise.
    """
    if not text or not isinstance(text, str):
        return False

    cleaned_text = text.strip()
    if not cleaned_text:
        return False

    # Check using the pre-compiled regex pattern
    if QUESTION_PATTERN.match(cleaned_text):
        # logger.debug(f"Likely question (Regex Match): '{cleaned_text[:80]}...'")
        return True

    # Fallback check specifically for question mark if regex didn't catch it (e.g., whitespace issues)
    if cleaned_text.endswith('?'):
        # logger.debug(f"Likely question (Ends with ?): '{cleaned_text[:80]}...'")
        return True

    return False

# --- END OF FILE: analysis/alignment_utils.py ---