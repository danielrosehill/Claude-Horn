FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY horn_server.py .
ENV CLAUDE_HORN_CONFIG=/config/config.json PYTHONUNBUFFERED=1
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/health')"
CMD ["python", "horn_server.py"]
