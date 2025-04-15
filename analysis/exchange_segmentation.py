# --- Start of File: analysis/exchange_segmentation.py ---
import re
import logging
import time

logger = logging.getLogger(__name__)

# ==============================================================================
# === Configuration: Exchange Start Markers (REFINED) ===
# ==============================================================================
# Define patterns using Regular Expressions (Regex) to identify the start of
# a NEW parliamentary exchange. Case-insensitive matching is used.
# FOCUS: Primarily target explicit cues from the Speaker introducing the next questioner.
# NOTE: This list is CRUCIAL and needs refinement based on MORE transcript analysis.
#       This is an AUTOMATED first pass; manual review/correction is expected.

try:
    EXCHANGE_START_MARKER_PATTERNS = [
        # 1. Speaker announcing "Next Question" variations followed by member/leader ID
        #    Covers "The next question", "next question", optional comma, optional "once again",
        #    followed by "is for", "the leader", "the member". More robust structure.
        re.compile(r"^\s*(?:the\s+)?next\s+question(?:,)?(?:\s+once\s+again(?:,)?)?\s+(?:is\s+for\s+|the\s+leader\b|the\s+member\b)", re.IGNORECASE),

        # 2. Speaker explicitly recognizing member for the *first* question of the session
        #    Adjust this based on the exact phrasing observed in transcripts.
        re.compile(r"^\s*It is now time for oral questions\.\s+I recognize\s+(?:the\s+leader\b|the\s+member\b)", re.IGNORECASE),

        # 3. Speaker announcing "The next question is for [Location/Riding]"
        #    Example: "The next question is for Waterloo." - Requires the riding name doesn't clash with common words.
        # re.compile(r"^\s*(?:the\s+)?next\s+question\s+is\s+for\s+[\w\s-]+", re.IGNORECASE), # Needs testing, potentially too broad

        # --- Patterns to AVOID adding here ---
        # - "supplementary question" / "final supplementary" -> These CONTINUE exchanges.
        # - Generic question words ("Can the minister...") -> Too unreliable, part of member's speech.
        # - Answer introductions ("To reply...", "Minister of...") -> Signal Q->A transition, not new exchange start.
    ]
    logger.info(f"Compiled {len(EXCHANGE_START_MARKER_PATTERNS)} 'auto' exchange start marker patterns (Refined Set).")
except re.error as e:
    logger.critical(f"Regex compilation error in exchange markers: {e}. Auto Exchange ID step will fail.", exc_info=True)
    EXCHANGE_START_MARKER_PATTERNS = [] # Prevent further errors


# ==============================================================================
# === Helper Function: Check for Marker ===
# ==============================================================================
def _find_marker_match(segment_text):
    """
    Checks if the beginning of the text matches any known start marker patterns.

    Args:
        segment_text (str): The text of a transcript segment.

    Returns:
        str | None: The matched marker text (cleaned) if found, otherwise None.
    """
    if not segment_text:
        return None

    # Use strip() early to handle leading whitespace consistently
    stripped_text = segment_text.strip()

    # Check against compiled patterns
    for idx, pattern in enumerate(EXCHANGE_START_MARKER_PATTERNS):
        # Use `match` to check only the beginning of the stripped string
        match = pattern.match(stripped_text)
        if match:
            # Return the matched portion, cleaning multiple spaces
            matched_text_cleaned = " ".join(match.group(0).split())
            logger.debug(f"Segment matched PATTERN #{idx}: '{pattern.pattern}' -> Matched text: '{matched_text_cleaned}'")
            return matched_text_cleaned # Return the cleaned matched text

    # --- ADDED logging for misses (optional, can be noisy) ---
    # logger.debug(f"Segment text did NOT match any start patterns: '{stripped_text[:100]}'")
    return None

# ==============================================================================
# === Main Function: Identify Long Exchanges ===
# ==============================================================================
def identify_long_exchanges(transcript_segments):
    """
    Analyzes a list of transcript segments to identify long exchanges based on
    pre-defined keyword/phrase markers signaling the START of an exchange ('auto' type).
    The end of an exchange is the start time of the next identified exchange marker,
    or the end time of the last segment in the transcript.

    Args:
        transcript_segments (list): A list of dictionaries, each representing a
                                    transcript segment with 'start', 'end', 'text'.

    Returns:
        list: A list of dictionaries, each representing an identified long exchange.
              Contains: 'id' (str, e.g., 'lex_0'), 'start', 'end', 'marker', 'duration'.
    """
    start_time_analysis = time.time()
    logger.info(f"Starting 'auto' long exchange identification for {len(transcript_segments)} segments...")
    exchanges = []

    if not transcript_segments:
        logger.warning("No transcript segments provided for exchange identification.")
        return exchanges
    if not EXCHANGE_START_MARKER_PATTERNS:
         logger.error("No valid 'auto' exchange start marker patterns compiled. Cannot identify exchanges.")
         return exchanges

    found_marker_indices = [] # Store info about where markers are found

    # --- Pass 1: Find all segments that contain a start marker ---
    for idx, segment in enumerate(transcript_segments):
        text = segment.get('text', '')
        start_time = segment.get('start')
        # Basic validation of segment data
        if text is None or start_time is None or segment.get('end') is None:
             logger.debug(f"Skipping malformed segment at index {idx}: {segment}")
             continue # Skip malformed segments

        # Check if the segment's text matches any defined start marker
        matched_marker = _find_marker_match(text)
        if matched_marker:
            found_marker_indices.append({
                'index': idx,
                'start_time': start_time,
                'marker_text': matched_marker
            })
            logger.info(f"--> Auto-Marker found at index {idx}, time {start_time:.3f}s: '{matched_marker}'")

    if not found_marker_indices:
         logger.warning("No 'auto' exchange start markers found in the entire transcript.")
         return exchanges

    logger.info(f"Found {len(found_marker_indices)} potential 'auto' exchange start markers.")

    # --- Pass 2: Define exchanges based on consecutive markers ---
    num_markers = len(found_marker_indices)
    for k in range(num_markers):
        current_marker_info = found_marker_indices[k]
        exchange_start_time = current_marker_info['start_time']
        marker_text = current_marker_info['marker_text']

        # Determine end time
        if k + 1 < num_markers:
            # End time is the start time of the *next* identified marker segment
            next_marker_info = found_marker_indices[k+1]
            exchange_end_time = next_marker_info['start_time']
        else:
            # This is the last marker found, exchange ends at the end of the *entire transcript*
            last_transcript_segment = transcript_segments[-1]
            exchange_end_time = last_transcript_segment.get('end')
            if exchange_end_time is None:
                logger.warning(f"Last segment has no end time. Cannot accurately determine end for the last exchange starting at {exchange_start_time:.3f}s. Using start time + default duration (e.g., 60s) as fallback.")
                # Fallback: Use start time + a default guess, or skip? Skipping is safer.
                # exchange_end_time = exchange_start_time + 60.0
                continue # Skip this last exchange if end time is unknown

        # Basic validation and formatting
        if exchange_end_time > exchange_start_time:
            exchange_id = f"lex_{k}" # Simple ID based on order found ('lex' = long exchange)
            duration = round(exchange_end_time - exchange_start_time, 3)

            # Optional: Minimum duration filter?
            # min_exchange_duration = 10.0 # seconds
            # if duration < min_exchange_duration:
            #     logger.info(f"Skipping potential exchange {exchange_id} due to short duration ({duration:.1f}s < {min_exchange_duration}s).")
            #     continue

            exchanges.append({
                'id': exchange_id, # This becomes the 'exchange_label' in the DB
                'start': round(exchange_start_time, 3),
                'end': round(exchange_end_time, 3),
                'marker': marker_text, # The text that triggered this start
                'duration': duration,
                # 'type': 'auto' # Type is added during DB insertion
            })
            logger.debug(f"Defined Auto Exchange {exchange_id}: {exchange_start_time:.3f}s - {exchange_end_time:.3f}s (Duration: {duration:.3f}s)")
        else:
            logger.warning(f"Skipping potential exchange starting at {exchange_start_time:.3f}s because calculated end time ({exchange_end_time:.3f}s) is not valid.")


    analysis_duration = time.time() - start_time_analysis
    logger.info(f"'Auto' exchange identification finished in {analysis_duration:.2f}s. Defined {len(exchanges)} exchanges.")
    return exchanges

# --- END OF FILE: analysis/exchange_segmentation.py ---