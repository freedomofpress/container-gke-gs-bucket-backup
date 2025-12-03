# sha256 as of 2025-12-02
FROM docker.io/google/cloud-sdk:548.0.0-slim@sha256:17a274eee28444fbdc1ce7410a064943c0dead47042cac07944a9020bd93cbc6

ARG UID=1001

COPY gs_bucket_sync.py /usr/local/bin/gs_bucket_sync.py

RUN adduser --disabled-password --uid "$UID" --gecos "" gcloud_user

USER gcloud_user

ENTRYPOINT [ "/usr/local/bin/gs_bucket_sync.py" ]
