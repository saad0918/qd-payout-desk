FROM python:3.12-slim
WORKDIR /app
COPY server.pyc .
ENV PORT=8081
EXPOSE 8081
CMD ["python", "-u", "server.pyc"]
