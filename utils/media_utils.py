import subprocess
import os
import logging
import datetime
import json
import re
import time # Import time for delays and measurements
from config import Config

logger = logging.getLogger(__name__)
# Instantiate Config within this module if accessing its properties
config = Config()
FFMPEG_PATH = config.FFMPEG_PATH
_FFMPEG_CHECKED = False
_FFPROBE_CHECKED = False
FFMPEG_AVAILABLE = False
FFPROBE_AVAILABLE = False

# Derive ffprobe path from ffmpeg path assumption (common location)
FFPROBE_PATH_GUESS = None
try:
    if FFMPEG_PATH and isinstance(FFMPEG_PATH, str):
        # Handle common cases: 'ffmpeg', '/path/to/ffmpeg', 'C:\path\ffmpeg.exe'
        ffmpeg_lower = FFMPEG_PATH.lower()
        if ffmpeg_lower == 'ffmpeg':
            FFPROBE_PATH_GUESS = 'ffprobe' # Assume both are in PATH
        elif 'ffmpeg' in ffmpeg_lower:
            base_path = os.path.dirname(FFMPEG_PATH)
            probe_exe = "ffprobe.exe" if ffmpeg_lower.endswith(".exe") else "ffprobe"
            FFPROBE_PATH_GUESS = os.path.join(base_path, probe_exe)
        else:
            # Can't make a reliable guess if 'ffmpeg' isn't in the name/path
            logger.warning(f"Could not confidently determine ffprobe path from non-standard ffmpeg path: '{FFMPEG_PATH}'.")
    else:
        logger.warning(f"FFMPEG_PATH '{FFMPEG_PATH}' is not a valid string.")
except Exception as path_err:
     logger.error(f"Error constructing ffprobe path guess from '{FFMPEG_PATH}': {path_err}")


def check_ffmpeg_tools():
    """Checks if ffmpeg and ffprobe commands are available and updates global flags."""
    global _FFMPEG_CHECKED, _FFPROBE_CHECKED, FFMPEG_AVAILABLE, FFPROBE_AVAILABLE

    # Check ffmpeg only if not already checked
    if not _FFMPEG_CHECKED:
        logger.info(f"Checking for FFmpeg executable at: {FFMPEG_PATH}")
        try:
            # Run 'ffmpeg -version' and capture output
            result = subprocess.run(
                [FFMPEG_PATH, "-version"],
                check=True,                # Throw error on non-zero exit code
                capture_output=True,       # Capture stdout/stderr
                text=True,                 # Decode output as text
                encoding='utf-8',          # Specify encoding
                timeout=10                 # Timeout in seconds
            )
            # Check if output contains expected version string
            if "ffmpeg version" in result.stdout.lower():
                logger.info(f"FFmpeg check successful. Version info detected:\n{result.stdout.splitlines()[0]}") # Log first line
                FFMPEG_AVAILABLE = True
            else:
                 logger.warning(f"FFmpeg command ran but version string not found in output:\n{result.stdout[:200]}...")
                 FFMPEG_AVAILABLE = False
        except FileNotFoundError:
            logger.error(f"FFmpeg command '{FFMPEG_PATH}' not found. Ensure FFmpeg is installed and in your system's PATH, or set FFMPEG_PATH in the .env file correctly.")
            FFMPEG_AVAILABLE = False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, PermissionError) as e:
            logger.error(f"Error executing FFmpeg version check ('{FFMPEG_PATH} -version'): {e}")
            if isinstance(e, subprocess.CalledProcessError):
                 logger.error(f"FFmpeg stderr: {e.stderr}")
            FFMPEG_AVAILABLE = False
        except Exception as e:
            logger.error(f"Unexpected error during FFmpeg check: {e}", exc_info=True)
            FFMPEG_AVAILABLE = False
        finally:
             _FFMPEG_CHECKED = True # Mark as checked regardless of outcome

    # Check ffprobe only if not already checked AND we have a path guess
    if not _FFPROBE_CHECKED and FFPROBE_PATH_GUESS:
        logger.info(f"Checking for FFprobe executable at guessed path: {FFPROBE_PATH_GUESS}")
        try:
            result = subprocess.run(
                [FFPROBE_PATH_GUESS, "-version"],
                 check=True, capture_output=True, text=True, encoding='utf-8', timeout=10
            )
            if "ffprobe version" in result.stdout.lower():
                 logger.info(f"FFprobe check successful. Version info detected:\n{result.stdout.splitlines()[0]}")
                 FFPROBE_AVAILABLE = True
            else:
                  logger.warning(f"FFprobe command ran but version string not found in output:\n{result.stdout[:200]}...")
                  FFPROBE_AVAILABLE = False
        except FileNotFoundError:
            logger.warning(f"FFprobe command '{FFPROBE_PATH_GUESS}' not found at the guessed location. Features requiring ffprobe (like duration check) may fail.")
            FFPROBE_AVAILABLE = False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, PermissionError) as e:
            logger.error(f"Error executing FFprobe version check ('{FFPROBE_PATH_GUESS} -version'): {e}")
            if isinstance(e, subprocess.CalledProcessError):
                 logger.error(f"FFprobe stderr: {e.stderr}")
            FFPROBE_AVAILABLE = False
        except Exception as e:
             logger.error(f"Unexpected error during FFprobe check: {e}", exc_info=True)
             FFPROBE_AVAILABLE = False
        finally:
            _FFPROBE_CHECKED = True
    elif not FFPROBE_PATH_GUESS:
         logger.warning("FFprobe check skipped: Could not determine FFprobe path from FFmpeg config.")
         _FFPROBE_CHECKED = True # Mark as checked (negative result)

    return FFMPEG_AVAILABLE # Return primary tool status

# Run check automatically when module is loaded
check_ffmpeg_tools()


def _run_ffmpeg_command(command, description="ffmpeg operation"):
    """Helper to run an FFmpeg command list, check availability, handle errors, log output."""
    if not FFMPEG_AVAILABLE:
        err_msg = f"FFmpeg is not available or configured correctly (checked path: {FFMPEG_PATH}). Cannot run '{description}'."
        logger.error(err_msg)
        return False, err_msg # Return failure and error message

    logger.info(f"Running FFmpeg for '{description}': {' '.join(command)}")
    start_time = time.time()

    # Determine output path heuristic (often last arg unless it starts with '-')
    output_path = None
    if command:
        if not command[-1].startswith('-'):
             output_path = command[-1]
        elif len(command) > 1 and not command[-2].startswith('-'):
             # If last is flag, maybe second-to-last is output? Highly heuristic.
             output_path = command[-2]

    try:
        # Ensure output directory exists before running FFmpeg command
        if output_path:
            output_dir = os.path.dirname(output_path)
            # Ensure we only create dirs if output_dir is not empty (i.e., not just a filename in cwd)
            if output_dir and not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    logger.info(f"Created directory for FFmpeg output: {output_dir}")
                except OSError as e:
                     err = f"Failed to create output directory '{output_dir}' for FFmpeg '{description}': {e}"
                     logger.error(err)
                     return False, err # Fail early if directory cannot be created

        # Execute the FFmpeg command
        # Capture stderr as it contains progress and error details. stdout is less common.
        process = subprocess.run(
            command,
            check=True,             # Raises CalledProcessError on non-zero exit code
            stdout=subprocess.PIPE, # Capture stdout just in case
            stderr=subprocess.PIPE, # Capture stderr (most important)
            text=True,              # Decode stdout/stderr as text
            encoding='utf-8',       # Specify encoding
            timeout=7200            # Generous 2-hour timeout (adjust if needed)
        )

        elapsed = time.time() - start_time

        # --- Verify Output Post-Success ---
        output_ok = True
        if output_path:
            if not os.path.exists(output_path):
                 logger.warning(f"FFmpeg command '{description}' reported success, but output file '{output_path}' does NOT exist.")
                 output_ok = False
            elif os.path.getsize(output_path) == 0:
                 logger.warning(f"FFmpeg command '{description}' reported success, but output file '{output_path}' is EMPTY (0 bytes).")
                 output_ok = False

        if output_ok:
             logger.info(f"FFmpeg '{description}' completed successfully in {elapsed:.2f}s. Output path: {output_path or '(No specific output path argument found)'}")
        # Log stderr output at DEBUG level if it's verbose
        if process.stderr:
            stderr_lines = process.stderr.strip().splitlines()
            # Limit log size if stderr is huge
            log_limit = 20
            if len(stderr_lines) > log_limit * 2:
                 log_stderr = "\n".join(stderr_lines[:log_limit]) + "\n...\n" + "\n".join(stderr_lines[-log_limit:])
            else:
                 log_stderr = "\n".join(stderr_lines)
            logger.debug(f"FFmpeg stderr output for '{description}' ({len(stderr_lines)} lines total):\n{log_stderr}")
        if not output_ok:
            # Return success=False even if ffmpeg exit code was 0, if output validation failed
            return False, f"FFmpeg command succeeded, but output file validation failed (missing or empty): {output_path}"

        return True, None # Success, no error message

    except FileNotFoundError:
        # This backup check shouldn't be needed if FFMPEG_AVAILABLE is correct, but safeguard.
        err = f"FFmpeg command '{FFMPEG_PATH}' was not found during execution attempt. Check installation and PATH."
        logger.error(err)
        return False, err
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        err = f"FFmpeg command '{description}' timed out after {elapsed:.0f} seconds. Process was killed."
        logger.error(err)
        # Attempt to clean up potentially incomplete output file
        if output_path and os.path.exists(output_path):
            try: os.remove(output_path); logger.info(f"Removed potentially incomplete output file: {output_path}")
            except OSError as rm_err: logger.warning(f"Failed to remove incomplete output file '{output_path}' after timeout: {rm_err}")
        return False, err
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        # Extract useful info from the error, especially stderr
        stderr_content = e.stderr.strip() if e.stderr else "No stderr captured."
        # Try to find key error lines
        error_lines = [line for line in stderr_content.splitlines() if 'error' in line.lower() or 'failed' in line.lower()]
        if error_lines:
             error_hint = f"Error hint: ...{error_lines[-1][-180:]}" # Last potential error line snippet
        elif stderr_content:
             error_hint = f"Last stderr: ...{stderr_content[-180:]}" # Tail of stderr if no specific error found
        else:
             error_hint = "No informative error message in stderr."

        err = f"FFmpeg command '{description}' failed after {elapsed:.1f}s with exit code {e.returncode}. {error_hint}"
        logger.error(err) # Log the concise error
        # Log the full command and full stderr at DEBUG level for deep diagnostics
        logger.debug(f"Failed FFmpeg command was: {' '.join(e.cmd)}")
        if e.stderr: logger.debug(f"Full FFmpeg stderr:\n{e.stderr.strip()}")
        # Attempt cleanup of potentially corrupted output
        if output_path and os.path.exists(output_path):
            try: os.remove(output_path); logger.info(f"Removed potentially corrupted output file: {output_path}")
            except OSError as rm_err: logger.warning(f"Failed to remove failed output file '{output_path}': {rm_err}")
        return False, err # Return the concise formatted error message
    except Exception as e:
        # Catch-all for other Python errors during subprocess handling
        elapsed = time.time() - start_time
        err = f"Unexpected Python error during FFmpeg '{description}' execution after {elapsed:.1f}s: {type(e).__name__}: {e}"
        logger.error(err, exc_info=True) # Log with full traceback
        if output_path and os.path.exists(output_path):
             try: os.remove(output_path); logger.info(f"Removed potentially affected output file: {output_path}")
             except OSError as rm_err: logger.warning(f"Failed to remove output file '{output_path}' after Python error: {rm_err}")
        return False, err

# --- Core Media Functions ---

def extract_audio(video_path, audio_output_path, sample_rate=16000, channels=1):
    """
    Extracts audio from a video file using FFmpeg.
    Outputs WAV audio (pcm_s16le), mono by default, at a specified sample rate.

    Args:
        video_path (str): Path to the input video file.
        audio_output_path (str): Path for the output WAV audio file.
        sample_rate (int): Target audio sample rate (e.g., 16000 for speech).
        channels (int): Target number of audio channels (1 for mono, 2 for stereo).

    Returns:
        tuple: (success (bool), error_message (str | None))
    """
    if not os.path.exists(video_path):
        return False, f"Input video file not found: {video_path}"

    command = [
        FFMPEG_PATH,
        '-hide_banner',       # Suppress version and config info printout
        '-loglevel', 'warning', # Reduce verbosity, show errors/warnings
        '-y',                 # Overwrite output file if it exists
        '-i', video_path,     # Input file
        '-vn',                # Disable video recording (audio only)
        '-acodec', 'pcm_s16le', # Audio Codec: PCM signed 16-bit little-endian (standard WAV)
        '-ac', str(channels), # Set number of audio channels (1 = mono)
        '-ar', str(sample_rate),# Set audio sample rate (e.g., 16000 Hz)
        audio_output_path     # Output file path
    ]
    return _run_ffmpeg_command(command, f"audio extraction ({sample_rate}Hz, {channels}-ch)")

def create_clip(input_video_path, output_clip_path, start_time, end_time, re_encode=True):
    """
    Creates a video clip from input_video_path between start_time and end_time (in seconds).

    Args:
        input_video_path (str): Path to the source video file.
        output_clip_path (str): Path where the clipped video file will be saved.
        start_time (float): Start time of the clip in seconds.
        end_time (float): End time of the clip in seconds.
        re_encode (bool): If True (default), re-encodes the clip (accurate cuts, slower).
                          If False, uses stream copy (fast, inaccurate cuts on non-keyframes).

    Returns:
        tuple: (success (bool), result (str | None))
               result is output_clip_path on success, error_message on failure.
    """
    if not os.path.exists(input_video_path):
        return False, f"Input video file not found for clipping: {input_video_path}"

    duration = round(end_time - start_time, 3)
    if duration <= 0:
        return False, f"Invalid clip duration: start={start_time:.3f}s, end={end_time:.3f}s (Duration: {duration:.3f}s <= 0)"

    # Check start/end times against video duration if possible
    source_duration = get_video_duration(input_video_path)
    if source_duration is not None: # If ffprobe worked
         if start_time < 0:
             logger.warning(f"Clip start time {start_time:.3f}s is negative, adjusting to 0.")
             start_time = 0.0
         if end_time > source_duration + 0.5: # Allow slight over-run for safety margin?
              logger.warning(f"Clip end time {end_time:.3f}s exceeds video duration {source_duration:.3f}s. Clamping end time.")
              end_time = source_duration
         # Recalculate duration after clamping
         duration = round(end_time - start_time, 3)
         if duration <= 0:
             return False, f"Invalid clip duration after clamping start/end times to video boundaries ({start_time:.3f}s - {end_time:.3f}s)."

    # Build FFmpeg command
    description = f"clip creation ({start_time:.3f}s to {end_time:.3f}s, duration {duration:.3f}s)"
    command = [
        FFMPEG_PATH,
        '-hide_banner',
        '-loglevel', 'warning',
        # Input flags: Use -ss AFTER -i for accuracy. -to is often more robust than -t duration.
        '-i', input_video_path,
        '-ss', f"{start_time:.3f}",  # Use formatted string for accuracy
        '-to', f"{end_time:.3f}",    # Use formatted string
        '-y',                       # Overwrite output
        '-map_metadata', '-1',      # Strip global metadata (optional)
        '-map_chapters', '-1',      # Strip chapters (optional)
    ]

    if re_encode:
        description += " [Re-encode]"
        # Standard re-encoding parameters (adjust as needed)
        command.extend([
            # Video Options
            '-c:v', 'libx264',       # Widely compatible H.264 codec
            '-preset', 'medium',     # Balance between speed and compression (faster, fast, medium, slow...)
            '-crf', '23',            # Constant Rate Factor (Quality: 18=high, 23=good, 28=low)
            '-pix_fmt', 'yuv420p',   # Essential for broad player compatibility
            # '-profile:v', 'high',  # Optional: Specify H.264 profile if needed
            # '-level:v', '4.0',     # Optional: Specify H.264 level (constraints)

            # Audio Options
            '-c:a', 'aac',           # Common AAC audio codec
            '-b:a', '128k',          # Standard audio bitrate (adjust if desired, e.g., 192k, 256k)
            '-ac', '2',              # Number of audio channels (stereo) - change if mono desired

            # Container Options
            '-movflags', '+faststart' # CRUCIAL for web playback (moves index to start)
        ])
    else: # Stream Copy
        description += " [Stream Copy]"
        # Copy streams directly - FAST but inaccurate cuts (only at keyframes)
        command.extend([
            '-c', 'copy',              # Copy all streams (video, audio, subtitles etc.)
            '-avoid_negative_ts', 'make_zero', # Fix potential negative timestamps often needed with stream copy cuts
            # Note: Stream copy IGNORES most quality/codec settings above.
            # May require `-copyts` if precise timestamp inheritance is needed, but can cause issues.
        ])

    # Add the output file path at the end
    command.append(output_clip_path)

    # Execute using the helper
    success, result = _run_ffmpeg_command(command, description)

    if success:
        # On success, result should be None, return the output path
        return True, output_clip_path
    else:
        # On failure, result contains the error message
        return False, result


def get_video_duration(video_path):
    """Gets the duration of a video file in seconds using ffprobe. Returns None on failure."""
    if not _FFPROBE_CHECKED: # Check if ffprobe check was run
        logger.debug("Re-checking for FFprobe before getting duration...")
        check_ffmpeg_tools() # Try to check again

    if not FFPROBE_AVAILABLE:
        logger.warning("Cannot get video duration: ffprobe is not available or configured correctly.")
        return None # Cannot proceed without ffprobe
    if not os.path.exists(video_path):
         logger.warning(f"Cannot get video duration: File not found at '{video_path}'")
         return None

    # Use the guessed path if available
    ffprobe_cmd_path = FFPROBE_PATH_GUESS
    if not ffprobe_cmd_path: # Should not happen if FFPROBE_AVAILABLE is True, but safety check
        logger.error("Internal state error: FFPROBE_AVAILABLE is True but path guess is missing.")
        return None

    command = [
        ffprobe_cmd_path,
        '-v', 'error',                            # Show only critical errors from ffprobe itself
        '-show_entries', 'format=duration',      # Ask specifically for the 'duration' field within the 'format' section
        '-of', 'default=noprint_wrappers=1:nokey=1', # Output format: Print only the value, no key/wrapper
        '-select_streams', 'v:0',                # Optional: Get duration of the first video stream (sometimes more reliable?)
        # Or probe format instead: -select_streams '' (empty string might probe format)
        video_path
    ]
    description = f"duration query for {os.path.basename(video_path)}"
    logger.debug(f"Running ffprobe for {description}: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            check=True,                 # Raise error on non-zero exit
            capture_output=True,        # Capture stdout/stderr
            text=True,                  # Decode as text
            encoding='utf-8',
            timeout=60                  # Generous timeout for probing potentially large/slow files
        )
        duration_str = result.stdout.strip()

        # Validate the output - should be a floating-point number string
        if not duration_str or duration_str.lower() == 'n/a':
            logger.warning(f"ffprobe did not return a valid duration value for '{video_path}'. Output: '{duration_str}'. Trying format section...")
            # Fallback: Query format section explicitly if stream query failed
            command_format = [ffprobe_cmd_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', video_path]
            try:
                 result_format = subprocess.run(command_format, check=True, capture_output=True, text=True, encoding='utf-8', timeout=60)
                 duration_str = result_format.stdout.strip().split('\n')[0] # Use first line if multiple
                 logger.info(f"Retrieved duration from format section: {duration_str}")
                 if not duration_str or duration_str.lower() == 'n/a':
                      logger.error(f"ffprobe failed to find duration in video stream or format section for '{video_path}'.")
                      return None
            except Exception as fmt_err:
                  logger.error(f"ffprobe secondary duration check (format section) failed for '{video_path}': {fmt_err}", exc_info=True)
                  return None


        # Convert valid string to float
        duration_sec = float(duration_str)
        if duration_sec < 0:
             logger.warning(f"ffprobe returned negative duration ({duration_sec:.3f}s) for '{video_path}'. Treating as invalid.")
             return None

        logger.info(f"Duration of '{os.path.basename(video_path)}': {duration_sec:.3f} seconds.")
        return duration_sec

    except FileNotFoundError:
        # This should be caught by FFPROBE_AVAILABLE check, but redundant check here.
        logger.error(f"ffprobe command '{ffprobe_cmd_path}' not found during execution. Check configuration.")
        FFPROBE_AVAILABLE = False # Mark as unavailable if fails during use
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timed out after 60s getting duration for '{video_path}'. File might be corrupted or inaccessible.")
        return None
    except subprocess.CalledProcessError as e:
        # Log the error output from ffprobe if it fails
        stderr_msg = e.stderr.strip() if e.stderr else "(no stderr captured)"
        logger.error(f"ffprobe failed for '{video_path}' (exit code {e.returncode}). Command: '{' '.join(command)}'. Stderr: {stderr_msg}")
        return None
    except ValueError as e:
        stdout_val = result.stdout.strip() if 'result' in locals() else "(ffprobe output unknown)"
        logger.error(f"Could not parse ffprobe duration output ('{stdout_val}') as a float number for '{video_path}': {e}")
        return None
    except Exception as e:
        # Catch-all for any other unexpected error
        logger.error(f"Unexpected error getting video duration for '{video_path}': {e}", exc_info=True)
        return None

def sanitize_filename(filename, max_len=200, replacement_char='_'):
    """Removes or replaces characters problematic for filenames across OS, limiting length."""
    if not isinstance(filename, str) or not filename:
        return f"sanitized_empty_filename_{int(time.time())}" # Ensure uniqueness if empty

    # Remove leading/trailing whitespace, dots, and replacement characters themselves
    filename = filename.strip().strip('.' + replacement_char)

    # Define regex for characters to replace:
    # Includes standard problematic chars: <>:"/\|?*%
    # Includes control characters (ASCII 0-31)
    # Optionally include others like apostrophe ' if causing issues
    bad_chars_pattern = r'[<>:"/\\|?*\x00-\x1F%\']' # Includes single quote
    filename = re.sub(bad_chars_pattern, replacement_char, filename)

    # Replace multiple consecutive spaces or replacement characters with a single replacement character
    # Escape the replacement char in case it's a regex special char like '.'
    pattern = r'[\s' + re.escape(replacement_char) + r']+'
    filename = re.sub(pattern, replacement_char, filename)

    # Limit overall filename length (important for many filesystems)
    # Encoding to UTF-8 helps handle multi-byte characters correctly regarding length limits.
    try:
        filename_bytes = filename.encode('utf-8')
        if len(filename_bytes) > max_len:
            # Truncate byte string smartly (try not to cut mid-character)
            # Find the last byte index within max_len that starts a UTF-8 character
            # Bytes starting with 10xxxxxx are continuation bytes
            cut_pos = max_len
            while cut_pos > 0 and (filename_bytes[cut_pos] & 0xC0) == 0x80: # While it's a continuation byte
                 cut_pos -= 1
            # If we backed up too far (e.g., max_len was very small), just force truncate.
            if cut_pos == 0 and max_len > 0: cut_pos = max_len

            filename_bytes = filename_bytes[:cut_pos]
            # Decode back to string, ignoring potential errors from crude cut (though we tried to avoid)
            filename = filename_bytes.decode('utf-8', errors='ignore')
            # Remove any trailing replacement characters possibly created by truncation
            filename = filename.rstrip(replacement_char)
            logger.debug(f"Filename truncated to {len(filename_bytes)} bytes / {len(filename)} chars.")

    except Exception as e:
        logger.warning(f"Error during filename length sanitization: {e}. Using basic string slice.")
        filename = filename[:max_len] # Fallback to simple string slicing if encoding/decoding fails

    # Handle reserved filenames on Windows (case-insensitive check)
    # Check the base name part without extension
    name_part, dot, ext_part = filename.rpartition('.')
    base_name_to_check = name_part if dot else filename
    reserved_names = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
    if base_name_to_check.upper() in reserved_names:
        filename = filename + replacement_char # Append replacement char if reserved name conflict

    # Final check: ensure filename is not empty or just the replacement char after all sanitization
    if not filename or filename == replacement_char:
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"sanitized_file_{timestamp}" # Provide a unique fallback

    return filename

# Note: Subtitle burning function 'burn_subtitles' was not included in the prompt's definition
# of 'project_three.md', so it's omitted here. If needed, it could be added similarly to
# how extract_audio or create_clip call _run_ffmpeg_command.