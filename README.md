# docker-assemble

[![PyPI](https://img.shields.io/pypi/v/docker-assemble)](https://pypi.org/project/docker-assemble/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**docker-assemble** is a Python CLI tool for extracting Docker image filesystems, inspecting image contents, finding large files, and rebuilding optimized Docker images.

It helps developers, researchers, and DevOps engineers understand what is inside a Docker image by exporting the image filesystem into a local directory. You can use it to analyze container images, inspect files, identify oversized files, and optionally create a new Docker image after removing selected files.

## Features

- Extract the filesystem of a Docker image into a local directory
- Pull an image automatically if it is not available locally
- Inspect Docker image contents for research, debugging, and optimization
- Detect files larger than a configurable size limit
- Optionally remove selected large files
- Rebuild a new Docker image from the filtered filesystem
- Simple command-line interface built with Python

## Why use docker-assemble?

Docker images can contain unnecessary files, large artifacts, cached dependencies, logs, build leftovers, or other filesystem content that increases image size. `docker-assemble` makes it easier to inspect the full filesystem of an image and understand what contributes to its size.

This can be useful for:

- Docker image analysis
- Container image optimization
- DevOps research
- Security and filesystem inspection
- Finding large files inside Docker images
- Rebuilding smaller Docker images
- Understanding image contents without manually creating containers

## Installation

Install from PyPI:

```bash
pip install docker-assemble
```

### System-wide installation (all users)

To make `docker-assemble` available to every user on a shared machine, install it outside any single user's home directory.

#### Option 1 — Dedicated venv in `/opt` + symlink

Works on any system with Python 3.8+ and avoids conflicts with OS-managed Python packages:

```bash
sudo python3 -m venv /opt/docker-assemble
sudo /opt/docker-assemble/bin/pip install docker-assemble
sudo ln -s /opt/docker-assemble/bin/docker-assemble /usr/local/bin/docker-assemble
```

Any user with `/usr/local/bin` on their `PATH` can now run `docker-assemble`. To upgrade later:

```bash
sudo /opt/docker-assemble/bin/pip install -U docker-assemble
```

#### Option 2 — pipx (global)

With `pipx` 1.5 or newer:

```bash
sudo pipx install docker-assemble
```

On Ubuntu 24.04 (which ships pipx 1.4.3, predating `--global`), use environment variables instead:

```bash
sudo apt install pipx
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install docker-assemble
```

Both forms place the entry point in `/usr/local/bin/docker-assemble`.

## Requirements

- Python 3.8+
- Docker installed and running
- Access to the Docker daemon

## Basic usage

Extract a Docker image filesystem into a local directory:

```bash
docker-assemble -d ubuntu:20.04 output_dir
```

This extracts the filesystem of `ubuntu:20.04` into `output_dir`.

## Analyze large files

You can scan the extracted filesystem for files larger than a given size:

```bash
docker-assemble -d ubuntu:20.04 output_dir --maximum-file-size 100M
```

Supported size suffixes include:

- `K` for kilobytes
- `M` for megabytes
- `G` for gigabytes

Examples:

```bash
docker-assemble -d ubuntu:20.04 output_dir --maximum-file-size 10M
docker-assemble -d python:3.11 output_dir --maximum-file-size 500M
docker-assemble -d node:20 output_dir --maximum-file-size 1G
```

## Rebuild a Docker image

Pass `--new-image-name` to rebuild the extracted filesystem as a single-layer image (`FROM scratch` + `COPY . /`). `--maximum-file-size` is optional:

- **Without `--maximum-file-size`** — no files are filtered out. The new image contains the same content as the original, just consolidated into one layer. Useful for comparing a multi-layer original against a squashed single-layer version without conflating filtering effects.

  ```bash
  docker-assemble -d ubuntu:20.04 output_dir \
    --new-image-name ubuntu-squashed
  ```

- **With `--maximum-file-size`** — `docker-assemble` lists files above the threshold, asks which should be removed, and rebuilds the image without them:

  ```bash
  docker-assemble -d ubuntu:20.04 output_dir \
    --maximum-file-size 100M \
    --new-image-name ubuntu-optimized
  ```

## Package

`docker-assemble` is available on PyPI:

```bash
pip install docker-assemble
```

PyPI: https://pypi.org/project/docker-assemble/

## Debug mode

Enable debug logging with:

```bash
docker-assemble --debug -d ubuntu:20.04 output_dir
```

## Example workflow

```bash
# Extract a Docker image filesystem
docker-assemble -d python:3.11 python-image-filesystem

# Find files larger than 100 MB
docker-assemble -d python:3.11 python-image-filesystem --maximum-file-size 100M

# Rebuild a new image after removing selected large files
docker-assemble -d python:3.11 python-image-filesystem \
  --maximum-file-size 100M \
  --new-image-name python-optimized
```

## Use cases

`docker-assemble` is useful when you need to:

- inspect the contents of a Docker image
- analyze why a Docker image is large
- identify unnecessary files in a container image
- export an image filesystem for research
- compare Docker image contents
- create a smaller image after removing selected files
- debug container filesystem structure

## How it works

`docker-assemble` uses the Docker SDK for Python to access Docker images. If the requested image is not available locally, it pulls the image. It then creates a temporary container, exports the container filesystem, extracts it into the selected output directory, and optionally rebuilds a new image from a filtered filesystem.

## Project status

This project is in active development. Contributions, issues, and suggestions are welcome.


## License

This project is licensed under the Apache License 2.0.

Docker is a trademark of Docker, Inc. This project is not affiliated with or endorsed by Docker, Inc.
