FROM python:3.12-slim
WORKDIR /workspace
RUN useradd --create-home --uid 10001 runner
USER runner
ENTRYPOINT ["python"]
