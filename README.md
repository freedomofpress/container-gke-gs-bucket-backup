# gke-gs-bucket-backup

Container to take a backup of a Google Cloud GS bucket (S3 bucket) with a kubernetes job

To build the container image:

```bash
podman build .
```

Or pull the pre-built container image:

```bash
podman pull ghcr.io/freedomofpress/gke-gs-bucket-backup
```

Use the below command to see options that can be passed to the container command:

```bash
podman run ghcr.io/freedomofpress/gke-gs-bucket-backup --help
```