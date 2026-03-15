FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 5001

ENV BOOKS_DIR=/books
ENV PORT=5001

CMD ["bookstuff-web"]
