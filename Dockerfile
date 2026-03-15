FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    mcp \
    starlette \
    uvicorn \
    httpx

COPY server.py .

ENV PORT=8080
EXPOSE 8080

CMD ["python3", "server.py"]
