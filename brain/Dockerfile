FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi uvicorn httpx
WORKDIR /app
COPY app.py persona.txt memes.txt board.html ./
COPY personas/ ./personas/
EXPOSE 6190
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "6190"]
