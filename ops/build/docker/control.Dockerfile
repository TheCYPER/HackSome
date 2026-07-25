# Thin Docker CLI/Python image for the HackSome Build Hub and lifecycle managers.
#
# This is a thin Docker CLI client plus Python/PyYAML. Manager services mount
# the host Docker socket and create Worker/Verifier/Department containers as
# host siblings; the image never runs a nested daemon. Repository code is
# bind-mounted at runtime so host-side volume sources keep the same absolute
# path when commands cross the Docker socket boundary.

ARG BASE_REGISTRY=docker.io/library
FROM ${BASE_REGISTRY}/docker:cli

RUN apk add --no-cache python3 py3-yaml \
    && ln -sf /usr/bin/python3 /usr/local/bin/python

ENTRYPOINT []
CMD ["sleep", "infinity"]
