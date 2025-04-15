# --- Start of File: utils/download.py ---
import logging
import os
import time # Import time for throttling logs
import yt_dlp # The core library for downloading YouTube videos
from config import Config # Import application configuration

# Configure logger for this utility module
logger = logging.getLogger(__name__)

# Get configuration instance - needed for FFmpeg path
config = Config()

# ================================================
# === yt-dlp Logger Integration ===
# ================================================
# This class redirects yt-dlp's internal log messages to our application's main logger.
class YTDLLogger:
    """A simple logger adapter for yt-dlp."""
    def debug(self, msg):
        # Only log yt-dlp debug messages if our main logger is also at DEBUG level.
        # Filter out potential download progress lines if they sneak in here.
        if '[download]' not in msg and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[yt-dlp] {msg}")
    def info(self, msg):
        # Map yt-dlp info to our debug to avoid flooding general INFO logs.
         if '[download]' not in msg: # Filter progress lines
            logger.debug(f"[yt-dlp] {msg}") # Log as debug
    def warning(self, msg):
        # Capture warnings like missing ffmpeg more visibly
        logger.warning(f"[yt-dlp] {msg}")
    def error(self, msg):
        logger.error(f"[yt-dlp] {msg}")

# ================================================
# === Get Video Info Function ===
# ================================================
def get_video_info(url):
    """
    Fetches basic video information (primarily title) without downloading the video.
    Uses yt-dlp's extract_info with download=False.

    Args:
        url (str): The YouTube video URL.

    Returns:
        tuple: (title (str | None), error_message (str | None))
               - title: The video title if successfully fetched.
               - error_message: Description of the error if fetching failed.
    """
    logger.info(f"Fetching video info for URL: {url}")
    ydl_opts = {
        'quiet': True,        # Suppress console output from yt-dlp
        'no_warnings': True,  # Suppress yt-dlp warnings
        'logger': YTDLLogger(), # Use our custom logger
        'skip_download': True, # Crucial: Only fetch info, don't download
        'force_generic_extractor': False # Allow specific youtube extractor
    }
    try:
        # Use yt-dlp context manager to ensure cleanup
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info for the given URL
            info_dict = ydl.extract_info(url, download=False)
            # Extract the title from the returned dictionary
            title = info_dict.get('title', None)
            if title:
                logger.info(f"Fetched info for '{title}' (URL: {url})")
                return title, None # Return title and no error
            else:
                logger.warning(f"Could not extract title from info dict for URL: {url}")
                return None, "Could not extract title from video info."
    except yt_dlp.utils.DownloadError as e:
        # Handle specific yt-dlp download errors (like private/unavailable videos)
        logger.error(f"yt-dlp DownloadError fetching info for {url}: {e}")
        # Provide a more user-friendly error message if possible
        if "Private video" in str(e):
            return None, "Video is private."
        if "Video unavailable" in str(e):
            return None, "Video is unavailable."
        return None, f"yt-dlp error: {e}"
    except Exception as e:
        # Handle any other unexpected errors during info fetching
        logger.error(f"Unexpected error fetching video info for {url}: {e}", exc_info=True)
        return None, f"Unexpected error: {e}"

# ================================================
# === Download Video Function ===
# ================================================
def download_video(url, output_dir, filename, resolution="480p"):
    """
    Downloads a video from the given URL using yt-dlp with specified options.

    Args:
        url (str): The YouTube video URL.
        output_dir (str): The directory where the video should be saved.
        filename (str): The base filename (without extension) for the downloaded video.
        resolution (str): The desired video height (e.g., "480p", "1080p"). yt-dlp will try
                          to get the best format matching or below this height.

    Returns:
        tuple: (success (bool), error_message (str | None), final_path (str | None))
               - success: True if download completed without errors recognized by yt-dlp.
               - error_message: Description of the error if download failed.
               - final_path: The actual full path to the downloaded file if successful, otherwise None.
                             (This accounts for the extension added by yt-dlp).
    """
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Define the output template for yt-dlp
    output_template = os.path.join(output_dir, f'{filename}.%(ext)s')

    # --- Progress Hook ---
    downloaded_path_store = {} # Store final path reported by hook
    last_log_time = 0          # Track time of last progress log
    log_interval = 3.0         # Log progress at most every X seconds

    def progress_hook(d):
        nonlocal last_log_time # Allow modifying the outer scope variable
        if d['status'] == 'downloading':
            # --- ADDED PROGRESS LOGGING ---
            current_time = time.time()
            # Throttle logging: Only log if interval has passed
            if current_time - last_log_time >= log_interval:
                percent_str = d.get('_percent_str', '?%').strip()
                speed_str = d.get('_speed_str', 'N/A').strip()
                eta_str = d.get('_eta_str', 'N/A').strip()
                # Log progress at INFO level
                logger.info(f"[Download Progress] {percent_str} | Speed: {speed_str} | ETA: {eta_str} | File: {d.get('filename', '...')}")
                last_log_time = current_time
        elif d['status'] == 'finished':
            final_filename = d.get('filename')
            if final_filename:
                 downloaded_path_store['final_path'] = final_filename
            logger.info(f"Download hook: Status finished. Final filename reported: {final_filename}")
        elif d['status'] == 'error':
            logger.error(f"Download hook: Status error reported.")


    # --- yt-dlp Options ---
    target_height = ''.join(filter(str.isdigit, resolution))
    if not target_height:
        logger.warning(f"Could not extract height from resolution '{resolution}'. Defaulting download format selection.")
        format_selector = 'best[ext=mp4]/best'
    else:
        format_selector = (f'bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]'
                           f'/bestvideo[height<={target_height}]+bestaudio'
                           f'/best[height<={target_height}][ext=mp4]'
                           f'/best[height<={target_height}]'
                           f'/best[ext=mp4]/best')

    ydl_opts = {
        'format': format_selector,
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': False,             # <<< CHANGED to False: Allow yt-dlp to show merge messages >>>
        'noprogress': True,         # <<< Keep True: Disable default bar, use hook instead >>>
        'ffmpeg_location': config.FFMPEG_PATH,
        'postprocessors': [
            # FFmpegEmbedThumbnailPP entry removed
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'logtostderr': False,
        'ignoreerrors': False,
        'logger': YTDLLogger(),   # <<< Keep routing detailed logs >>>
        'progress_hooks': [progress_hook],
        # 'retries': 3,
        # 'ratelimit': 10 * 1024 * 1024,
    }

    logger.info(f"Starting download: URL='{url}', Res='{resolution}', TargetDir='{output_dir}', Filename='{filename}'")
    logger.debug(f"Using yt-dlp format selector: {format_selector}")
    logger.debug(f"Using yt-dlp output template: {output_template}")
    logger.debug(f"Using yt-dlp options: { {k: v for k, v in ydl_opts.items() if k != 'logger'} }")

    try:
        print(f"  Initiating yt-dlp download for {url}...")
        # --- Execute Download ---
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            status_code = ydl.download([url])

        # --- Check Download Status ---
        if status_code == 0:
             final_path = downloaded_path_store.get('final_path')
             if final_path and os.path.exists(final_path):
                 # If merged file exists (common case)
                 logger.info(f"Download successful for {url}. Merged file path: {final_path}")
                 print(f"  Download successful: {os.path.basename(final_path)}")
                 return True, None, final_path
             else:
                 # Check if separate files exist (might happen if merge failed silently?)
                 # Or if hook failed to get the final merged path. Try guessing.
                 logger.warning("Progress hook didn't capture final path or file missing post-download. Attempting to find merged file.")
                 guessed_path_mp4 = os.path.join(output_dir, f'{filename}.mp4')
                 guessed_path_mkv = os.path.join(output_dir, f'{filename}.mkv') # Common merge container
                 if os.path.exists(guessed_path_mp4) and os.path.getsize(guessed_path_mp4) > 0:
                      logger.info(f"Found merged file at guessed path: {guessed_path_mp4}")
                      print(f"  Download successful (guessed path): {os.path.basename(guessed_path_mp4)}")
                      return True, None, guessed_path_mp4
                 elif os.path.exists(guessed_path_mkv) and os.path.getsize(guessed_path_mkv) > 0:
                     logger.info(f"Found merged file at guessed path: {guessed_path_mkv}")
                     print(f"  Download successful (guessed path): {os.path.basename(guessed_path_mkv)}")
                     return True, None, guessed_path_mkv
                 else:
                     # If download reported success (status_code 0) but we can't find the merged file.
                     err = (f"Download reported success (status code 0) but final merged file not found "
                            f"at expected paths ({guessed_path_mp4} or variants).")
                     logger.error(err)
                     print(f"  ERROR: Download confusing - success reported but merged file missing.")
                     return False, err, None
        else:
            err = f"yt-dlp download method returned non-zero status code: {status_code}"
            logger.error(f"{err} for URL: {url}")
            print(f"  ERROR: yt-dlp indicated failure (status code {status_code}). Check logs.")
            return False, err, None

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during download for {url}: {e}", exc_info=False)
        error_reason = f"Download error: {e}"
        print(f"  ERROR: {error_reason}. Check logs.")
        return False, error_reason, None
    except KeyError as e:
         logger.error(f"Invalid configuration key passed to yt-dlp: {e}", exc_info=True)
         error_reason = f"Configuration error for download tool: '{e}'"
         print(f"  ERROR: {error_reason}. Check download options in code.")
         return False, error_reason, None
    except Exception as e:
        logger.error(f"Unexpected error during download for {url}: {e}", exc_info=True)
        error_reason = f"Unexpected error during download: '{e}'"
        print(f"  ERROR: {error_reason}. Check logs.")
        return False, error_reason, None

# --- END OF FILE: utils/download.py ---