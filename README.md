# Log Analyzer MVP

MVP web para cargar y analizar logs de aplicaciones Python Flask o Django.

Entrega un panel simple con:

- IPs que más acceden
- rutas más visitadas
- métodos HTTP
- códigos HTTP
- errores más repetidos
- actividad por hora
- matriz IP vs status
- matriz ruta vs status
- eventos recientes

## 1. Casos de uso cubiertos

Este MVP está pensado para un escenario realista de operación:

- logs de acceso tipo `nginx`, `gunicorn` o formato common/combined
- logs de desarrollo de Django
- líneas de error con `ERROR`, `CRITICAL`, `Exception` o `Traceback`

No intenta reemplazar a ELK, Loki o Datadog. Es una base rápida para un visor interno y luego crecer.

## 2. Arquitectura

```text
[ Navegador ]
      |
      v
[ Flask Web UI ]
      |
      +--> carga archivos .log/.txt
      +--> parser streaming línea a línea
      +--> normalización de rutas y errores
      +--> persistencia JSON del análisis
      |
      v
[ Dashboard HTML ]
```

## 3. Estructura

```text
log_analyzer_mvp/
├── app.py
├── parser.py
├── requirements.txt
├── Dockerfile
├── sample_flask_django.log
├── uploads/
├── data/
├── static/
│   └── styles.css
└── templates/
    ├── base.html
    ├── index.html
    ├── report.html
    └── 404.html
```

## 4. Ejecución local en Linux

### Opción A: Python directo

```bash
cd log_analyzer_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abrir:

```text
http://127.0.0.1:8000
```

### Opción B: Docker

```bash
docker build -t log-analyzer-mvp .
docker run --rm -p 8000:8000 log-analyzer-mvp
```

## 5. Prueba rápida

Sube el archivo:

```text
sample_flask_django.log
```

Deberías ver inmediatamente:

- `/dashboard` entre las rutas más visitadas
- `192.168.1.10` como IP destacada
- errores como `Internal Server Error` y `invalid payload`
- mezcla de `200`, `404` y `500`

## 6. Decisiones técnicas del MVP

### Qué hace bien

- procesa archivos línea a línea, no carga todo en memoria de golpe
- normaliza rutas como `/api/orders/123` → `/api/orders/<num>`
- normaliza errores para agrupar variantes parecidas
- guarda el análisis en JSON para revisar reportes después
- expone un endpoint API `/api/report/<id>`

### Limitaciones actuales

- no hay autenticación
- no hay base de datos
- no hay parsing avanzado de multiline stacktraces complejos con contexto completo
- no hay charts JS todavía, solo tablas operativas
- no detecta automáticamente todos los formatos posibles de logs

## 7. Próxima evolución recomendada

### Fase 2

- filtros por rango de tiempo
- búsqueda por IP, ruta o texto de error
- gráficos con Chart.js o ECharts
- upload masivo de varios archivos comprimidos
- score de anomalías por IP o ruta

### Fase 3

- persistencia en PostgreSQL
- jobs asíncronos con Celery/RQ
- soporte para archivos grandes y procesamiento en background
- login y RBAC
- parser por tipo de fuente: gunicorn, nginx, django, flask, supervisor, systemd
- correlación entre access logs y app errors

### Fase 4

- integración con Loki / Elasticsearch / S3 / MinIO
- detección automática de picos por ventana de tiempo
- alertas
- exportación CSV y PDF

## 8. Hardening sugerido para producción

- poner Nginx al frente
- limitar tamaño y tipo de archivos
- aislar uploads en volumen dedicado
- limpiar reportes antiguos con cron
- agregar autenticación simple al menos con Basic Auth o login interno
- registrar auditoría de cargas y consultas

## 9. Endpoint de salud

```text
GET /health
```

Respuesta:

```json
{"status":"ok"}
```

## 10. Idea de siguiente paso natural

El paso más útil después de este MVP es agregar:

1. filtros por fecha
2. gráficos
3. clasificación por severidad
4. parser separado por formato
5. soporte de lectura directa desde archivos de aplicaciones en un directorio monitoreado

