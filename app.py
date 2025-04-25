# --- Start of File: app.py ---
import logging
import logging.handlers # For FileHandler
import os
import time # Keep for SSE sleep
import json
import datetime
import sys # Keep for logging and potential exit

from flask import (Flask, Response, render_template, request, redirect, url_for,
                   flash, jsonify, session, abort, send_from_directory)
from werkzeug.utils import secure_filename # Keep if needed elsewhere, good practice
from config import Config # Import configuration class
import database as db # Import database operations module

# <<< MODIFIED: Import Celery tasks from new locations >>>
from celery_app import celery_app
from tasks.video_tasks import (
    download_task,
    extract_audio_task,
    transcribe_task,
    diarize_full_audio_task,
    identify_exchanges_task
)
from tasks.exchange_tasks import (
    process_exchange_diarization_task,
    define_short_clips_task,
    cut_short_clips_task
)
# Removed old imports if any existed referencing pipeline directly for tasks

from utils import download, media_utils, error_utils # Import utility modules

# --- Global Configuration ---
config = Config()

# --- App Initialization & Basic Config ---
app = Flask(__name__, instance_relative_config=False)
app.config.from_object(config) # Load config from Config object

# ======================================
# === Logging Configuration ===
# ======================================
# (Logging setup remains the same)
log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(threadName)s] [%(name)s] %(message)s')
log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
console_handler = logging.StreamHandler(sys.stdout); console_handler.setFormatter(log_formatter)
log_dir = os.path.dirname(config.LOG_FILE_PATH)
if log_dir and not os.path.exists(log_dir): os.makedirs(log_dir, exist_ok=True)
file_handler = logging.handlers.RotatingFileHandler(config.LOG_FILE_PATH, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(log_formatter)
logging.getLogger().handlers.clear(); logging.basicConfig(level=log_level, handlers=[console_handler, file_handler])
flask_logger = logging.getLogger('werkzeug'); flask_logger.setLevel(log_level)
app.logger.info("="*50); app.logger.info("Flask application starting up (Refactored Tasks)..."); app.logger.info(f"Log Level: {config.LOG_LEVEL}"); app.logger.info(f"DB Path: {config.DATABASE_PATH}"); app.logger.info(f"Celery Broker: {config.CELERY_BROKER_URL}"); app.logger.info(f"Download Dir: {config.DOWNLOAD_DIR}"); app.logger.info(f"Clips Dir: {config.PROCESSED_CLIPS_DIR}"); app.logger.info(f"SSE Poll: {config.SSE_POLL_INTERVAL_SECONDS}s");
app.logger.info("="*50)


# --- DB Initialization ---
try:
    with app.app_context(): db.init_db()
    app.logger.info("Database initialization check complete.")
except Exception as e: app.logger.critical(f"FATAL: DB init failed: {e}. Application cannot start.", exc_info=True); raise RuntimeError(f"DB init failed: {e}") from e

# ======================================
# === Jinja Filters & Context Processors ===
# ======================================
# (Filters and context processors remain the same)
@app.template_filter('datetimeformat')
def format_datetime(value, format='%Y-%m-%d %H:%M'):
    if not value: return "N/A"
    try:
        value_str = str(value).split('+')[0].split('Z')[0].split('.')[0]
        dt_obj = datetime.datetime.fromisoformat(value_str)
        return dt_obj.strftime(format)
    except (ValueError, TypeError):
        try:
            dt_obj = datetime.datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
            return dt_obj.strftime(format)
        except (ValueError, TypeError):
            return value

@app.template_filter('basename')
def basename_filter(value):
    return os.path.basename(value) if value and isinstance(value, str) else ""

@app.template_filter('dirname')
def dirname_filter(value):
    return os.path.dirname(value) if value and isinstance(value, str) else ""

@app.context_processor
def inject_current_year(): return {'current_year': datetime.datetime.now().year}

@app.context_processor
def inject_config(): return {'config': config}

# ======================================
# === Request Logging Middleware ===
# ======================================
# (Middleware remains the same)
@app.before_request
def log_request_info():
    if request.path.startswith(('/static', '/stream_updates')):
        return
    app.logger.info(f"Request <-- {request.remote_addr} - {request.method} {request.path}")

@app.after_request
def log_response_info(response):
    if request.path.startswith(('/static', '/stream_updates')):
        return response
    if request.path == '/favicon.ico' and response.status_code == 404:
        return response
    app.logger.info(f"Response --> {request.remote_addr} - {request.method} {request.path} - Status: {response.status_code}")
    return response

# ======================================
# === Status Calculation Helper ===
# ======================================
def _calculate_overall_status(video_dict):
    """
    Calculates a simplified overall status and current step display string
    based on the granular statuses in a video dictionary.

    Args:
        video_dict (dict): A dictionary representing a video record from the DB,
                           containing all granular status and error fields.

    Returns:
        tuple: (overall_status (str), current_step_display (str), overall_status_class (str))
               e.g., ('Error', 'Download Failed', 'error')
               e.g., ('Processing', 'Transcribing...', 'processing')
               e.g., ('Complete', 'All Steps Complete', 'complete')
    """
    if not video_dict:
        return 'Unknown', 'N/A', 'unknown'

    # Define the order of steps for status checking
    steps_in_order = ['download', 'audio', 'transcript', 'diarization', 'exchange_id']
    step_display_names = {
        'download': 'Download', 'audio': 'Audio Extraction', 'transcript': 'Transcription',
        'diarization': 'Diarization', 'exchange_id': 'Exchange ID'
    }

    # Check for Errors first
    for step in steps_in_order:
        if video_dict.get(f"{step}_status") == 'Error':
            return 'Error', f"{step_display_names[step]} Failed", 'error'

    # Check for Running steps
    for step in steps_in_order:
        if video_dict.get(f"{step}_status") == 'Running':
            return 'Processing', f"{step_display_names[step]}...", 'processing' # Use 'processing' class

    # Check for Queued steps
    for step in steps_in_order:
        if video_dict.get(f"{step}_status") == 'Queued':
            return 'Queued', f"Queued for {step_display_names[step]}", 'queued'

    # Check if all steps are Complete
    all_complete = True
    for step in steps_in_order:
        if video_dict.get(f"{step}_status") != 'Complete':
            all_complete = False
            break
    if all_complete:
        return 'Complete', 'All Steps Complete', 'complete'

    # Check if ready for next step (e.g., download done, ready for audio)
    if video_dict.get('download_status') == 'Complete' and video_dict.get('audio_status') == 'Pending':
         return 'Ready', 'Ready for Audio Extraction', 'ready'
    if video_dict.get('audio_status') == 'Complete' and video_dict.get('transcript_status') == 'Pending':
         return 'Ready', 'Ready for Transcription', 'ready'
    if video_dict.get('audio_status') == 'Complete' and video_dict.get('diarization_status') == 'Pending':
         # Handles case where transcript might finish before diarization or vice-versa
         return 'Ready', 'Ready for Diarization', 'ready'
    if video_dict.get('transcript_status') == 'Complete' and video_dict.get('exchange_id_status') == 'Pending':
         return 'Ready', 'Ready for Exchange ID', 'ready'

    # Default to Pending (usually pending download)
    return 'Pending', 'Pending Download', 'pending'


# ======================================
# === Core Routes ===
# ======================================

@app.route('/', methods=['GET', 'POST'])
def index():
    """ Handles the main page: displaying video list and queuing new videos for DOWNLOAD only. """
    if request.method == 'POST':
        # --- Handle New Video Submission ---
        # (POST logic remains largely the same, but ensures download_task is imported correctly)
        app.logger.info("Received POST to queue videos for INITIAL DOWNLOAD")
        youtube_urls_text = request.form.get('urls', ''); resolution = request.form.get('resolution', '480p')
        raw_urls = [url.strip() for url in youtube_urls_text.splitlines() if url.strip()]
        if not raw_urls: flash('Please enter at least one YouTube URL.', 'warning'); return redirect(url_for('index'))
        if not resolution: resolution = '480p'; flash('Resolution not selected, defaulting to 480p.', 'warning')
        queued_count=0; failed_count=0; warning_count=0; url_results=[]
        for url in raw_urls:
            app.logger.info(f"Attempting to queue initial download for URL: {url} at resolution: {resolution}")
            video_id = None
            try:
                title, fetch_error = download.get_video_info(url)
                if title is None:
                     err_msg = f"Failed info fetch: {fetch_error}"; app.logger.warning(f"Skipping URL '{url}': {err_msg}")
                     url_results.append({'url': url, 'status': 'warning', 'message': err_msg}); warning_count += 1; continue

                video_id = db.add_video_job(url, title, resolution)
                if not video_id:
                    err_msg = "Failed DB job creation."; app.logger.error(f"DB Error for URL '{url}': {err_msg}")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg}); failed_count += 1; continue

                safe_title = media_utils.sanitize_filename(title or "video")[:60]; subfolder = f"{video_id}_{safe_title}"
                download_subdir = os.path.join(config.DOWNLOAD_DIR, subfolder); fname_base = f"video_{resolution}"
                # Guess path with .mp4, but actual extension handled by downloader/DB update
                fpath_guess = os.path.join(download_subdir, fname_base + ".mp4")
                try: os.makedirs(download_subdir, exist_ok=True)
                except OSError as e:
                    err_msg = f"Failed dir creation '{download_subdir}': {e}"; app.logger.error(err_msg)
                    db.update_video_step_status(video_id, 'download', 'Error', error_message=err_msg)
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg}); failed_count += 1; continue

                path_updated = db.update_video_path(video_id, fpath_guess)
                if not path_updated: # Handles unique constraint error via return value
                    err_msg = f"DB error setting path for Job ID {video_id} (likely path conflict)."
                    app.logger.error(f"Error for URL '{url}': {err_msg}")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg}); failed_count += 1; continue

                try:
                    db.update_video_step_status(video_id, 'download', 'Queued')
                    # <<< MODIFIED: Call imported task >>>
                    download_task.delay(video_id=video_id)
                    app.logger.info(f"Dispatched DOWNLOAD Celery task for Video ID: {video_id}")
                    url_results.append({'url': url, 'status': 'success', 'message': f"Queued '{title}' for download (Job ID: {video_id})."}); queued_count += 1
                except Exception as dispatch_err:
                    err_msg = f"Failed dispatch download job: {dispatch_err}"; app.logger.error(f"{err_msg} Video ID: {video_id}", exc_info=True)
                    db.update_video_step_status(video_id, 'download', 'Error', error_message=f"Queueing error: {err_msg}")
                    url_results.append({'url': url, 'status': 'error', 'message': err_msg}); failed_count += 1; continue
            except Exception as e:
                err_fmt = error_utils.format_error(e, False); app.logger.error(f"Error queuing URL {url}: {e}", exc_info=True)
                if video_id: db.update_video_step_status(video_id, 'download', 'Error', error_message=f"Setup error: {err_fmt}")
                url_results.append({'url': url, 'status': 'error', 'message': f"Setup error: {err_fmt}"}); failed_count += 1; continue

        # Flash summary (logic unchanged)
        if queued_count > 0: flash(f"{queued_count} video(s) queued for download.", "success")
        shown=0; limit=5
        for res in url_results:
             if res['status'] == 'error' and shown < limit: flash(f"Error '{res['url']}': {res['message']}", "danger"); shown+=1
             elif res['status'] == 'warning' and shown < limit: flash(f"Warning '{res['url']}': {res['message']}", "warning"); shown+=1
        if failed_count > shown: flash(f"{failed_count - shown} other job(s) failed during setup/queueing.", "danger")
        if warning_count > shown: flash(f"{warning_count - shown} other URL(s) had warnings.", "warning")
        return redirect(url_for('index'))

    # --- Handle GET Request ---
    try:
        videos_raw = db.get_all_videos(order_by='created_at', desc=True)
        videos_processed = []
        # <<< ADDED: Calculate derived status for each video >>>
        for video in videos_raw:
            overall_status, current_step_display, overall_status_class = _calculate_overall_status(video)
            video_dict = dict(video) # Convert Row object to dict if needed, or work directly
            video_dict['overall_status'] = overall_status
            video_dict['current_step_display'] = current_step_display
            video_dict['overall_status_class'] = overall_status_class
            videos_processed.append(video_dict)
    except Exception as e:
        app.logger.error(f"Error retrieving videos: {e}", exc_info=True)
        flash("Error fetching video list.", "danger"); videos_processed = []

    # Pass the processed list (with derived statuses) to the template
    return render_template('index.html', videos=videos_processed)


@app.route('/video/<int:video_id>')
def video_details(video_id):
    # (No significant changes needed here, template handles display based on DB fields)
    app.logger.info(f"Request details for Video ID: {video_id}")
    try:
        video = db.get_video_by_id(video_id)
        if not video:
            app.logger.warning(f"Video ID {video_id} not found in database.")
            abort(404, description=f"Video ID {video_id} not found.")

        long_exchanges = db.get_long_exchanges_for_video(video_id)

        def safe_json_load(json_string, default_value=None):
            if not json_string: return default_value
            try: return json.loads(json_string)
            except json.JSONDecodeError as e: app.logger.error(f"Invalid JSON (vid {video_id}): {e}. Content: {json_string[:100]}..."); return default_value

        transcript_data = safe_json_load(video.get('transcript'), default_value=[])
        full_diarization_data = safe_json_load(video.get('full_diarization_result'), default_value=[])
        generated_clips = safe_json_load(video.get('generated_clips'), default_value=[])

        # Calculate overall status for display in the details header (optional, but consistent)
        overall_status, current_step_display, _ = _calculate_overall_status(video)
        # Add to video dict if needed by template directly (or template can use existing fields)
        video_dict_for_template = dict(video)
        video_dict_for_template['overall_status_derived'] = overall_status
        video_dict_for_template['current_step_derived'] = current_step_display

        return render_template('video_details.html',
                               video=video_dict_for_template, # Pass modified dict
                               long_exchanges=long_exchanges,
                               transcript_data=transcript_data,
                               full_diarization_data=full_diarization_data,
                               generated_clips=generated_clips
                               )
    except Exception as e:
        app.logger.error(f"Error loading details for Video ID {video_id}: {e}", exc_info=True)
        flash("Error loading video details page.", "danger")
        return redirect(url_for('index'))


# ==================================================
# === Granular Task Trigger Routes (Phase 1) ===
# ==================================================
# (Logic remains same, just ensures correct task functions are called)
def _trigger_step(video_id, step_name, task_func, required_prev_steps):
    """ Helper to handle common logic for triggering a granular step. """
    app.logger.info(f"Received trigger request for step '{step_name}' on video ID: {video_id}")
    video = db.get_video_by_id(video_id)
    if not video: return jsonify({"success": False, "error": "Video not found."}), 404

    for prev_step, required_status in required_prev_steps.items():
        current_prev_status = video.get(f"{prev_step}_status")
        if current_prev_status != required_status:
            error_msg = f"Cannot start '{step_name}'. Prerequisite '{prev_step}' is not '{required_status}' (current: '{current_prev_status}')."
            app.logger.warning(f"Trigger failed for vid {video_id}: {error_msg}")
            return jsonify({"success": False, "error": error_msg}), 400

    reset_ok = db.update_video_step_status(video_id, step_name, 'Queued', error_message=None)
    if not reset_ok:
        return jsonify({"success": False, "error": "DB error updating status before queueing."}), 500

    try:
        # Dispatch using the passed task_func (already imported correctly)
        task_func.delay(video_id=video_id)
        app.logger.info(f"Dispatched '{step_name}' task for Video ID: {video_id}")
        return jsonify({"success": True, "message": f"'{step_name.replace('_', ' ').capitalize()}' task queued successfully."}), 200
    except Exception as dispatch_err:
        error_msg = f"Failed to dispatch {step_name} job: {dispatch_err}"
        app.logger.error(f"{error_msg} Video ID: {video_id}", exc_info=True)
        db.update_video_step_status(video_id, step_name, 'Error', error_message=f"Queueing error: {error_msg}")
        return jsonify({"success": False, "error": "Failed to queue job."}), 500

# <<< MODIFIED: Routes call correctly imported tasks >>>
@app.route('/video/<int:video_id>/trigger_download', methods=['POST'])
def trigger_download(video_id):
    return _trigger_step(video_id, 'download', download_task, {})

@app.route('/video/<int:video_id>/trigger_audio', methods=['POST'])
def trigger_audio(video_id):
    return _trigger_step(video_id, 'audio', extract_audio_task, {'download': 'Complete'})

@app.route('/video/<int:video_id>/trigger_transcript', methods=['POST'])
def trigger_transcript(video_id):
    return _trigger_step(video_id, 'transcript', transcribe_task, {'audio': 'Complete'})

# Modified route name for clarity - matches task name
@app.route('/video/<int:video_id>/trigger_diarization', methods=['POST'])
def trigger_diarize_full(video_id):
    # Corrected step name mapping to trigger diarize_full_audio_task
    return _trigger_step(video_id, 'diarization', diarize_full_audio_task, {'audio': 'Complete'})

# Modified route name for clarity
@app.route('/video/<int:video_id>/trigger_exchange_id', methods=['POST'])
def trigger_identify_exchanges(video_id):
    # Corrected step name mapping to trigger identify_exchanges_task
    return _trigger_step(video_id, 'exchange_id', identify_exchanges_task, {'transcript': 'Complete'})


# =====================================================
# === Granular Task Trigger Routes (Phase 2) ===
# =====================================================
# (Logic remains same, just ensures correct task functions are called)
def _trigger_exchange_substep(exchange_db_id, substep_name, task_func, required_parent_steps, required_exchange_steps):
    """ Helper for triggering Phase 2 substeps operating on a specific exchange. """
    app.logger.info(f"Received trigger request for exchange substep '{substep_name}' on exchange DB ID: {exchange_db_id}")
    exchange_data = db.get_long_exchange_by_id(exchange_db_id)
    if not exchange_data: return jsonify({"success": False, "error": f"Exchange record {exchange_db_id} not found."}), 404

    video_id = exchange_data.get('video_id')
    if not video_id: return jsonify({"success": False, "error": f"Parent video ID missing for exchange {exchange_db_id}."}), 500

    video_data = db.get_video_by_id(video_id)
    if not video_data: return jsonify({"success": False, "error": f"Parent video record {video_id} not found."}), 404

    for parent_step, required_status in required_parent_steps.items():
        current_parent_status = video_data.get(f"{parent_step}_status")
        if current_parent_status != required_status:
            error_msg = f"Cannot start '{substep_name}' for exchange {exchange_db_id}. Parent video prerequisite '{parent_step}' is not '{required_status}' (current: '{current_parent_status}')."
            app.logger.warning(error_msg)
            return jsonify({"success": False, "error": error_msg}), 400

    for ex_step, required_status in required_exchange_steps.items():
        current_ex_status = exchange_data.get(f"{ex_step}_status")
        if current_ex_status != required_status:
            error_msg = f"Cannot start '{substep_name}' for exchange {exchange_db_id}. Prerequisite step '{ex_step}' is not '{required_status}' (current: '{current_ex_status}')."
            app.logger.warning(error_msg)
            return jsonify({"success": False, "error": error_msg}), 400

    reset_ok = db.update_exchange_substep_status(exchange_db_id, substep_name, 'Queued', error_message=None)
    if not reset_ok:
        return jsonify({"success": False, "error": "DB error updating exchange status before queueing."}), 500

    try:
        # Dispatch using the passed task_func (already imported correctly)
        task_func.delay(long_exchange_db_id=exchange_db_id)
        app.logger.info(f"Dispatched '{substep_name}' task for Exchange DB ID: {exchange_db_id}")
        return jsonify({"success": True, "message": f"'{substep_name.replace('_', ' ').capitalize()}' task queued successfully for exchange {exchange_db_id}."}), 200
    except Exception as dispatch_err:
        error_msg = f"Failed to dispatch {substep_name} job for exchange {exchange_db_id}: {dispatch_err}"
        app.logger.error(error_msg, exc_info=True)
        db.update_exchange_substep_status(exchange_db_id, substep_name, 'Error', error_message=f"Queueing error: {error_msg}")
        return jsonify({"success": False, "error": "Failed to queue job."}), 500

# <<< MODIFIED: Routes call correctly imported tasks >>>
@app.route('/exchange/<int:exchange_id>/trigger_process_diarization', methods=['POST'])
def trigger_exchange_diarization(exchange_id):
    # Corrected substep name mapping
    return _trigger_exchange_substep(exchange_id, 'diarization', process_exchange_diarization_task, {'diarization': 'Complete'}, {})

@app.route('/exchange/<int:exchange_id>/trigger_define_clips', methods=['POST'])
def trigger_define_clips(exchange_id):
     # Corrected substep name mapping
    return _trigger_exchange_substep(exchange_id, 'clip_definition', define_short_clips_task, {}, {'diarization': 'Complete'})

@app.route('/exchange/<int:exchange_id>/trigger_cut_clips', methods=['POST'])
def trigger_cut_clips(exchange_id):
    # Corrected substep name mapping
    return _trigger_exchange_substep(exchange_id, 'clip_cutting', cut_short_clips_task, {}, {'clip_definition': 'Complete'})

# =====================================================
# === Manual Interaction Routes ===
# =====================================================
# (Manual exchange route remains the same)
@app.route('/video/<int:video_id>/mark_manual_exchange', methods=['POST'])
def mark_manual_exchange(video_id):
    app.logger.info(f"Received request to mark manual exchange for video {video_id}")
    video = db.get_video_by_id(video_id)
    if not video: return jsonify({"success": False, "error": "Video not found."}), 404

    try:
        start_time = request.form.get('start_time', type=float)
        end_time = request.form.get('end_time', type=float)
        if start_time is None or end_time is None or end_time <= start_time: raise ValueError("Invalid start/end time.")
    except (ValueError, TypeError) as e: return jsonify({"success": False, "error": f"Invalid input data: {e}"}), 400

    success, new_exchange_id = db.add_manual_exchange(video_id, start_time, end_time)

    if success:
        flash("Manual exchange marked successfully.", "success")
        return jsonify({"success": True, "message": "Manual exchange saved.", "new_exchange_id": new_exchange_id}), 201
    else:
        return jsonify({"success": False, "error": "Failed to save manual exchange to database."}), 500

# ======================================
# === Other Routes (Error Log, Delete, Clips) ===
# ======================================
# (These routes remain largely the same, maybe add derived status to error log)
@app.route('/errors')
def error_log():
    app.logger.info("Accessing error log page")
    try:
        error_videos_raw = db.get_videos_with_errors()
        # Add derived first error step if needed (DB function already does this)
        error_videos = error_videos_raw # Use the list returned by DB function
    except Exception as e:
        app.logger.error(f"Error fetching error videos: {e}", exc_info=True);
        flash("Error fetching errored videos.", "danger"); error_videos = []
    return render_template('error_log.html', error_videos=error_videos)


@app.route('/delete-videos', methods=['POST'])
def delete_videos():
    # (Delete logic remains the same)
    record_ids_str = request.form.getlist('selected_videos')
    if not record_ids_str: flash('No videos selected.', 'warning'); return redirect(request.referrer or url_for('index'))
    try: video_ids_to_delete = [int(id_str) for id_str in record_ids_str]; app.logger.info(f"Request delete Video IDs: {video_ids_to_delete}")
    except ValueError: flash('Invalid video ID.', 'danger'); return redirect(request.referrer or url_for('index'))

    deleted_db_count=0; files_deleted=0; files_failed=0; dirs_removed=0; dirs_failed=0
    videos_data = [db.get_video_by_id(vid) for vid in video_ids_to_delete]

    try:
        deleted_db_count = db.delete_video_records(video_ids_to_delete)
        if deleted_db_count > 0: flash(f'Deleted {deleted_db_count} job record(s) from database.', 'success')
        elif not videos_data: flash('No matching video records found to delete.', 'warning')
    except Exception as db_err:
        app.logger.error(f"Error deleting DB records: {db_err}", exc_info=True)
        flash("Error deleting database records.", "danger")

    dirs_to_try_remove = set()
    for video in videos_data:
        if not video: continue
        paths_to_delete = []; download_subdir = None

        main_video_path = video.get('file_path')
        main_audio_path = video.get('audio_path')

        if main_video_path:
             paths_to_delete.append(main_video_path)
             download_subdir = os.path.dirname(main_video_path)
             if download_subdir and download_subdir.startswith(os.path.normpath(config.DOWNLOAD_DIR)) and os.path.normpath(download_subdir) != os.path.normpath(config.DOWNLOAD_DIR):
                  dirs_to_try_remove.add(download_subdir)

        if main_audio_path: paths_to_delete.append(main_audio_path)

        generated_clips_json = video.get('generated_clips')
        try: clip_paths = json.loads(generated_clips_json or '[]')
        except json.JSONDecodeError: clip_paths = []
        if clip_paths and isinstance(clip_paths, list):
             paths_to_delete.extend([p for p in clip_paths if p and isinstance(p, str)])
             clip_parent_dir = os.path.join(config.PROCESSED_CLIPS_DIR, f"video_{video.get('id')}")
             if os.path.isdir(clip_parent_dir): dirs_to_try_remove.add(clip_parent_dir)

        for path in paths_to_delete:
             if path and os.path.isfile(path):
                  try: os.remove(path); app.logger.info(f"Deleted file: {path}"); files_deleted += 1
                  except OSError as e: app.logger.error(f"Error deleting file '{path}': {e}"); files_failed += 1
             elif path: app.logger.warning(f"Path in deletion list is not a file: {path}")

    for dir_path in sorted(list(dirs_to_try_remove), reverse=True):
         try:
             os.rmdir(dir_path)
             app.logger.info(f"Removed empty directory: {dir_path}"); dirs_removed += 1
         except OSError as e:
             if "Directory not empty" not in str(e) and "Errno 39" not in str(e) and "ENOTEMPTY" not in str(e).upper():
                  app.logger.error(f"Error removing directory '{dir_path}': {e}"); dirs_failed += 1
             else:
                  app.logger.info(f"Directory '{dir_path}' not empty or doesn't exist, skipped removal.")
         except Exception as e:
             app.logger.error(f"Unexpected error removing directory '{dir_path}': {e}"); dirs_failed += 1

    if files_deleted > 0: flash(f"Deleted {files_deleted} associated local file(s).", "info")
    if dirs_removed > 0: flash(f"Removed {dirs_removed} empty local directories.", "info")
    if files_failed > 0: flash(f"Failed to delete {files_failed} local file(s). Check logs and permissions.", "warning")
    if dirs_failed > 0: flash(f"Failed to remove {dirs_failed} local directories (may not be empty). Check logs.", "warning")

    return redirect(request.referrer or url_for('index'))


# Manual Clip Creation Route - REMOVED as per refactoring focus
# @app.route('/clip/<int:video_id>', methods=['POST']) ...


@app.route('/clips/<path:filename>')
def serve_clip(filename):
    # (Clip serving logic remains the same)
    clips_dir = config.PROCESSED_CLIPS_DIR
    if not os.path.isdir(clips_dir): abort(404, description="Clip directory not found.")

    if ".." in filename or filename.startswith(("/", "\\")):
        abort(400, description="Invalid filename path component.")

    requested_path = os.path.join(clips_dir, filename)
    safe_abs_path = os.path.abspath(requested_path)
    if not safe_abs_path.startswith(os.path.abspath(clips_dir)):
        abort(403, description="Access denied to requested file path.")

    if not os.path.isfile(safe_abs_path): abort(404, description="Clip file not found.")

    app.logger.debug(f"Serving clip: {filename} from {clips_dir}")
    try: return send_from_directory(clips_dir, filename, as_attachment=False, conditional=True)
    except Exception as e: app.logger.error(f"Error serving '{filename}': {e}", exc_info=True); abort(404)


@app.route('/stream_updates')
def stream_updates():
    """ Streams granular status updates using SSE. """
    # (SSE logic remains the same - relies on DB having correct granular statuses)
    sse_poll_interval = config.SSE_POLL_INTERVAL_SECONDS
    def event_stream():
        last_data_sent = {}; app.logger.info(f"SSE client connected (Poll: {sse_poll_interval}s).")
        while True:
            try:
                active_videos = db.get_active_videos_for_sse()
                updates = {}
                for video in active_videos:
                    # Send all granular statuses
                    video_statuses = {key: video[key] for key in video.keys() if key.endswith('_status')}
                    video_statuses['updated_at'] = format_datetime(video['updated_at'], '%H:%M:%S')
                    updates[video['id']] = video_statuses

                if updates != last_data_sent:
                    current_data_json = json.dumps(updates)
                    yield f"data: {current_data_json}\n\n"
                    last_data_sent = updates

                time.sleep(sse_poll_interval)
            except GeneratorExit: app.logger.info("SSE client disconnected."); break
            except Exception as e: app.logger.error(f"SSE stream error: {e}", exc_info=True); time.sleep(sse_poll_interval * 3)
    return Response(event_stream(), mimetype='text/event-stream')

# ======================================
# === Main Execution Guard ===
# ======================================
if __name__ == '__main__':
    # (Execution logic remains the same)
    use_waitress = True; host = '0.0.0.0'; port = config.PORT
    if not app.debug and use_waitress:
        try: from waitress import serve; app.logger.info(f"Starting Waitress on http://{host}:{port}/"); serve(app, host=host, port=port, threads=config.APP_THREADS or 4)
        except ImportError: app.logger.warning("Waitress not installed. Falling back to Flask dev server."); app.run(host=host, port=port, debug=app.debug)
        except Exception as e: app.logger.critical(f"Failed to start Waitress: {e}", exc_info=True); sys.exit(1)
    else: app.logger.info(f"Starting Flask dev server on http://{host}:{port}/ (Debug: {app.debug})"); app.run(host=host, port=port, debug=app.debug)

# --- END OF FILE: app.py ---