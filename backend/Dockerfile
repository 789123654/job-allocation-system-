# Shape verified against fastapi/guide/deployment/docker.md, adapted for uv (not pip/requirements.txt)
# per this project's actual toolchain — see uv's own Docker guide referenced in that doc.
FROM python:3.13-slim

WORKDIR /code

# uv itself, pinned — not installed via curl|sh inside the image.
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

# Docker_Security_Cheat_Sheet.md — never run the app as root.
RUN groupadd -r app && useradd -r -g app app && chown -R app:app /code
USER app

EXPOSE 80

# --forwarded-allow-ips: this container's only ingress is Railway's own edge, not a fixed publishable
# IP — see DEPLOYMENT.md §1 for the reasoning (not the generic --proxy-headers from the FastAPI tutorial,
# which assumes a co-located proxy reachable at 127.0.0.1).
CMD ["uv", "run", "fastapi", "run", "app/main.py", "--port", "80", "--forwarded-allow-ips", "*"]
