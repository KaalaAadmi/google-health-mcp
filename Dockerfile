FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY google_health_mcp.py .

# Cloud Run injects PORT (8080); the server reads it.
EXPOSE 8080
CMD ["python", "google_health_mcp.py"]
