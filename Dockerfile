FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRIALTRUST_RUNTIME=/mnt/workspace/trialtrust/web \
    TRIALTRUST_ENABLE_LIVE=0
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 1000 --create-home trialtrust \
    && mkdir -p /mnt/workspace/trialtrust \
    && chown -R trialtrust:trialtrust /mnt/workspace
COPY trialtrust ./trialtrust
USER trialtrust
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health', timeout=3)"
CMD ["python", "-m", "trialtrust.managed"]
