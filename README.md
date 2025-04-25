# Flask Video Processing Pipeline 🎬 (Granular Workflow)

This Flask web application provides a user interface to download YouTube videos and process them through a multi-stage analysis pipeline (audio extraction, transcription, speaker diarization, exchange identification) using Celery for background task management. Users can then trigger further analysis on identified exchanges and generate short video clips.

It combines the power of:
*   **yt-dlp:** For reliable video downloading.
*   **Faster Whisper:** For accurate and efficient audio transcription.
*   **Pyannote.audio:** For speaker diarization (identifying who spoke when).
*   **FFmpeg:** For audio extraction and video clip generation.
*   **Flask:** As the web framework.
*   **Celery & Redis:** For robust background task queuing and execution.
*   **SQLite:** For database storage of job information and results.
*   **Waitress:** As the production WSGI server.

## ✨ Key Features (Granular Workflow)

*   **Submit YouTube URLs:** Queue single or multiple YouTube videos for processing via a simple web form.
*   **Select Resolution:** Choose the desired video download resolution.
*   **Background Processing (Celery):** Jobs are added to a Redis queue and processed by Celery workers.
*   **Granular Pipeline Control:**
    *   Trigger individual processing steps (Download, Audio Extract, Transcribe, Diarize, Identify Exchanges) for each video.
    *   Trigger sub-steps (Process Diarization, Define Clips, Cut Clips) for each identified exchange (Auto or Manual).
*   **Status Tracking:** Monitor the status of each granular step via the UI, updated in near real-time using Server-Sent Events (SSE).
*   **Detailed View:** Access a dedicated page for each video showing:
    *   Overall job status and metadata.
    *   Detailed status for each processing step.
    *   A control panel to trigger/re-run steps.
    *   A table to manage identified exchanges (Auto-detected via speaker changes/questions, or Manually marked).
    *   Controls to process individual exchanges.
    *   Full transcript display with speaker information (once aligned).
    *   List of generated short clips.
    *   Error messages if processing failed at any step.
*   **Exchange Identification:** Automatically identifies potential conversation exchanges based on speaker changes and simple question detection rules.
*   **Manual Exchange Marking:** Manually define start/end times for exchanges directly on the details page.
*   **Clip Generation:** Generate short MP4 clips corresponding to identified speaker segments within processed exchanges.
*   **Job Deletion:** Select and delete jobs (including their database records and associated local files).
*   **Error Log:** A dedicated page lists all jobs that encountered errors during processing.

## ⚙️ Prerequisites

Before you begin, ensure you have the following installed:

1.  **Python:** Version 3.9 or higher recommended.
2.  **pip:** Python package installer.
3.  **Redis:**
    *   Required for Celery message broker and result backend.
    *   Install Redis locally or use a cloud service. Ensure it's running before starting Celery workers.
    *   Download/Instructions: [https://redis.io/docs/getting-started/installation/](https://redis.io/docs/getting-started/installation/)
4.  **FFmpeg & ffprobe:**
    *   Essential for audio extraction and video clipping.
    *   Download: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
    *   Ensure `ffmpeg` and `ffprobe` executables are in your system's `PATH` or configure the full path in `.env`.
5.  **Git:** (Optional, for cloning).
6.  **Hugging Face Account & Token:**
    *   Required for Pyannote speaker diarization models.
    *   Create account: [https://huggingface.co/join](https://huggingface.co/join)
    *   Generate Token (read access): [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
    *   You **must** accept the terms of service for the specific Pyannote models used (check `.env` or `config.py` defaults, e.g., `pyannote/speaker-diarization-3.1`) on the Hugging Face website while logged in.

## 🚀 Installation & Setup

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url> granular_video_processor
    cd granular_video_processor
    ```

2.  **Create a Virtual Environment:** (Recommended)
    ```bash
    python -m venv venv
    # Activate:
    # Windows: .\venv\Scripts\activate
    # macOS/Linux: source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(This can take time, especially for PyTorch and related libraries).*

4.  **Configure Environment Variables:**
    *   Copy `.env.example` to `.env`:
        ```bash
        cp .env.example .env
        ```
    *   **Edit `.env`:**
        *   **REQUIRED:**
            *   `FLASK_SECRET_KEY`: Generate a strong random key.
            *   `HUGGING_FACE_TOKEN`: Paste your Hugging Face token.
        *   **Verify/Optional:**
            *   `CELERY_BROKER_URL`: Ensure this points to your running Redis instance (e.g., `redis://localhost:6379/0`).
            *   `CELERY_RESULT_BACKEND`: Ensure this points to your Redis instance (use a different DB number, e.g., `redis://localhost:6379/1`).
            *   `FFMPEG_PATH`: Set full path if not in system PATH.
            *   Review ML model settings (`FASTER_WHISPER_MODEL`, `PYANNOTE_PIPELINE`, etc.). Start with defaults.
            *   Review directory paths (`DATABASE_PATH`, `DOWNLOAD_DIR`, `PROCESSED_CLIPS_DIR`).
    *   **DO NOT commit your actual `.env` file!**

## ▶️ Running the Application

You need to run **two** main components: the **Flask Web Application** and the **Celery Worker**. Ensure Redis is running first.

**1. Start Redis:** (If running locally)
   *   Open a terminal and start the Redis server (command depends on your installation, e.g., `redis-server`).

**2. Start the Celery Worker:**
   *   Open a **new terminal**.
   *   Activate your virtual environment (`source venv/bin/activate` or `.\venv\Scripts\activate`).
   *   Navigate to the project directory (`cd granular_video_processor`).
   *   Run the Celery worker command:

     ```bash
     celery -A celery_app.celery_app worker --loglevel=info -P solo
     ```

     *   `-A celery_app.celery_app`: Points to your Celery application instance.
     *   `worker`: Specifies that this process should run as a worker.
     *   `--loglevel=info`: Sets the logging level (use `debug` for more detail).
     *   `-P solo`: **Crucial for Development/Testing on Windows or without complex setup.** This runs the worker using a simple inline pool (single-threaded within the worker process). For production or parallel processing on Linux/macOS, you might use `-P gevent`, `-P prefork` (default), or `-P eventlet` after installing the corresponding libraries (`pip install gevent eventlet`). `-P solo` is the simplest way to get started.

   *   Keep this terminal open. You should see Celery start up and list the discovered tasks (from `tasks.video_tasks` and `tasks.exchange_tasks`).

**3. Start the Flask Web Application:**
   *   Open **another new terminal**.
   *   Activate your virtual environment.
   *   Navigate to the project directory.
   *   Run the Flask app using Waitress:

     ```bash
     python app.py
     ```

**4. Access the Application:**
   *   Open your web browser and go to: [http://localhost:5001](http://localhost:5001) (or the host/port configured).

## 📖 Usage Guide

1.  **Submit Videos:** Go to the main page. Paste YouTube URL(s), select resolution, click "Add & Start Download". This queues the *download task only*.
2.  **Monitor Progress:** The main table shows overall status (calculated from granular steps). Status updates automatically via SSE.
3.  **Video Details Page:** Click "Details" for a video.
    *   **Pipeline Control Panel:** Shows the status of each Phase 1 step (Download, Audio, Transcript, Diarize, Exchange ID). Use the "Run"/"Retry"/"Re-run" buttons to trigger these steps. Buttons are enabled/disabled based on prerequisites.
    *   **Manage Exchanges:**
        *   Manually mark exchanges using the Start/End time inputs (use the transcript section below to click segments for easy time selection).
        *   View automatically identified exchanges (labeled `spkchg_N`) and manually marked ones (`man_...`).
        *   Use the buttons (<i class="bi bi-people"></i>, <i class="bi bi-list-task"></i>, <i class="bi bi-scissors"></i>) next to each exchange to trigger Phase 2 substeps: Process Diarization, Define Clips, Cut Clips. These buttons also respect prerequisites.
    *   **View Generated Clips:** See clips created by the "Cut Clips" substep.
    *   **Full Transcript:** View the transcript. Click segments to populate the Manual Exchange start/end times.
4.  **Error Log:** Check for jobs with errors.
5.  **Delete Jobs:** Use checkboxes on the main page.

## 🔧 Configuration (.env Variables)

*   `FLASK_SECRET_KEY`: **Required**.
*   `HUGGING_FACE_TOKEN`: **Required**.
*   `CELERY_BROKER_URL`: **Required**. Connection URL for Redis (or other broker).
*   `CELERY_RESULT_BACKEND`: **Required**. Connection URL for Redis (or other backend).
*   `DATABASE_PATH`: Path to SQLite DB file.
*   `DOWNLOAD_DIR`: Base directory for downloads.
*   `PROCESSED_CLIPS_DIR`: Directory for generated clips.
*   `FASTER_WHISPER_MODEL`: Whisper model size (`tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v3`, etc.).
*   `FASTER_WHISPER_COMPUTE_TYPE`: `int8`, `float16`, `float32`. Default: `int8` on CPU, `float16` on CUDA.
*   `PYANNOTE_PIPELINE`: Pyannote pipeline ID (e.g., `pyannote/speaker-diarization-3.1`).
*   `FFMPEG_PATH`: Full path to `ffmpeg` if needed.
*   `LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
*   `CLIP_MIN_DURATION_SECONDS` / `CLIP_MAX_DURATION_SECONDS`: (Optional) Used by clip definition logic. Defaults exist if not set.

## 🛠️ Technical Details

*   **Backend:** Python, Flask, Celery
*   **Frontend:** HTML, Bootstrap 5, Jinja2, JavaScript (SSE, AJAX).
*   **Database:** SQLite.
*   **Task Queue:** Celery with Redis Broker/Backend.
*   **Video/Audio:** `yt-dlp`, `ffmpeg`.
*   **Analysis:** `faster-whisper`, `pyannote.audio`.
*   **Serving:** `Waitress`.

## ⚡ Troubleshooting Common Issues

*   **`sqlite3.OperationalError: no such table: ...`:** Delete `instance/videos.db` and restart the Flask app *first* to allow `init_db` to run successfully *before* starting the Celery worker.
*   **Celery Worker Not Starting/Connecting:** Ensure Redis server is running and accessible. Check `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` in `.env`. Check Celery worker logs for connection errors.
*   **Tasks Stuck in 'Queued'/'Running':** Check Celery worker logs for errors. Ensure the worker is running and connected. Check resource usage (CPU/RAM/GPU). Increase task timeouts in FFmpeg calls (`media_utils.py`) or Celery task definitions if needed for very long operations.
*   **Pyannote Errors / Hugging Face Token:** Ensure token is correct in `.env` AND you've accepted model terms on HF website.
*   **FFmpeg Not Found:** Check PATH or `FFMPEG_PATH` in `.env`.
*   **CUDA OOM:** Try smaller models (`FASTER_WHISPER_MODEL`), different compute types (`int8`), or run on CPU (`DEVICE=cpu` in `.env`, though not directly configurable this way - relies on `torch.cuda.is_available()`).
*   **Dependency Conflicts:** Use a clean virtual environment. Check library compatibility (PyTorch, Pyannote).

## 🔮 Future Enhancements (TODO)

*   **Improve Exchange Detection:** Use more advanced NLP for question detection, refine speaker change logic, potentially integrate LLMs (like Gemini) selectively.
*   **Parallel Workers:** Configure Celery with pools like `gevent` or `prefork` for parallel task execution (requires careful resource management).
*   **More Robust UI Feedback:** Better handling of SSE disconnects, visual progress indicators for long tasks.
*   **Configuration UI:** Allow managing some settings via the web UI.
*   **Authentication:** Secure the application.
*   **Subtitle Generation:** Create VTT/SRT files.

## License

(Specify your license here, e.g., MIT License)