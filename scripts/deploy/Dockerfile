FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/mvp
WORKDIR /app
COPY requirements.lock /app/requirements.lock
COPY mvp/requirements-server.txt mvp/requirements-postgres.txt /app/mvp/
RUN pip install --no-cache-dir --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.lock -r mvp/requirements-postgres.txt
COPY mvp /app/mvp
COPY scripts /app/scripts
COPY contracts /app/contracts
COPY fixtures /app/fixtures
COPY web/dist /app/web/dist
RUN groupadd -g 10001 rkd && useradd -u 10001 -g rkd -M -s /usr/sbin/nologin rkd
USER 10001:10001
CMD ["python", "scripts/deploy/container_entry.py", "serve"]
