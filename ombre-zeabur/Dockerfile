FROM python:3.12-slim

ARG OMBRE_COMMIT=8bb06dda6c5b6df5ee27a081f92ca6c3fba59ec6

RUN apt-get update \
    && apt-get install -y --no-install-recommends git nginx gettext-base curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone https://github.com/Yinglianchun/Ombre-Brain.git /app/ombre \
    && cd /app/ombre \
    && git checkout "$OMBRE_COMMIT" \
    && pip install --no-cache-dir -r requirements.txt

COPY ombre-zeabur/generate_config.py /app/generate_config.py
COPY ombre-zeabur/nginx.conf.template /app/nginx.conf.template
COPY ombre-zeabur/start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PORT=8080 \
    OMBRE_BUCKETS_DIR=/app/data/buckets \
    OMBRE_STATE_DIR=/app/data/state

VOLUME ["/app/data"]
EXPOSE 8080

CMD ["/app/start.sh"]
