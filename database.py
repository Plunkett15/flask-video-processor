# --- Start of File: database.py ---
import sqlite3
import os
import json
import logging
from contextlib import contextmanager, closing # For managing resources like DB connections
import datetime
import time # For generating unique manual IDs
from config import Config # Import application configuration

# Get configuration instance
config = Config()
DATABASE_PATH = config.DATABASE_PATH # Get database path from config

logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """ Provides a managed database connection (WAL mode, Foreign Keys ON). """
    conn = None
    try:
        db_dir = os.path.dirname(DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir); logger.info(f"Created database directory: {db_dir}")
        conn = sqlite3.connect(DATABASE_PATH, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection or PRAGMA error for '{DATABASE_PATH}': {e}", exc_info=True); raise
    finally:
        if conn: conn.close()


def init_db():
    """ Initializes/Verifies the database schema for the granular workflow. """
    logger.info(f"Initializing/Verifying database schema at '{DATABASE_PATH}'...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # === Clean up potential old structures first ===
            cursor.execute('DROP TRIGGER IF EXISTS update_videos_updated_at;')
            cursor.execute('DROP TRIGGER IF EXISTS trigger_videos_updated_at;')
            cursor.execute('DROP TRIGGER IF EXISTS trigger_long_exchange_clips_updated_at;')

            # === Create `videos` Table (Revised Schema) ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_url TEXT NOT NULL,
                    title TEXT,
                    resolution TEXT,
                    download_status TEXT DEFAULT 'Pending',
                    audio_status TEXT DEFAULT 'Pending',
                    transcript_status TEXT DEFAULT 'Pending',
                    diarization_status TEXT DEFAULT 'Pending',
                    exchange_id_status TEXT DEFAULT 'Pending',
                    file_path TEXT UNIQUE,
                    audio_path TEXT,
                    transcript TEXT,
                    full_diarization_result TEXT,
                    generated_clips TEXT DEFAULT '[]',
                    download_error_message TEXT,
                    audio_error_message TEXT,
                    transcript_error_message TEXT,
                    diarization_error_message TEXT,
                    exchange_id_error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.debug("`videos` table schema checked/created (granular).")

            # === Create `long_exchange_clips` Table (Revised Schema) ===
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS long_exchange_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    exchange_label TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('auto', 'manual')),
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    trigger_marker TEXT, -- NULLable, marker text if 'auto' type based on keywords
                    diarization_status TEXT DEFAULT 'Pending',
                    clip_definition_status TEXT DEFAULT 'Pending',
                    clip_cutting_status TEXT DEFAULT 'Pending',
                    diarization_result TEXT,
                    short_clip_definitions TEXT,
                    diarization_error_message TEXT,
                    clip_definition_error_message TEXT,
                    clip_cutting_error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
                    UNIQUE (video_id, exchange_label)
                )
            """)
            logger.debug("`long_exchange_clips` table schema checked/created.")

            # === Create Indexes ===
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_created_at ON videos (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_long_exchange_clips_video_id ON long_exchange_clips (video_id)")
            logger.debug("Indexes checked/created.")

            # === Create `updated_at` Triggers ===
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS trigger_videos_updated_at
                AFTER UPDATE ON videos FOR EACH ROW
                WHEN OLD.updated_at = NEW.updated_at OR OLD.updated_at IS NULL
                BEGIN
                    UPDATE videos SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END;
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS trigger_long_exchange_clips_updated_at
                AFTER UPDATE ON long_exchange_clips FOR EACH ROW
                WHEN OLD.updated_at = NEW.updated_at OR OLD.updated_at IS NULL
                BEGIN
                    UPDATE long_exchange_clips SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END;
            ''')
            logger.debug("`updated_at` triggers checked/created.")

            conn.commit()
            logger.info("Database schema initialization/verification completed successfully.")
    except sqlite3.Error as e:
        logger.critical(f"Database schema initialization FAILED: {e}", exc_info=True); raise

# --- Helper Function ---
def dict_from_row(row: sqlite3.Row | None) -> dict | None:
    """Converts a sqlite3.Row object to a standard Python dictionary."""
    return dict(row) if row else None

# ======================================
# === Video CRUD Operations (Revised) ===
# ======================================

def add_video_job(youtube_url, title, resolution):
    """ Adds a new video job, initializing granular statuses. """
    initial_statuses = {
        'download_status': 'Pending', 'audio_status': 'Pending', 'transcript_status': 'Pending',
        'diarization_status': 'Pending', 'exchange_id_status': 'Pending',
    }
    sql = """
        INSERT INTO videos (youtube_url, title, resolution,
                            download_status, audio_status, transcript_status, diarization_status, exchange_id_status,
                            file_path, generated_clips)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '[]')
    """
    params = (youtube_url, title, resolution,
              initial_statuses['download_status'], initial_statuses['audio_status'],
              initial_statuses['transcript_status'], initial_statuses['diarization_status'],
              initial_statuses['exchange_id_status'])
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, params)
            new_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Added video job record ID: {new_id} for URL: {youtube_url} with initial statuses.")
            return new_id
    except sqlite3.Error as e:
        logger.error(f"Error adding video job record for {youtube_url} to DB: {e}", exc_info=True); return None

def update_video_path(video_id, file_path):
    """ Updates the main video file path. """
    sql = "UPDATE videos SET file_path = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (file_path, video_id)); conn.commit()
        logger.info(f"Updated file_path for video ID {video_id} to: {file_path}")
        return True
    except sqlite3.IntegrityError as e:
         logger.error(f"DB Integrity Error updating file path for video {video_id}: Path '{file_path}' likely already exists (UNIQUE constraint). Error: {e}")
         update_video_step_status(video_id, 'download', 'Error', error_message=f"File path conflict: '{os.path.basename(file_path)}' may already be associated with another job.")
         return False
    except sqlite3.Error as e:
        logger.error(f"Error updating file_path for video ID {video_id}: {e}", exc_info=True); return False

def update_video_audio_path(video_id, audio_path):
    """ Updates the extracted audio file path. """
    sql = "UPDATE videos SET audio_path = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (audio_path, video_id)); conn.commit()
        if audio_path: logger.info(f"Updated audio_path for video ID {video_id}: {audio_path}")
        else: logger.info(f"Cleared audio_path for video ID {video_id} (cleanup).")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating audio_path for video ID {video_id}: {e}", exc_info=True); return False

def update_video_step_status(video_id, step_name, status, error_message=None):
    """ Updates status and optionally clears/sets error for a specific video processing step. """
    valid_steps = ['download', 'audio', 'transcript', 'diarization', 'exchange_id']
    if step_name not in valid_steps:
        logger.error(f"Invalid step_name '{step_name}' provided to update_video_step_status."); return False

    status_col = f"{step_name}_status"
    error_col = f"{step_name}_error_message"
    error_message_truncated = str(error_message)[:3000] if error_message else None

    sql = f"UPDATE videos SET {status_col} = ?, {error_col} = ? WHERE id = ?"
    params = (status, error_message_truncated if status == 'Error' else None, video_id)

    try:
        with get_db_connection() as conn:
            conn.execute(sql, params); conn.commit()
        log_msg = f"Video {video_id} step '{step_name}' status updated to '{status}'."
        if status == 'Error' and error_message_truncated:
            log_msg += f" Error: {error_message_truncated[:100]}..."
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating step '{step_name}' status for video ID {video_id}: {e}", exc_info=True); return False

def update_video_step_result(video_id, step_name, result_data):
    """ Stores the result data (usually JSON) for a specific video processing step. """
    valid_steps_with_results = {
        'transcript': 'transcript',
        'diarization': 'full_diarization_result'
    }
    if step_name not in valid_steps_with_results:
        logger.error(f"Invalid step_name '{step_name}' provided for storing results."); return False

    result_col = valid_steps_with_results[step_name]
    json_string = None
    if result_data is None:
        json_string = None
    elif isinstance(result_data, str):
        json_string = result_data
    else:
        try: json_string = json.dumps(result_data, ensure_ascii=False)
        except TypeError as e: logger.error(f"Data for step '{step_name}' (vid {video_id}) not JSON serializable: {e}", exc_info=True); return False

    sql = f"UPDATE videos SET {result_col} = ? WHERE id = ?"
    try:
        with get_db_connection() as conn:
            conn.execute(sql, (json_string, video_id)); conn.commit()
        logger.info(f"Stored result for step '{step_name}' in column '{result_col}' for video ID {video_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating result for step '{step_name}' (video ID {video_id}): {e}", exc_info=True); return False

def add_generated_clip(video_id, clip_path):
    """ Atomically appends a generated clip path to the video's JSON list. """
    sql_select = "SELECT generated_clips FROM videos WHERE id = ?"
    sql_update = "UPDATE videos SET generated_clips = ? WHERE id = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(sql_select, (video_id,)).fetchone()
            if not row: logger.error(f"Video ID {video_id} not found for adding clip path."); return False

            current_json = row['generated_clips']
            existing_clips = []
            try:
                loaded_clips = json.loads(current_json or '[]')
                if isinstance(loaded_clips, list): existing_clips = loaded_clips
                else: logger.warning(f"Existing generated_clips for vid {video_id} is not a list. Overwriting.")
            except json.JSONDecodeError:
                logger.warning(f"Could not parse existing generated_clips for vid {video_id}. Overwriting.")

            if clip_path not in existing_clips:
                existing_clips.append(clip_path)
                new_json = json.dumps(existing_clips, ensure_ascii=False)
                cursor.execute(sql_update, (new_json, video_id))
                conn.commit()
                logger.info(f"Appended clip path '{os.path.basename(clip_path)}' to video {video_id}.")
                return True
            else:
                logger.info(f"Clip path '{os.path.basename(clip_path)}' already exists for video {video_id}.")
                return True
    except sqlite3.Error as e:
        logger.error(f"Error adding generated clip path for video {video_id}: {e}", exc_info=True); return False

# --- Read Operations (Updated) ---

def get_video_by_id(video_id):
    """ Fetches a video record including all granular status/result fields. """
    sql = "SELECT * FROM videos WHERE id = ?"
    try:
        with get_db_connection() as conn: row = conn.execute(sql, (video_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e: logger.error(f"Error fetching video by ID {video_id}: {e}", exc_info=True); return None

def get_all_videos(order_by='created_at', desc=True):
    """ Fetches all videos, selecting key columns for the index page. """
    direction = 'DESC' if desc else 'ASC'
    allowed_columns = ['id', 'title', 'created_at', 'updated_at', 'resolution']
    if order_by not in allowed_columns: order_by = 'created_at'; logger.warning("Invalid order_by fallback.")

    sql = f"""SELECT id, youtube_url, title, resolution, created_at, updated_at,
                     download_status, audio_status, transcript_status, diarization_status, exchange_id_status,
                     download_error_message, audio_error_message, transcript_error_message, diarization_error_message, exchange_id_error_message
              FROM videos ORDER BY {order_by} {direction}"""
    try:
        with get_db_connection() as conn: rows = conn.execute(sql).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e: logger.error(f"Error fetching all videos: {e}", exc_info=True); return []

def get_active_videos_for_sse():
    """ Fetches IDs and all granular statuses for videos currently being processed. """
    active_statuses = "'Queued', 'Running'"
    sql = f"""
        SELECT id, updated_at,
               download_status, audio_status, transcript_status,
               diarization_status, exchange_id_status
        FROM videos
        WHERE download_status IN ({active_statuses})
           OR audio_status IN ({active_statuses})
           OR transcript_status IN ({active_statuses})
           OR diarization_status IN ({active_statuses})
           OR exchange_id_status IN ({active_statuses})
        ORDER BY updated_at DESC
    """
    try:
        with get_db_connection() as conn: rows = conn.execute(sql).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e: logger.error(f"Error fetching active videos for SSE: {e}", exc_info=True); return []

def get_videos_with_errors():
    """ Fetches videos where ANY step status is 'Error'. """
    error_check = " = 'Error'"
    sql = f"""
        SELECT id, title, updated_at,
               download_status, audio_status, transcript_status,
               diarization_status, exchange_id_status,
               download_error_message, audio_error_message, transcript_error_message,
               diarization_error_message, exchange_id_error_message
        FROM videos
        WHERE download_status {error_check}
           OR audio_status {error_check}
           OR transcript_status {error_check}
           OR diarization_status {error_check}
           OR exchange_id_status {error_check}
        ORDER BY updated_at DESC
     """
    try:
        with get_db_connection() as conn: rows = conn.execute(sql).fetchall()
        videos = []
        for row_dict in [dict_from_row(row) for row in rows]:
            first_error_step = "Unknown"
            first_error_msg = "Multiple errors or unknown"
            for step in ['download', 'audio', 'transcript', 'diarization', 'exchange_id']:
                if row_dict.get(f"{step}_status") == 'Error':
                    first_error_step = step.capitalize().replace('_', ' ')
                    first_error_msg = row_dict.get(f"{step}_error_message", "Error message missing")
                    break
            row_dict['first_error_step'] = first_error_step
            row_dict['first_error_message'] = first_error_msg
            videos.append(row_dict)
        return videos
    except sqlite3.Error as e: logger.error(f"Error fetching videos with errors: {e}", exc_info=True); return []


def delete_video_records(video_ids):
    """ Deletes video records and associated exchange clips via CASCADE. """
    if not video_ids: return 0
    placeholders = ','.join('?' for _ in video_ids)
    sql = f"DELETE FROM videos WHERE id IN ({placeholders})"
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, tuple(video_ids)); deleted_count = cursor.rowcount; conn.commit()
        if deleted_count > 0: logger.info(f"Deleted {deleted_count} video record(s) and related long_exchange_clips (via CASCADE) for IDs: {video_ids}.")
        else: logger.warning(f"Attempted to delete video IDs {video_ids}, but no matching records found.")
        return deleted_count
    except sqlite3.Error as e: logger.error(f"Error deleting video records {video_ids}: {e}", exc_info=True); return 0

# ==============================================
# === Long Exchange CRUD Operations (Revised) ===
# ==============================================

def add_long_exchanges(video_id, exchange_definitions):
    """
    Adds multiple 'auto' type long exchange records.
    Handles definitions with or without a 'marker' key.
    """
    if not exchange_definitions: return True
    data_to_insert = []
    for ex_def in exchange_definitions:
        # Essential keys: id (label), start, end
        if 'id' in ex_def and 'start' in ex_def and 'end' in ex_def:
            data_to_insert.append((
                video_id,
                ex_def.get('id'),        # e.g., "spkchg_0" or "lex_0"
                'auto',                  # Type is still 'auto' as it's auto-detected
                ex_def.get('start'),
                ex_def.get('end'),
                ex_def.get('marker'),    # Will be None if not present in dict
                'Pending', 'Pending', 'Pending' # Initial substep statuses
            ))
        else:
            logger.warning(f"Skipping incomplete exchange definition for video {video_id}: {ex_def}")

    if not data_to_insert:
        logger.warning(f"No valid exchange definitions provided to insert for video {video_id}.")
        return False # Return False indicating nothing was inserted

    # Use ON CONFLICT to reset substep statuses if the same exchange is re-identified
    sql_insert = """
        INSERT INTO long_exchange_clips (
            video_id, exchange_label, type, start_time, end_time, trigger_marker,
            diarization_status, clip_definition_status, clip_cutting_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) -- 9 placeholders
        ON CONFLICT(video_id, exchange_label) DO UPDATE SET
            type=excluded.type, -- Update type in case manual was later marked auto? Unlikely but possible.
            start_time=excluded.start_time,
            end_time=excluded.end_time,
            trigger_marker=excluded.trigger_marker, -- Handles NULL correctly
            -- Reset substep statuses and results on conflict
            diarization_status='Pending',
            clip_definition_status='Pending',
            clip_cutting_status='Pending',
            diarization_result=NULL,
            short_clip_definitions=NULL,
            diarization_error_message=NULL,
            clip_definition_error_message=NULL,
            clip_cutting_error_message=NULL,
            updated_at=CURRENT_TIMESTAMP
    """
    try:
        with get_db_connection() as conn:
            conn.executemany(sql_insert, data_to_insert)
            conn.commit()
        logger.info(f"Added/Updated {len(data_to_insert)} 'auto' long exchange records for video ID {video_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error adding 'auto' long exchanges for video ID {video_id}: {e}", exc_info=True)
        return False

def add_manual_exchange(video_id, start_time, end_time, label_hint="Manual"):
    """ Adds a 'manual' type long exchange record. """
    ts = int(time.time())
    unique_label = f"man_{ts}_{str(start_time).replace('.', 'p')}"
    sql_insert = """
        INSERT INTO long_exchange_clips (
            video_id, exchange_label, type, start_time, end_time,
            diarization_status, clip_definition_status, clip_cutting_status
        ) VALUES (?, ?, 'manual', ?, ?, 'Pending', 'Pending', 'Pending')
    """
    params = (video_id, unique_label, start_time, end_time)
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql_insert, params)
            new_id = cursor.lastrowid
            conn.commit()
        logger.info(f"Added 'manual' long exchange record ID: {new_id} (Label: {unique_label}) for video ID {video_id}.")
        return True, new_id
    except sqlite3.IntegrityError as e:
        logger.error(f"Failed to add manual exchange for video {video_id}: Label '{unique_label}' might already exist. Error: {e}"); return False, None
    except sqlite3.Error as e:
        logger.error(f"Error adding 'manual' long exchange for video ID {video_id}: {e}", exc_info=True); return False, None

def clear_long_exchanges_for_video(video_id, type_filter=None):
    """ Deletes long exchange records for a video, optionally filtering by type ('auto' or 'manual'). """
    sql = "DELETE FROM long_exchange_clips WHERE video_id = ?"
    params = [video_id]
    if type_filter in ['auto', 'manual']:
        sql += " AND type = ?"
        params.append(type_filter)
        log_suffix = f" of type '{type_filter}'"
    else:
        log_suffix = " (all types)"

    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql, tuple(params)); deleted_count = cursor.rowcount; conn.commit()
        logger.info(f"Cleared {deleted_count} long exchange records{log_suffix} for video ID {video_id}.")
        return True
    except sqlite3.Error as e: logger.error(f"Error clearing long exchanges{log_suffix} for video ID {video_id}: {e}", exc_info=True); return False

def get_long_exchanges_for_video(video_id):
    """ Fetches all long exchange records for a video, including substep statuses. """
    sql = "SELECT * FROM long_exchange_clips WHERE video_id = ? ORDER BY start_time ASC"
    try:
        with get_db_connection() as conn: rows = conn.execute(sql, (video_id,)).fetchall()
        return [dict_from_row(row) for row in rows]
    except sqlite3.Error as e: logger.error(f"Error fetching long exchanges for video ID {video_id}: {e}", exc_info=True); return []

def get_long_exchange_by_id(exchange_db_id):
    """ Fetches a single long exchange record by its primary key. """
    sql = "SELECT * FROM long_exchange_clips WHERE id = ?"
    try:
        with get_db_connection() as conn: row = conn.execute(sql, (exchange_db_id,)).fetchone()
        return dict_from_row(row)
    except sqlite3.Error as e: logger.error(f"Error fetching long exchange by DB ID {exchange_db_id}: {e}", exc_info=True); return None

def update_exchange_substep_status(exchange_db_id, substep_name, status, error_message=None):
    """ Updates status and error for a specific exchange substep. """
    valid_substeps = ['diarization', 'clip_definition', 'clip_cutting']
    if substep_name not in valid_substeps:
        logger.error(f"Invalid substep_name '{substep_name}' for update_exchange_substep_status."); return False

    status_col = f"{substep_name}_status"
    error_col = f"{substep_name}_error_message"
    error_message_truncated = str(error_message)[:3000] if error_message else None

    sql = f"UPDATE long_exchange_clips SET {status_col} = ?, {error_col} = ? WHERE id = ?"
    params = (status, error_message_truncated if status == 'Error' else None, exchange_db_id)

    try:
        with get_db_connection() as conn: conn.execute(sql, params); conn.commit()
        log_msg = f"Exchange {exchange_db_id} substep '{substep_name}' status updated to '{status}'."
        if status == 'Error' and error_message_truncated: log_msg += f" Error: {error_message_truncated[:100]}..."; logger.warning(log_msg)
        else: logger.info(log_msg)
        return True
    except sqlite3.Error as e: logger.error(f"Error updating substep '{substep_name}' status for exchange ID {exchange_db_id}: {e}", exc_info=True); return False

def update_exchange_substep_result(exchange_db_id, substep_name, result_data):
    """ Stores JSON results for exchange substeps. """
    valid_substeps_with_results = {
        'diarization': 'diarization_result',
        'clip_definition': 'short_clip_definitions'
    }
    if substep_name not in valid_substeps_with_results:
        logger.error(f"Invalid substep_name '{substep_name}' for storing exchange results."); return False

    result_col = valid_substeps_with_results[substep_name]
    json_string = None
    if result_data is None: json_string = None
    elif isinstance(result_data, str): json_string = result_data
    else:
        try: json_string = json.dumps(result_data, ensure_ascii=False)
        except TypeError as e: logger.error(f"Data for exchange substep '{substep_name}' (exch {exchange_db_id}) not JSON serializable: {e}", exc_info=True); return False

    sql = f"UPDATE long_exchange_clips SET {result_col} = ? WHERE id = ?"
    try:
        with get_db_connection() as conn: conn.execute(sql, (json_string, exchange_db_id)); conn.commit()
        logger.info(f"Stored result for substep '{substep_name}' in column '{result_col}' for exchange ID {exchange_db_id}.")
        return True
    except sqlite3.Error as e: logger.error(f"Error updating result for substep '{substep_name}' (exchange ID {exchange_db_id}): {e}", exc_info=True); return False


# ======================================
# === Reset Operations (Revised) ===
# ======================================

def reset_video_full(video_id: int):
    """ Resets ALL steps and data for a video, preparing for a fresh start (queues download). """
    logger.warning(f"Performing FULL reset for video ID: {video_id}")
    update_fields = {
        'download_status': 'Queued', 'audio_status': 'Pending', 'transcript_status': 'Pending',
        'diarization_status': 'Pending', 'exchange_id_status': 'Pending',
        'audio_path': None, 'transcript': None, 'full_diarization_result': None,
        'generated_clips': '[]', 'download_error_message': None, 'audio_error_message': None,
        'transcript_error_message': None, 'diarization_error_message': None, 'exchange_id_error_message': None,
    }
    set_clauses = [f"{col} = ?" for col in update_fields.keys()]
    params = list(update_fields.values())
    params.append(video_id)
    sql_update_video = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = ?"
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql_update_video, tuple(params))
            rows_affected = cursor.rowcount
            if rows_affected == 0: logger.warning(f"Video ID {video_id} not found during full reset."); return False
            clear_long_exchanges_for_video(video_id) # Clears both 'auto' and 'manual'
            conn.commit()
            logger.info(f"Successfully performed FULL reset for video ID: {video_id}")
            return True
    except sqlite3.Error as e: logger.error(f"Error during FULL reset for video ID {video_id}: {e}", exc_info=True); return False


def reset_video_step(video_id: int, step_name_to_reset: str):
    """ Resets a specific step and all subsequent dependent steps for a video. """
    logger.warning(f"Resetting video ID {video_id} starting from step: {step_name_to_reset}")
    steps_in_order = ['download', 'audio', 'transcript', 'diarization', 'exchange_id']
    steps_with_results = {'transcript': 'transcript', 'diarization': 'full_diarization_result'}
    steps_with_paths = {'audio': 'audio_path'}
    try: reset_start_index = steps_in_order.index(step_name_to_reset)
    except ValueError: logger.error(f"Invalid step name '{step_name_to_reset}' for reset."); return False

    update_fields = {}
    # Reset statuses and errors for the target step and subsequent steps
    for i in range(reset_start_index, len(steps_in_order)):
        step = steps_in_order[i]
        # Set the first step being reset to 'Queued', subsequent ones to 'Pending'
        update_fields[f"{step}_status"] = 'Queued' if i == reset_start_index else 'Pending'
        update_fields[f"{step}_error_message"] = None
        # Reset results/paths for subsequent steps
        if step in steps_with_results: update_fields[steps_with_results[step]] = None
        if step in steps_with_paths: update_fields[steps_with_paths[step]] = None

    # If resetting transcript or earlier, also clear generated clips and ALL exchanges
    # If resetting diarization or exchange_id, only clear 'auto' exchanges (keep manual)
    clear_auto_exchanges = False
    if reset_start_index <= steps_in_order.index('transcript'):
        update_fields['generated_clips'] = '[]'
        # Clear both 'auto' and 'manual' exchanges if resetting from transcript or earlier
        clear_long_exchanges_for_video(video_id)
    elif reset_start_index <= steps_in_order.index('exchange_id'):
        # Clear only 'auto' exchanges if resetting from diarization or exchange_id
        clear_auto_exchanges = True

    if not update_fields: logger.info(f"No fields to update for reset from step '{step_name_to_reset}'."); return True

    set_clauses = [f"{col} = ?" for col in update_fields.keys()]
    params = list(update_fields.values())
    params.append(video_id)
    sql_update_video = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql_update_video, tuple(params)); rows_affected = cursor.rowcount
            if rows_affected == 0: logger.warning(f"Video ID {video_id} not found during step reset."); return False

            # Clear 'auto' exchanges if needed (after main update)
            if clear_auto_exchanges:
                clear_long_exchanges_for_video(video_id, type_filter='auto')

            conn.commit()
            logger.info(f"Successfully reset video ID {video_id} from step '{step_name_to_reset}'.")
            return True
    except sqlite3.Error as e: logger.error(f"Error during step reset for video ID {video_id}: {e}", exc_info=True); return False

def reset_exchange_substeps(exchange_db_id: int):
    """ Resets all Phase 2 substep statuses/results/errors for a specific exchange. """
    logger.warning(f"Resetting all substeps for exchange ID: {exchange_db_id}")
    update_fields = {
        'diarization_status': 'Pending', 'clip_definition_status': 'Pending', 'clip_cutting_status': 'Pending',
        'diarization_result': None, 'short_clip_definitions': None, 'diarization_error_message': None,
        'clip_definition_error_message': None, 'clip_cutting_error_message': None,
    }
    set_clauses = [f"{col} = ?" for col in update_fields.keys()]
    params = list(update_fields.values())
    params.append(exchange_db_id)
    sql_update = f"UPDATE long_exchange_clips SET {', '.join(set_clauses)} WHERE id = ?"
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(sql_update, tuple(params)); rows_affected = cursor.rowcount; conn.commit()
        if rows_affected > 0: logger.info(f"Successfully reset substeps for exchange ID {exchange_db_id}.")
        else: logger.warning(f"Exchange ID {exchange_db_id} not found during substep reset."); return False
        return True
    except sqlite3.Error as e: logger.error(f"Error resetting substeps for exchange ID {exchange_db_id}: {e}", exc_info=True); return False


# --- END OF FILE: database.py ---