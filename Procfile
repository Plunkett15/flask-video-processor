# --- Start of File: Procfile ---
# Use Waitress for deployment (works well on Heroku, Docker etc.)
# The PORT environment variable is often set by hosting platforms.
web: waitress-serve --host=0.0.0.0 --port=${PORT:-5001} app:app
# --- END OF FILE: Procfile ---