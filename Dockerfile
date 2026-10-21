FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY visiontriage ./visiontriage
RUN pip install --no-cache-dir .

EXPOSE 8000 8080
CMD ["uvicorn", "visiontriage.api:app", "--host", "0.0.0.0", "--port", "8080"]
