# Videoflix Backend

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.1.3-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Django REST Framework](https://img.shields.io/badge/Django%20REST%20Framework-3.18.3-red)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Queue%20and%20cache-Redis-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![FFmpeg](https://img.shields.io/badge/Video-FFmpeg-007808)](https://ffmpeg.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Videoflix Backend provides account registration and authentication, a video catalog, and authenticated HLS playback. Videos are managed through Django Admin and processed asynchronously with FFmpeg, Django RQ, and Redis. The associated Vanilla JavaScript frontend is maintained separately in the [Developer Akademie Videoflix frontend repository](https://github.com/Developer-Akademie-Backendkurs/project.Videoflix).

> **Implementation status:** This README describes behavior found in the current source code. The API specification and project checklists include requirements beyond the implementation; only routes and behavior listed below are confirmed as implemented.

## Table of contents

- [Features](#features)
- [Getting started](#getting-started)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Frontend setup and integration](#frontend-setup-and-integration)
- [Implemented features](#implemented-features)
- [Authentication](#authentication)
- [API reference](#api-reference)
- [Video processing and storage](#video-processing-and-storage)
- [Testing](#testing)
- [Security and operational notes](#security-and-operational-notes)
- [License](#license)

## Features

- Register accounts, activate them by email OTP, log in, refresh tokens, log out, and reset passwords.
- Authenticate browser and API requests with HttpOnly JWT cookies.
- List ready videos and play authenticated HLS playlists and segments.
- Manage uploads and processing status through Django Admin.
- Convert source videos to 480p, 720p, and 1080p HLS in a background RQ worker; create a thumbnail when one was not uploaded.
- Protect direct media-file URLs and clean up replaced or deleted, unreferenced media assets.

## Getting started

The following steps set up and run the backend locally on your machine, with PostgreSQL and Redis provided by Docker Compose.

### Prerequisites

- Git.
- Python 3.12 and `pip`.
- FFmpeg installed and available on your `PATH` for local video processing. The Docker backend image installs FFmpeg for the container workflow.
- Docker Engine with Docker Compose, used here to run PostgreSQL and Redis.

### 1. Clone the repository

Clone the backend repository (the configured remote uses GitHub SSH; configure an SSH key with GitHub first):

```sh
git clone git@github.com:gloedige/Videoflix-Backend.git
cd Videoflix-Backend
```

### 2. Create a virtual environment and install Python dependencies

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**macOS/Linux:**

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

### 3. Install FFmpeg

Install FFmpeg using the instructions for your operating system from [ffmpeg.org](https://ffmpeg.org/download.html), and confirm the `ffmpeg` executable is available in the terminal `PATH`. If using the all-container option below, the backend image already installs FFmpeg.

### 4. Configure environment variables

Copy `.env.template` to `.env`, then replace placeholders with local database credentials and a private Django secret. Never commit `.env` or real credentials.

**Windows PowerShell:**

```powershell
Copy-Item .env.template .env
```

**macOS/Linux:**

```sh
cp .env.template .env
```

For running Django on the host while PostgreSQL and Redis run in Compose, set `DB_HOST=localhost`, `REDIS_HOST=localhost`, and `REDIS_LOCATION=redis://localhost:6379/1` in `.env`. Keep the DB name, user, and password consistent with the Compose PostgreSQL service. The template's email settings are placeholders; the current email backend prints messages to the console rather than sending SMTP mail.

### 5. Start PostgreSQL and Redis

From the repository root:

```sh
docker compose up -d db redis
```

### 6. Migrate the database and create an admin user

In the activated virtual environment:

```sh
python manage.py migrate
python manage.py createsuperuser
```

### 7. Start the backend and its background worker

Run Django in one terminal:

```sh
python manage.py runserver
```

Run the RQ worker in a second terminal with the same virtual environment activated:

```sh
python manage.py rqworker default
```

The API is available at `http://127.0.0.1:8000/`, and Django Admin at `http://127.0.0.1:8000/admin/`.

### Alternative: run the complete stack in Docker

If you prefer not to install Python dependencies or FFmpeg on the host, configure `.env` with the Compose service hostnames (`DB_HOST=db`, `REDIS_HOST=redis`, `REDIS_LOCATION=redis://redis:6379/1`) and run:

```sh
docker compose up --build -d
docker compose logs -f web
```

If startup fails with `exec ./backend.entrypoint.sh: no such file or directory`, the entrypoint may have Windows-style CRLF line endings. In VS Code, open `backend.entrypoint.sh`, click `CRLF` in the status bar, select `LF`, and save the file. Then run `docker compose up --build -d` again. This change is only necessary if you encounter this error and the file uses CRLF line endings.

The entrypoint waits for PostgreSQL, collects static files, runs migrations, creates the configured superuser if absent, starts the `default` RQ worker, then starts Gunicorn. The backend is at `http://localhost:8000/`; Admin is at `http://localhost:8000/admin/`. The source tree is bind-mounted into the backend container. Rebuild after changing dependencies or image-installed components. `docker compose down` stops containers but preserves named volumes; `docker compose down -v` also deletes their data.

## Tech stack

| Area | Technology |
| --- | --- |
| Language and web framework | Python 3.12, Django 6.1.3 |
| API | Django REST Framework 3.18.3 |
| Authentication | SimpleJWT 5.5.1 with custom cookie JWT authentication |
| Database | PostgreSQL (`psycopg2-binary` 2.9.13) |
| Cache and background jobs | Redis 8.1.0, django-redis 7.0.0, django-rq 4.2.0, RQ 3.0.0 |
| Video processing | FFmpeg, installed in the backend Docker image |
| Static assets | WhiteNoise 6.12.0 |
| Tests | Django test runner |

Dependency versions are taken from `requirements.txt`; the Python image version is taken from `backend.Dockerfile`.

## Project structure

```text
Videoflix-Backend/
├── auth_app/                  # Users, OTP activation, JWT authentication, password reset
│   ├── api/                   # Authentication serializers, views, and routes
│   ├── migrations/            # Auth database migrations
│   ├── templates/auth_app/    # HTML email templates
│   └── tests/                 # Authentication tests
├── content_app/               # Video model, admin, processing, and media lifecycle
│   ├── api/                   # Video list, protected media, HLS views and routes
│   ├── migrations/            # Video database migrations
│   └── tests/                 # Video, streaming, and cleanup tests
├── core/                      # Django settings and root URL/ASGI/WSGI configuration
├── media/                     # Local media root; Docker mounts a persistent volume here
├── static/                    # Collected static files
├── .env.template              # Environment-variable template
├── backend.Dockerfile         # Python, FFmpeg and backend image
├── backend.entrypoint.sh      # Migrations, superuser, RQ worker and Gunicorn startup
├── docker-compose.yml         # PostgreSQL, Redis and backend services
├── manage.py                  # Django management commands
├── requirements.txt           # Pinned Python dependencies
└── LICENSE                    # MIT license
```

## Configuration

Settings are read from environment variables, with `.env` loaded by `core/settings.py`. `.env.template` is a placeholder template, not a production-ready configuration. Never use its sample or insecure-looking values as real credentials.

> **Email delivery status:** The current `EMAIL_BACKEND` is `django.core.mail.backends.console.EmailBackend`. Activation and password-reset messages are printed to the backend process output; they are **not sent through SMTP**. The `EMAIL_HOST` and related SMTP variables are defined, but will not send email until `EMAIL_BACKEND` is deliberately changed to an SMTP backend.

| Variable | Purpose / observed behavior |
|---|---|
| `SECRET_KEY` | Django signing secret. Set a private, sufficiently random value. |
| `DEBUG` | Enables Django debug behavior when set to `True`; defaults to `True` in settings. |
| `ALLOWED_HOSTS` | Comma-separated allowed host names; settings default to `localhost`. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins; defaults to local frontend origins. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins; defaults to `http://localhost:5500`. Credentials are allowed. |
| `FRONTEND_URL` | Base URL used to construct activation and password-reset links; defaults to `http://localhost:5500`. |
| Frontend `API_BASE_URL` | In the linked frontend's `shared/js/config.js`, the API root is currently `http://127.0.0.1:8000/api/`. Change it there only when the backend is hosted at a different address. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection. Docker Compose expects the database service name `db`; settings default to `db` and port `5432`. |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | Django RQ connection; Compose service hostname is `redis`, default port `6379`, default RQ database `0`. |
| `REDIS_LOCATION` | Redis cache URL; defaults to `redis://redis:6379/1`. |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | Used by the Docker entrypoint to create an initial superuser if that username does not exist. Set a private password. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `DEFAULT_FROM_EMAIL` | SMTP-related settings are present. However, the current `EMAIL_BACKEND` is Django's console backend, so the configured SMTP values are not currently used to send mail. |
| `AUTH_COOKIE_SECURE` | Overrides whether auth cookies use the `Secure` attribute; defaults to `False` when `DEBUG=True` and `True` otherwise. |

docker-compose.yml
The frontend is maintained separately; its source is not included in this backend repository. The frontend repository README states that it is intended for Developer Akademie students and is not freely licensed for redistribution. Review that repository's terms before copying or redistributing it.

## Frontend setup and integration

The linked frontend uses plain HTML, CSS, and Vanilla JavaScript; it does not require a frontend framework or package installation. Its README recommends opening the frontend project in Visual Studio Code and serving the root `index.html` with the Live Server extension (or an equivalent local static server). Serve it over HTTP rather than opening a `file://` URL so browser origin and cookie behavior work as expected.

The frontend's `shared/js/config.js` currently sets `API_BASE_URL` to `http://127.0.0.1:8000/api/`. Its README says that normally no frontend file changes are needed for the supplied local setup. The backend's current `CORS_ALLOWED_ORIGINS` default is `http://localhost:5500`; this matches the usual Live Server origin. If Live Server uses a different host or port, add that exact frontend origin to the backend's `CORS_ALLOWED_ORIGINS` environment variable. CORS entries are for the browser page's origin, not merely the API destination.

The frontend sends API requests with `credentials: 'include'` and configures HLS.js XHR requests with `withCredentials = true`. This allows the backend's HttpOnly JWT cookies to accompany login-dependent API, playlist, segment, and media requests. The frontend does not read the token itself. It also attempts an access-token refresh every 20 minutes. For non-local deployments, coordinate the frontend API URL, backend CORS/CSRF origin settings, HTTPS, and secure cookie configuration; the frontend's local API URL does not configure a deployed backend automatically.

## Implemented features

- Email-based account registration, OTP activation, login, logout, token refresh, and password reset.
- HttpOnly JWT cookies, with an access-token lifetime of 30 minutes and a refresh-token lifetime of 24 hours.
- Authenticated video metadata listing, ordered newest first, limited to videos marked ready and having a thumbnail.
- Django Admin video management, processing status/error display, retry and stuck-job recovery actions.
- Background FFmpeg conversion to HLS at 480p, 720p, and 1080p, plus thumbnail extraction when no thumbnail was uploaded.
- Authenticated playlist and segment API routes, and authenticated direct media-file serving.
- Cleanup of replaced or deleted source files, thumbnails, and unreferenced HLS generations after database commits.

The video-processing worker runs from the web container entrypoint. Queue jobs use Django RQ's `default` queue with a configured default timeout of 900 seconds. Processing errors are logged and recorded on the video; check the Admin and `docker compose logs web` when troubleshooting.

## Authentication

The API uses the custom `CookieJWTAuthentication` class. It reads an access token from the `access_token` HttpOnly cookie; it also accepts the standard JWT authorization header. Login sets `access_token` and `refresh_token` cookies with `HttpOnly`, `SameSite=Lax`, path `/`, and `Secure` determined by `AUTH_COOKIE_SECURE`. Refresh uses the `refresh_token` cookie and rotates tokens according to SimpleJWT settings. Logout requires an authenticated access token and a refresh cookie, blacklists the refresh token, and clears both cookies.

For browser clients, cookie behavior depends on origin, HTTPS, CORS, and browser credential settings. `SameSite=Lax` may not be suitable for every cross-site deployment. Review cookie, CSRF, CORS, and HTTPS configuration for the actual deployment; the project is configured for development defaults and is not certified for production deployment.

## API reference

All routes below are registered in the current URL configuration. “JWT required” means the access token must be supplied by cookie or authorization header. Token refresh instead requires the refresh-token cookie.

| Method | Path | Purpose | Authentication |
|---|---|---|---|
| `POST` | `/api/register/` | Register a user and initiate activation | No |
| `GET` | `/api/activate/<uidb64>/<token>/` | Activate a user account | No |
| `POST` | `/api/login/` | Authenticate and set JWT cookies | No |
| `POST` | `/api/logout/` | Revoke refresh/access tokens and clear cookies | JWT required; refresh cookie required |
| `POST` | `/api/token/refresh/` | Rotate tokens using refresh cookie | Refresh cookie required |
| `POST` | `/api/password_reset/` | Initiate a password-reset email | No |
| `POST` | `/api/password_confirm/<uidb64>/<token>/` | Set a new password with reset token | No |
| `GET` | `/api/video/` | List ready video metadata | JWT required |
| `GET` | `/api/video/<movie_id>/<resolution>/index.m3u8` | Fetch a video HLS playlist | JWT required |
| `GET` | `/api/video/<movie_id>/<resolution>/<segment>` | Fetch a TS segment; no trailing slash | JWT required |
| `GET` | `/media/<path>` | Fetch an uploaded or generated media file | JWT required |

Supported HLS resolutions are `480p`, `720p`, and `1080p`. Playlist responses use `application/vnd.apple.mpegurl`; segment responses use `video/MP2T`. Unknown videos, unsupported resolutions, incomplete videos, invalid segment names, and missing files return `404`. Invalid or missing authentication is rejected. Media responses use `Cache-Control: private, no-store`.

Example login request:

```http
POST /api/login/ HTTP/1.1
Content-Type: application/json

{"email":"<user-email>","password":"<password>"}
```

The response sets HttpOnly cookies. Subsequent requests should send cookies automatically in a same-site browser flow; a command-line client can pass the received cookie jar. Example authenticated request:

```sh
curl --cookie cookies.txt http://localhost:8000/api/video/
```

The segment route intentionally has no trailing slash. This differs from the checked-in API specification, which documents one; clients and external tests must use the implemented route above. The playlist response is currently the generated FFmpeg playlist content; the real FFmpeg integration test verifies that its relative segment entry resolves from the playlist URL to the authenticated segment endpoint.

## Video processing and storage

Videos are uploaded and managed through Django Admin; no video-upload API is registered. Original uploads use `media/videos/`, uploaded thumbnails use `media/thumbnails/`, and generated HLS files use `media/hls/<video_id>/<processing_key>/<resolution>/`. Docker Compose mounts `videoflix_media` at `/app/media`, so these files are held in a persistent named volume rather than only in a disposable container layer.

Creating a video queues an RQ job after its database transaction commits. The worker produces HLS playlists and `.ts` segments for each configured resolution. If there is no uploaded thumbnail, FFmpeg extracts a frame. A video becomes listable after successful publication with a thumbnail. The Admin offers an action to start/retry processing and a separate recovery action for jobs believed to be stuck. Replacing source files causes a new processing generation; stale generations cannot publish over the current one. Cleanup checks references before deleting old files.

FFmpeg is invoked with a 900-second subprocess timeout. The RQ queue's default job timeout is also configured to 900 seconds. Actual processing time depends on input duration, resolution, and available CPU; the timeout may be insufficient for long or high-resolution videos. The repository does not document a maximum upload size or a tested input-format matrix.

## Testing

Run the test suite inside the running Docker web service:

```sh
docker compose exec web python manage.py test --noinput
```

Run a focused test module, for example:

```sh
docker compose exec web python manage.py test content_app.tests.test_video_processing --noinput
```

Check for model changes without creating migrations:

```sh
docker compose exec web python manage.py makemigrations --check --dry-run
```

The tests use Django's test runner and include API, auth, cleanup, and FFmpeg integration checks. FFmpeg must be installed for tests that generate a real media fixture; the supplied backend image includes it.

## Security and operational notes

- Do not use the example secret key, sample credentials, or placeholder SMTP values from `.env.template`. Keep `.env` and all credentials out of version control.
- `DEBUG` defaults to `True`. Do not expose a debug-enabled instance publicly. For non-local deployments, configure `DEBUG=False`, a production secret key, `ALLOWED_HOSTS`, trusted origins, HTTPS, and secure cookies. This educational project does not include a production deployment configuration.
- Uploaded and generated media is served through an authenticated Django endpoint, not the public development `static()` media route. Direct media responses are marked `private, no-store`; make sure any proxy or CDN does not bypass this access control or cache private responses publicly.
- The Docker entrypoint runs `makemigrations` at startup as well as `migrate`. This is the current project behavior; production migration management should be reviewed before deployment.
- The Django-RQ dashboard is mounted at `/django-rq/`; access control for this dashboard should be reviewed before exposing it beyond a trusted development environment.
- The configured email backend is `console`, so activation and reset messages are written to application output rather than delivered by the SMTP settings until the backend is changed.

## License

This project includes an [MIT License](LICENSE).
