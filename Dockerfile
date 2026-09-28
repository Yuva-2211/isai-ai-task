# Multi-stage / lightweight production container
FROM python:3.10-slim

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (graphviz is required for rendering DAGs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000
EXPOSE 8501

# Make start script executable
RUN chmod +x start.sh

# Default command starts both backend and frontend services
CMD ["./start.sh"]
