FROM python:3.11-slim

WORKDIR /app

COPY relay/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY relay/main.py ./main.py
COPY relay/admin ./admin
COPY relay/public ./public
COPY src/localflight ./localflight

EXPOSE 8080

CMD ["python", "main.py"]
