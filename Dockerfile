FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /fetch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cloud-fetch.py .

CMD ["gunicorn", "-b", "0.0.0.0:8080", "cloud-fetch:fetch"]
