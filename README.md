# CC63D — Lab 2: docker compose, PostgreSQL y Flyway

Segundo laboratorio del curso **CC63D — Arquitecturas de Servicios, DevOps, SRE y Cloud** (FCFM, Universidad de Chile, 2026).

Partimos de la plataforma de gestión de incidentes del [Lab 1](https://github.com/lnds/cc63d-lab-1), pero **ya evolucionada** a una arquitectura más cercana a producción:

- **PostgreSQL** como base de datos (en vez de SQLite + archivo)
- **Flyway** para gestionar las migraciones del schema
- **Nginx** sirviendo el frontend, separado del backend
- La API Flask migrada a `psycopg2`, configurada por environment (`DATABASE_URL`)

## 🎯 El ejercicio

**Todo el código ya está hecho.** El [`compose.yaml`](compose.yaml) viene con el servicio `db` **resuelto como ejemplo**; tu tarea es **completar los TODO** de `flyway`, `api` y `frontend` para que un solo comando levante toda la plataforma.

Los 4 servicios son:

| Servicio   | Imagen / build       | Rol |
|------------|----------------------|-----|
| `db`       | `postgres:16-alpine` | Base de datos (con healthcheck + volumen persistente) |
| `flyway`   | `flyway/flyway`      | Aplica las migraciones de `db/migrations/` |
| `api`      | `build: .`           | Backend Flask (espera a que Flyway termine) |
| `frontend` | `nginx:alpine`       | Sirve `static/` y proxea `/api/` al backend |

### Criterios de aceptación

1. `docker compose up --build` levanta todo sin intervención manual.
2. El orden de arranque es correcto: `db` (healthy) → `flyway` (migrate) → `api` → `frontend`.
3. Abrir `http://localhost:3000` muestra la UI y permite crear servicios, on-call e incidentes.
4. `docker compose down` y un nuevo `up` **conservan los datos** (volumen).
5. `docker compose down -v` los elimina.

## 📝 Entrega y evaluación

Esta es una **tarea con nota**. Entregas **dos** cosas:

1. Tu **`compose.yaml`** funcionando (cumpliendo los criterios de aceptación de arriba).
2. Una **justificación breve** (≈ media plana) que responda:

   - ¿Por qué `flyway` usa `condition: service_completed_successfully` y no `service_healthy`?
   - ¿Por qué la api se conecta a `db:5432` y **no** a `localhost:5432`?
   - ¿Qué pasa si **quitas el `healthcheck`** de `db`? ¿Por qué falla la api al arrancar?
   - ¿Qué sobrevive a `docker compose down`? ¿Y a `docker compose down -v`?

> La nota pondera **que entiendas tus decisiones**, no solo que el archivo levante.
> Un `compose.yaml` que funciona "de casualidad" no obtiene nota completa.

### Probar con datos de ejemplo

```bash
docker compose up --build -d
bash seed.sh http://localhost:3000/api   # carga servicios, on-call e incidentes
# abre http://localhost:3000
```

## 📁 Estructura del repo

```
.
├── app.py                  # API Flask migrada a PostgreSQL (psycopg2)
├── requirements.txt        # flask, psycopg2-binary, gunicorn
├── Dockerfile              # imagen de la API (gunicorn)
├── nginx.conf              # sirve el frontend + proxy /api/ -> api:8080
├── compose.yaml            # ← TU TAREA: db resuelto, completa los TODO
├── seed.sh                 # datos de ejemplo vía curl
├── db/
│   └── migrations/         # migraciones versionadas de Flyway
│       ├── V1__create_services.sql
│       ├── V2__create_oncall.sql
│       ├── V3__create_incidents.sql
│       ├── V4__create_incident_timeline.sql
│       └── V5__create_postmortems.sql
└── static/                 # frontend (lo sirve Nginx)
    ├── index.html
    ├── app.js
    └── style.css
```

## 📚 Recursos y punto de partida

**De dónde salió el esqueleto:** `docker init` genera `Dockerfile` + `compose.yaml` + `.dockerignore` a partir del proyecto. El `compose.yaml` que completas ya está en el repo, con el servicio `db` resuelto como ejemplo.

- [Compose file reference](https://docs.docker.com/reference/compose-file/)
- [`docker init`](https://docs.docker.com/reference/cli/docker/init/)
- Imágenes en Docker Hub: [`postgres`](https://hub.docker.com/_/postgres), [`flyway/flyway`](https://hub.docker.com/r/flyway/flyway), [`nginx`](https://hub.docker.com/_/nginx) — para ver qué montar y dónde
- El [`nginx.conf`](nginx.conf) ya viene en este repo: míralo para configurar el servicio `frontend`

## 🤔 Para discutir en clase

- ¿Por qué Flyway es un **servicio separado** y no un paso en el `Dockerfile` de la api?
- ¿Qué pasa si modificas una migración **ya aplicada** y haces `docker compose up`?
- ¿Por qué la api usa `db:5432` y no `localhost:5432`?
- ¿Por qué el frontend está separado del backend? ¿Qué ganas con eso?
- ¿Qué factores del **12-Factor** cumple (o viola) este setup?

> En la **Clase 5** llevamos esto a un pipeline CI/CD real.
