# SalesPilot Dockerfile — AWS Lightsail / ECS compatible
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create runtime directories
RUN mkdir -p runtime logs

# Expose the FastAPI port
EXPOSE 8000

# Environment defaults (override at deploy time)
ENV SALESPILOT_HOST=0.0.0.0
ENV SALESPILOT_PORT=8000
ENV SALESPILOT_LLM=stub

# Run the API server with demo data seeded
CMD ["python", "run.py", "--serve", "--seed", "--host", "0.0.0.0", "--port", "8000"]
