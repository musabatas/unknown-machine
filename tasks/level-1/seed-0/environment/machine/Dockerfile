FROM python:3.13-slim

RUN pip install --no-cache-dir mcp==2.3.0

WORKDIR /srv
COPY unknown_machine /srv/unknown_machine

EXPOSE 8000 8001
CMD ["python", "-m", "unknown_machine.server.app"]
