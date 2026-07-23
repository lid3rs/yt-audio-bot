FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# deno: JS runtime yt-dlp needs for YouTube web-client signature challenges
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      arm64) DARCH=aarch64 ;; \
      *) DARCH=x86_64 ;; \
    esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${DARCH}-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

ENV DATA_DIR=/data
VOLUME ["/data"]

# yt-dlp ages fast (YouTube changes break old versions), so refresh it and the
# PO-token plugin on every container start. Restarting the container is the
# "update" button; the plugin must track the provider container, which
# Watchtower keeps on :latest.
CMD ["sh", "-c", "pip install --no-cache-dir --quiet --upgrade 'yt-dlp[default]' bgutil-ytdlp-pot-provider; exec python bot.py"]
