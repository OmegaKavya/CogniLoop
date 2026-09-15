FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5001

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Run the application with a production WSGI server.
# Render (and most PaaS hosts) inject $PORT; default to 5001 for local `docker run`.
# Single worker: this app can load a PyTorch-based embedding model (RAG_ENABLED=true),
# and each worker would load its own copy -- 1 worker avoids doubling memory use on
# memory-constrained hosts. Override with WEB_CONCURRENCY on hosts with more headroom.
CMD gunicorn --bind 0.0.0.0:${PORT:-5001} --workers ${WEB_CONCURRENCY:-1} --timeout 120 app:app
