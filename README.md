# Flask Video Processing Pipeline 🎬

This Flask web application provides a user interface to download YouTube videos, process them through an analysis pipeline (transcription, speaker diarization), and generate short video clips based on the analysis results.

It combines the power of:
*   **yt-dlp:** For reliable video downloading.
*   **Faster Whisper:** For accurate and efficient audio transcription.
*   **Pyannote.audio:** For speaker diarization (identifying who spoke when).
*   **FFmpeg:** For audio extraction and video clip generation.
*   **Flask:** As the web framework.
*   **SQLite:** For database storage of job information and results.
*   **Waitress:** As the production WSGI server.

The application uses a background worker queue to process videos sequentially, preventing the web server from blocking during potentially long-running analysis tasks.

## ✨ Key Features

*   **Submit YouTube URLs:** Queue single or multiple YouTube videos for processing via a simple web form.
*   **Select Resolution:** Choose the desired video download resolution (e.g., 480p, 720p, best).
*   **Background Processing:** Jobs are added to a queue and processed one by one in the background.
*   **Status Tracking:** Monitor the status (Pending, Queued, Downloading, Processing, Processed, Error) and the current processing step for each job.
*   **Detailed View:** Access a dedicated page for each video showing:
    *   Basic job information (URL, Title, Status).
    *   Combined analysis results: Segments tagged with speaker, text, timing, and potential type.
    *   Raw transcript.
    *   Speaker turn details.
    *   Error messages if processing failed.
*   **Clip Generation:** Identify segments suitable for short clips (based on duration) and generate MP4 clips with a single click from the details page.
*   **Generated Clips List:** View and access previously generated clips for a video.
*   **Error Log:** A dedicated page lists all jobs that encountered errors during processing.
*   **Job Deletion:** Select and delete jobs (including their database records and associated local files) from the main dashboard.

## ⚙️ Prerequisites

Before you begin, ensure you have the following installed:

1.  **Python:** Version 3.8 or higher recommended.
2.  **pip:** Python package installer (usually comes with Python).
3.  **FFmpeg & ffprobe:**
    *   These are essential for audio extraction and video clipping.
    *   Download from the official FFmpeg website: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
    *   Ensure the `ffmpeg` and `ffprobe` executables are either in your system's `PATH` environment variable **OR** configure the full path in the `.env` file (see Configuration below).
4.  **Git:** (Optional, but recommended for cloning).
5.  **Hugging Face Account & Token:**
    *   Speaker diarization using Pyannote requires models hosted on Hugging Face Hub.
    *   Create an account: [https://huggingface.co/join](https://huggingface.co/join)
    *   Generate a User Access Token (read permissions are sufficient): [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
    *   You will need this token for the `.env` configuration.
    *   **IMPORTANT:** You might also need to visit the specific Pyannote model pages (e.g., [pyannote/speaker-diarization](https://huggingface.co/pyannote/speaker-diarization-3.1) - check the version used in `.env`) on Hugging Face while logged in and **accept their terms of service** before the model can be downloaded via the token.

## 🚀 Installation & Setup

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url> your_merged_project
    cd your_merged_project
    ```
    (Or download and extract the source code manually).

2.  **Create a Virtual Environment:** (Recommended)
    ```bash
    python -m venv venv
    # Activate the environment:
    # Windows:
    .\venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Note: This step can take a while, especially downloading PyTorch and related libraries. Ensure you have a stable internet connection.*

4.  **Configure Environment Variables:**
    *   Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    *   **Edit the `.env` file:** Open the newly created `.env` file in a text editor.
    *   **REQUIRED:**
        *   Set `FLASK_SECRET_KEY`: Generate a strong random key (e.g., run `python -c 'import secrets; print(secrets.token_hex(24))'` in your terminal) and paste it here.
        *   Set `HUGGING_FACE_TOKEN`: Paste the Hugging Face User Access Token you generated.
    *   **Optional (Check Paths):**
        *   Verify/set `FFMPEG_PATH` if `ffmpeg`/`ffprobe` are not in your system PATH.
        *   Review default `DATABASE_PATH`, `DOWNLOAD_DIR`, `PROCESSED_CLIPS_DIR` and adjust if necessary (defaults usually work).
        *   Review default ML model settings (`FASTER_WHISPER_MODEL`, `FASTER_WHISPER_COMPUTE_TYPE`, `PYANNOTE_PIPELINE`) if you want to experiment (start with defaults).
    *   **DO NOT commit your actual `.env` file to version control!**

5.  **Optional: NLTK Data (for future sentiment analysis):**
    *   If you plan to implement VADER sentiment analysis (currently not fully wired up but code placeholders exist), download the lexicon:
    ```bash
    python -c "import nltk; nltk.download('vader_lexicon')"
    ```

## ▶️ Running the Application

1.  **Ensure your virtual environment is activated.**
2.  **Make sure FFmpeg is installed and accessible (PATH or `.env`).**
3.  **Run the Flask app using Waitress:**
    ```bash
    python app.py
    ```
4.  **Access the Application:** Open your web browser and navigate to:
    [http://localhost:5001](http://localhost:5001) (or `http://0.0.0.0:5001`)

The application uses the Waitress WSGI server by default for better performance than the Flask development server.

## 📖 Usage Guide

1.  **Submit Videos:** Go to the main page ("Home"). Paste one or more YouTube video URLs (one per line) into the text area. Select the desired download resolution. Click "Add to Queue".
2.  **Monitor Progress:** The table on the main page lists all submitted jobs. Refresh the page manually to see updates to the "Status" and "Current Step" columns. The queue size and number of actively processing jobs are shown above the table.
3.  **View Details:** Click the "Details" button for any video job. This takes you to the video details page where you can find:
    *   Job status and metadata.
    *   The combined analysis segments under "Combined Segments & Clip Candidates". Potential short clips (based on configured duration limits) are highlighted.
    *   Links to view the raw transcript and speaker diarization data.
    *   A list of clips already generated for this video.
    *   Any error messages if the job failed.
4.  **Generate Clips:** On the video details page, locate a "Clip Candidate" segment you're interested in. Click the "Create Clip" button next to it. The application will use FFmpeg to cut the clip from the original downloaded video. The process happens via an AJAX request, and you'll see feedback next to the button (Creating..., Created, Failed). Successfully created clips appear in the "View Generated Clips" section with a link to view/play them.
5.  **Error Log:** Navigate to the "Error Log" page using the top navigation bar to see a filtered list of jobs that encountered errors.
6.  **Delete Jobs:** On the main dashboard ("Home"), check the boxes next to the jobs you want to delete. Click the "Delete Selected" button at the bottom. Confirm the deletion. This removes the database record AND attempts to delete the associated downloaded video file, temporary audio file (if any), the download subdirectory, and any generated clips stored in `processed_clips`.

## 🔧 Configuration (.env Variables)

*   `FLASK_SECRET_KEY`: **Required**. Secret key for Flask session security.
*   `HUGGING_FACE_TOKEN`: **Required**. Your read-access token from Hugging Face for downloading models.
*   `DATABASE_PATH`: (Optional) Path to the SQLite database file. Default: `instance/videos.db`.
*   `DOWNLOAD_DIR`: (Optional) Base directory for downloading original videos and temporary files. Default: `./downloads`.
*   `PROCESSED_CLIPS_DIR`: (Optional) Directory where generated MP4 clips are saved. This directory *must* exist and be writable. Default: `./processed_clips`.
*   `FASTER_WHISPER_MODEL`: (Optional) Whisper model size (`tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v2`, `large-v3`). Default: `base.en`. Larger models are slower and require more RAM/VRAM.
*   `FASTER_WHISPER_COMPUTE_TYPE`: (Optional) `int8`, `float16`, `float32`. Default: `int8` (good balance for CPU). Use `float16` or `int8` on GPU if available.
*   `PYANNOTE_PIPELINE`: (Optional) Pyannote pipeline identifier. Default: `pyannote/speaker-diarization@2.1` (Check Hugging Face for newer compatible versions like `pyannote/speaker-diarization-3.1`).
*   `FFMPEG_PATH`: (Optional) Full path to the `ffmpeg` executable if not in system PATH. Default: `ffmpeg`.

## 🛠️ Technical Details

*   **Backend:** Python, Flask
*   **Frontend:** HTML, Bootstrap 5, Jinja2 Templates, basic JavaScript (inline/AJAX for clipping).
*   **Database:** SQLite accessed via Python's `sqlite3` module. Uses Write-Ahead Logging (WAL) for better concurrency.
*   **Video Download:** `yt-dlp` library.
*   **Audio Processing:** `ffmpeg` (via `subprocess`) for extraction and clipping.
*   **Transcription:** `faster-whisper` library (optimised CTranslate2 implementation).
*   **Diarization:** `pyannote.audio` library (requires Hugging Face token).
*   **Background Tasks:** Standard Python `threading` and `queue.Queue` for sequential job processing.
*   **Serving:** `Waitress` WSGI server.

## ⚡ Troubleshooting Common Issues

*   **Dependency Conflicts:** The ML stack (`torch`, `pyannote`, `faster-whisper`) can be sensitive. If you encounter installation errors:
    *   Ensure you are using a clean virtual environment.
    *   Check the specific version compatibility requirements for `pyannote.audio` and the chosen `torch` version. The `requirements.txt` tries to pin working versions, but updates might break things.
    *   Consider installing `torch` separately first based on your system/CUDA version using instructions from [pytorch.org](https://pytorch.org/).
*   **Pyannote Errors / Hugging Face Token:**
    *   `401 Client Error` or `Repository Not Found`: Ensure your `HUGGING_FACE_TOKEN` in `.env` is correct. Crucially, make sure you have accepted the Terms of Service on the Hugging Face website for the *specific Pyannote model* you are trying to use (e.g., `pyannote/speaker-diarization-3.1`).
*   **FFmpeg Not Found:** Ensure FFmpeg and ffprobe are installed correctly and either added to your system's PATH or the full path is specified in `FFMPEG_PATH` in your `.env` file. Run `ffmpeg -version` in your terminal to test.
*   **CUDA Out Of Memory (OOM):** If you have a GPU and encounter OOM errors during transcription or diarization:
    *   Try a smaller `FASTER_WHISPER_MODEL` (e.g., `base.en`, `small.en`).
    *   Try a different `FASTER_WHISPER_COMPUTE_TYPE` like `int8`.
    *   Close other applications using GPU memory.
    *   Ensure your GPU drivers and CUDA toolkit are up to date and compatible with the installed PyTorch version.
*   **Permission Denied Errors:** The application needs write permissions for the `DOWNLOAD_DIR`, `PROCESSED_CLIPS_DIR`, and the `instance` directory (for the database). Ensure the user running the application has the necessary permissions.
*   **File Not Found (After Download):** If `yt-dlp` finishes but the app reports the file missing, check console logs for specific download errors or file renaming issues. Ensure the `DOWNLOAD_DIR` is correctly configured.

## 🔮 Future Enhancements (TODO)

*   **More Robust Q&A/Analysis:** Implement actual NLP techniques (e.g., using spaCy, NLTK, or transformers) for better question/answer detection, topic modeling, or sentiment analysis.
*   **Scalable Worker:** Replace the single-threaded worker with a more robust task queue system like Celery and Redis/RabbitMQ for parallel processing and better scalability.
*   **Real-time UI Updates:** Implement WebSockets or Server-Sent Events (SSE) to push status updates to the frontend without requiring manual refreshes.
*   **Retry Failed Jobs:** Add a button to easily re-queue jobs that failed due to transient errors.
*   **Configuration UI:** Allow changing model settings or paths via the web interface (carefully, requires security considerations).
*   **Authentication:** Add user login/authentication if the app needs to be secured.
*   **Subtitle Generation/Embedding:** Add options to generate subtitle files (e.g., VTT, SRT) and optionally burn them into clips.
*   **More Advanced Clipping:** Allow custom time ranges for clipping, not just pre-defined segments.

## License

(Specify your license here, e.g., MIT License)