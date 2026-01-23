FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY email_service.py .
COPY templates.py .

# Cloud Run sets PORT environment variable
ENV PORT=8080

# Run with uvicorn
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT
