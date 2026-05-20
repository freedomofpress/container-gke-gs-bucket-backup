# sha256 as of 2020-07-31 for 303.0.0-slim
FROM docker.io/google/cloud-sdk:303.0.0-slim@sha256:3eb726653fe2f83952982bd47607c563e387bfc791f7d431f7f1446acaaedadf

ARG UID=1001

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY gs_bucket_sync.py /usr/local/bin/gs_bucket_sync.py

RUN adduser --disabled-password --uid "$UID" --gecos "" gcloud_user

USER gcloud_user

ENV PYTHONUNBUFFERED=1

ENTRYPOINT [ "/usr/local/bin/entrypoint.sh" ]
