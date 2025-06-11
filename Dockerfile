FROM mcr.microsoft.com/playwright:v1.52.0
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv /uv /uvx /bin/
COPY server /app
RUN awk '/# dependencies = \[/{flag=1; next} /]/{flag=0} flag' app.py | sed 's/^[ \t]*#*[ \t]*//; s/[",]//g; s/playwright/playwright==1.52.0/' > requirements.txt
RUN uv venv -p python3
RUN uv pip install -n -r requirements.txt
EXPOSE 7777
CMD ["gunicorn", "--bind", "0.0.0.0:7777", "app:app"]
