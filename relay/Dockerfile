FROM python:3.11-slim

ARG LOCALFLIGHT_COMMIT_SHA=unknown
ENV LOCALFLIGHT_COMMIT_SHA=${LOCALFLIGHT_COMMIT_SHA}

WORKDIR /app

COPY relay/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY relay/main.py ./main.py
COPY relay/ground_cache.py ./relay/ground_cache.py
COPY relay/schedule_service.py ./relay/schedule_service.py
COPY relay/schedule_transport.py ./relay/schedule_transport.py
COPY relay/access ./relay/access
COPY relay/admin ./admin
COPY relay/public ./public
COPY src/localflight ./localflight

EXPOSE 8080

CMD ["python", "main.py"]
