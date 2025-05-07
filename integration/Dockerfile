FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy JSON files needed for order creation and editing
COPY create_body.json .
COPY edit_body.json .
COPY cloud-push.py .
# Copy templates directory for Flask application
COPY templates/ ./templates/

CMD ["gunicorn", "-b", "0.0.0.0:8080", "cloud-push:app"]