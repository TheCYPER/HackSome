#!/bin/bash
# Start the computer server already bundled in the upstream CUA image.
#
# The upstream startup hook upgrades a broad optional ML stack on every boot.
# Build Stage supplies the model runtime in its Agent image, so that upgrade is
# unnecessary and makes desktop startup depend on a large network download.
exec /usr/bin/python3 -m computer_server
