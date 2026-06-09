# Imagen base liviana con Python
FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias primero (mejor caché de capas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la API (el frontend lo sirve Nginx, no la API)
COPY app.py .

EXPOSE 8080

# En producción no usamos el servidor de desarrollo de Flask.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]
