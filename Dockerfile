FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m appuser && \
    chown -R appuser:appuser /app/uploads /app/data

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBUG=false

EXPOSE 8000

USER appuser

CMD ["python", "app.py"]