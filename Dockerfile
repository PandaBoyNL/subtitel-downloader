FROM alpine:latest
RUN apk add --no-cache bash ffmpeg findutils coreutils python3 py3-flask curl
WORKDIR /app
COPY remove_subs.sh /app/remove_subs.sh
COPY app.py /app/app.py
COPY templates /app/templates/
COPY static /app/static/
RUN chmod +x /app/remove_subs.sh
EXPOSE 5000
ENTRYPOINT ["python3", "/app/app.py"]
