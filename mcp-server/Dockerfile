FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir "fastmcp>=3,<4" "trino>=0.330"
COPY server.py .

EXPOSE 8000
CMD ["python", "server.py"]
