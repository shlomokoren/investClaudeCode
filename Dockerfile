FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    DEBUG=false

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# config.json is kept only as a seed file for init_db.py; the running app reads
# its configuration from Postgres via DATABASE_URL.
COPY app.py auth.py symbols.py db.py init_db.py config.json ./
COPY blueprints ./blueprints
COPY templates ./templates
COPY static ./static

EXPOSE 5000

CMD ["python", "app.py"]
