# Foundagent platform — singleton Company mail-router image.
#
# Polls the R2 inbox/ prefix, parses raw MIME, resolves the globally claimed
# Company, appends to that Company's private mail journal, and archives the
# source object to processed/ or unmatched/. It never invokes an LLM or fans
# out to Department inboxes.
#
# Unlike the Hub/control services (bind-mounted source on a shared lean image),
# the two packages are COPIED in: the mail backend is pluggable as a UNIT
# (design §1) and boto3 is its only third-party dep — a dedicated image keeps
# that dep out of every other service. This reference image is not wired into
# the active Team Compose.
#
# Manual build context = repo root, filtered by the root .dockerignore.
FROM python:3.12-slim

RUN pip install --no-cache-dir boto3

WORKDIR /opt/foundagent-orch
ENV PYTHONPATH=/opt/foundagent-orch \
    PYTHONUNBUFFERED=1

COPY peripheral/ peripheral/
COPY orchestration/ orchestration/

ENTRYPOINT ["python3", "-m", "peripheral.email.poller"]
