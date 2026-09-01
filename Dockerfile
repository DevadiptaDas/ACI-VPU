# ACI - Artificial Cognition Infrastructure: container for online/hosted testing.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e .
# Bind to all interfaces so the host can reach it; PORT is injected by most hosts.
ENV ACI_HOST=0.0.0.0 PYTHONHASHSEED=0
EXPOSE 7077
# Set ACI_API_KEY in your host's env to require auth.
CMD ["aci", "serve"]
