FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common curl && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv && \
    rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /venv && \
    /venv/bin/pip install --upgrade pip setuptools wheel

WORKDIR /app

COPY hive-datatype/hive_datatype/hive_datatype.py /app/hive_datatype/hive_datatype.py
COPY hive-datatype/hive_datatype/__init__.py /app/hive_datatype/__init__.py

COPY hive-research-gpu/pyproject.toml /app/hive-research-gpu/pyproject.toml
COPY hive-research-gpu/hive_research/ /app/hive-research-gpu/hive_research/
COPY hive-research-gpu/config.yaml /app/config.yaml

RUN /venv/bin/pip install --no-cache-dir /app/hive-research-gpu/

ENV PATH=/venv/bin:$PATH
ENV PYTHONPATH=/app

EXPOSE 7777

COPY <<-"EOF" /app/entrypoint.sh
#!/bin/bash
set -e
exec python -m hive_research serve --host 0.0.0.0 --port 7777
EOF

RUN chmod +x /app/entrypoint.sh

RUN groupadd -r hive && useradd -r -g hive -d /app -s /bin/false hive
RUN mkdir -p /app/data/graph
RUN chown -R hive:hive /app /venv
USER hive

ENTRYPOINT ["/app/entrypoint.sh"]
