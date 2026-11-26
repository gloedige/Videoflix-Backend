# Videoflix Backend

Videoflix Backend is a Django REST Framework application for account registration and authentication, a video catalog, and authenticated HLS playback. Videos are managed through Django Admin and processed asynchronously with FFmpeg using Django RQ and Redis. The associated Vanilla JavaScript frontend is maintained separately in the [Developer Akademie Videoflix frontend repository](https://github.com/Developer-Akademie-Backendkurs/project.Videoflix).

> **Implementation status:** This README describes behavior found in the current source code. The API specification and project checklists include requirements beyond the implementation; only routes and behavior listed below are confirmed as implemented.

## Table of contents

- [Requirements](#requirements)
- [Quick start with Docker Compose](#quick-start-with-docker-compose)
- [Local development without Docker](#local-development-without-docker)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Frontend setup and integration](#frontend-setup-and-integration)
- [Implemented features](#implemented-features)
- [Authentication](#authentication)
- [API reference](#api-reference)
- [Video processing and storage](#video-processing-and-storage)
- [Testing](#testing)
- [Security and operational notes](#security-and-operational-notes)
- [License](#license)

## Requirements

- Docker Engine and Docker Compose for the documented container workflow.
- The backend image is based on Python 3.12 Alpine and installs FFmpeg and the PostgreSQL client. For local development outside Docker, use Python 3.12 and install FFmpeg separately; PostgreSQL and Redis must also be available.
- PostgreSQL and Redis are started by the included Compose configuration.

The repository does not declare a confirmed public clone URL. Obtain the repository URL from its owner, then substitute it for `<repository-url>`:

```sh
git clone <repository-url> Videoflix-Backend
cd Videoflix-Backend
```

## Quick start with Docker Compose

1. Copy the environment template and replace every placeholder, especially secrets and database credentials. Do not commit `.env`.

   **PowerShell:**

   ```powershell
   Copy-Item .env.template .env
   ```

   **macOS/Linux:**

   ```sh
   cp .env.template .env
   ```

2. Start the services from the repository root:

   ```sh
   docker compose up --build -d
   ```

   The Compose file defines PostgreSQL, Redis, and the Django `web` service. The backend is available at `http://localhost:8000/`. The Admin is at `http://localhost:8000/admin/`; create credentials through the configured superuser environment variables before relying on an Admin account.

3. The web entrypoint waits for PostgreSQL, runs `collectstatic`, `makemigrations`, and `migrate`, creates the configured superuser if absent, starts an RQ worker for the `default` queue, and then starts Gunicorn. Inspect startup output with:

   ```sh
   docker compose logs -f web
   ```

4. Stop the services with `docker compose down`. Named volumes retain PostgreSQL data, Redis data, uploaded media, and collected static files. `docker compose down -v` also removes the named volumes and their data; use that only when you intentionally want to delete it.

The Compose service bind-mounts the working tree into `/app`. Rebuild the image with `docker compose up --build -d` after changing dependencies, the Dockerfile, or other image-installed components. Ordinary Python source changes are visible through the bind mount; the entrypoint runs Gunicorn with reload enabled.

## Local development without Docker

A native workflow is possible but requires local PostgreSQL, Redis, and FFmpeg. The checked-in defaults use Compose hostnames (`db` and `redis`), so override them for host-based development, for example with `DB_HOST=localhost`, `REDIS_HOST=localhost`, and `REDIS_LOCATION=redis://localhost:6379/1`. Configure the remaining required database credentials in `.env`.

**PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

In another activated terminal, start the background worker:

```powershell
python manage.py rqworker default
```

**macOS/Linux:**

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

In another activated terminal:

```sh
python manage.py rqworker default
```

The local API is at `http://127.0.0.1:8000/`. These host-based steps follow Django conventions and project settings; the provided Docker workflow is the repository's configured all-services setup.

## Configuration

Settings are read from environment variables, with `.env` loaded by `core/settings.py`. `.env.template` is a placeholder template, not a production-ready configuration. Never use its sample or insecure-looking values as real credentials.

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

## Project structure

```text
auth_app/       Registration, activation, login, logout, reset, JWT auth, and tests
content_app/    Video model, admin, background processing, HLS and media APIs, tests
core/           Django settings, root URL configuration, ASGI and WSGI entry points
media/          Local media directory (Docker uses a persistent named volume)
static/         Collected static files
.env.template   Environment-variable template; copy to the ignored .env file
backend.Dockerfile
                Backend image definition, including FFmpeg installation
docker-compose.yml
                PostgreSQL, Redis and backend service definitions
backend.entrypoint.sh
                Startup initialization, migrations, superuser creation, RQ worker and Gunicorn
requirements.txt
                Pinned Python dependencies
```

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
