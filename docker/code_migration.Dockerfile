FROM python:3.11.10-bullseye

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

WORKDIR /

# SWE-ReX will always attempt to install its server into your docker container
# however, this takes a couple of seconds. If we already provide it in the image,
# this is much faster.
RUN pip install pipx
RUN pipx install swe-rex
RUN pipx ensurepath

RUN pip install flake8

SHELL ["/bin/bash", "-c"]
# This is where pipx installs things
ENV PATH="$PATH:/root/.local/bin/"