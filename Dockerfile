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
CMD gunicorn --bind 0.0.0.0:${PORT:-5001} --workers 2 --timeout 120 app:app
