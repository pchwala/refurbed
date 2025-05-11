FROM python:3.12-slim

WORKDIR /app

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy JSON files needed for order creation and editing
COPY create_body.json .
COPY edit_body.json .

# Copy all Python files
COPY refurbed.py .
COPY idosell.py .
COPY main.py .
COPY cloud_logging.py .

# Copy templates directory for Flask application
COPY templates/ ./templates/

# Expose the port the app will run on
EXPOSE 8080

# Command to run the application
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]