FROM python:3.13-slim

RUN pip install --no-cache-dir mcp==2.3.0

WORKDIR /srv
COPY server.py /srv/server.py

EXPOSE 8000 8001
CMD ["python", "/srv/server.py"]
