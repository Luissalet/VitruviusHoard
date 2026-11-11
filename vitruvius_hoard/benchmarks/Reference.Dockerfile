FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS node
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY reference-dependencies.json /dependencies.json
COPY build_runtime.py /build_runtime.py
RUN python /build_runtime.py
COPY container_entry.py /entry.py
ENV HOST=0.0.0.0 PORT=8080 DATA_DIR=/state SEED=0 TZ=UTC PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "/entry.py"]
