import docker
import tarfile
import tempfile
import os
import json
from pathlib import Path
import logging
import io


class UnsupportedImageError(Exception):
    """Raised when a reference is not a runnable image and therefore cannot be
    disassembled or rebuilt — e.g. an OCI artifact such as a cosign signature
    (.sig), attestation (.att), or SBOM (.sbom). These have no valid root
    filesystem, so the daemon rejects container creation."""


# Substrings the Docker daemon returns when a "image" is really an OCI artifact
# (cosign signature/attestation/SBOM) with no usable rootfs.
_NOT_RUNNABLE_DAEMON_ERRORS = (
    "mismatched image rootfs and manifest layers",
)


def _is_not_runnable_image_error(error):
    explanation = getattr(error, "explanation", None) or str(error)
    return any(marker in explanation for marker in _NOT_RUNNABLE_DAEMON_ERRORS)


def create_temp_container(client, image_name):
    """Create a stopped temporary container for export, translating the daemon's
    'not a runnable image' failure into a clean UnsupportedImageError.

    A command must be supplied even though the container is never started: the
    daemon validates one at create time, so images with an empty Cmd/Entrypoint
    would otherwise fail with 400 'no command specified'."""
    try:
        return client.containers.create(image=image_name, command="sleep infinity")
    except docker.errors.APIError as e:
        if _is_not_runnable_image_error(e):
            raise UnsupportedImageError(
                f"'{image_name}' is not a runnable image (it looks like an OCI "
                f"artifact such as a cosign signature/attestation/SBOM); it has no "
                f"filesystem to disassemble or rebuild."
            ) from e
        raise


def ensure_image_present(client, image_name):
    """Make sure the image exists locally, pulling it if necessary."""
    try:
        client.images.get(image_name)
        logging.info(f"Image '{image_name}' found locally.")
    except docker.errors.ImageNotFound:
        logging.info(f"Image '{image_name}' not found locally. Pulling...")
        client.images.pull(image_name)


def get_or_pull_image_and_export_fs(client, image_name):
    ensure_image_present(client, image_name)

    container = create_temp_container(client, image_name)
    logging.debug(f"Created temporary container: {container.id[:12]}")

    tmp_tar_path = None
    try:
        stream, _ = container.get_archive("/")
        tmp_tar_path = tempfile.mktemp(suffix=".tar")
        try:
            with open(tmp_tar_path, "wb") as f:
                for chunk in stream:
                    f.write(chunk)
        finally:
            # Ensure the daemon-backed stream is released even on a partial
            # write (e.g. disk full) rather than waiting for GC.
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        return container, tmp_tar_path
    except Exception as e:
        container.remove(force=True)
        if tmp_tar_path is not None and os.path.exists(tmp_tar_path):
            os.remove(tmp_tar_path)
        raise e


def _cleanup_container_and_tar(container, tmp_tar_path):
    """Best-effort cleanup that never raises, so it cannot mask the original
    exception when invoked from a finally block."""
    if container is not None:
        try:
            container.remove(force=True)
        except Exception:
            logging.warning(
                "Failed to remove temporary container during cleanup", exc_info=True
            )
    if tmp_tar_path is not None and os.path.exists(tmp_tar_path):
        try:
            os.remove(tmp_tar_path)
        except OSError:
            logging.warning(
                f"Failed to remove temporary tar {tmp_tar_path} during cleanup",
                exc_info=True,
            )
    logging.debug("Cleaned up temporary container and tar file.")


def extract_image(image_name: str, output_dir: str):
    container = None
    tmp_tar_path = None
    try:
        client = docker.from_env()
        container, tmp_tar_path = get_or_pull_image_and_export_fs(client, image_name)

        logging.debug(f"Filesystem archive saved to: {tmp_tar_path}")

        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        extract_tar_safely(tmp_tar_path, output_path)

        logging.info(f"Image filesystem extracted to: {output_path}")

    finally:
        _cleanup_container_and_tar(container, tmp_tar_path)


def extract_tar_safely(tar_path: str, output_path: Path):
    # def is_safe_path(base: Path, target: Path) -> bool:
    #     try:
    #         return target.resolve().is_relative_to(base.resolve())
    #     except AttributeError:
    #         # For Python < 3.9 fallback
    #         return str(target.resolve()).startswith(str(base.resolve()))

    # Two-pass extraction so read-only directory modes don't block writing the
    # files inside them. tarfile applies each directory's mode the moment it is
    # extracted, so a restrictive dir (e.g. 0o555 on UBI/RHEL rootfs) makes the
    # next file member inside it fail with PermissionError. We extract every
    # directory with a temporarily writable mode, then restore the original
    # modes in a second pass (deepest-first, so tightening a parent never blocks
    # restoring a child).
    dir_modes = {}

    with tarfile.open(tar_path, "r") as tar:
        for member in tar.getmembers():
            member.name = member.name.lstrip("/")
            if not member.name:
                continue

            # member_path = output_path / member.name
            # if not is_safe_path(output_path, member_path):
            #     logging.warning(f"Blocked unsafe path: {member.name}, output_path: {output_path}, member_path: {member_path}")
            #     continue

            if member.isdir():
                dir_modes[member.name] = member.mode
                # Force a writable+traversable mode for the duration of the
                # extraction; the original mode is restored below.
                member.mode = 0o755

            tar.extract(member, path=output_path)
            logging.debug(f"Extracted: {member.name}")

    # Restore directory modes deepest-first so a parent that becomes read-only
    # is only tightened after all of its children have been handled.
    for name in sorted(dir_modes, key=lambda n: n.count("/"), reverse=True):
        dir_path = output_path / name
        try:
            os.chmod(dir_path, dir_modes[name])
        except OSError as e:
            logging.debug(f"Could not restore mode on {dir_path}: {e}")

    logging.info(f"Extraction completed to: {output_path}")


def check_large_files(output_dir, max_size_bytes):
    logging.info(f"Checking for files larger than {max_size_bytes} bytes.")
    large_files = []
    for root, _, files in os.walk(output_dir):
        for file in files:
            file_path = Path(root) / file
            try:
                file_size = os.path.getsize(file_path)
                rel_path = file_path.relative_to(output_dir)
                if file_size > max_size_bytes:
                    large_files.append((rel_path, file_size))
            except FileNotFoundError:
                logging.debug(f"File not found: {file_path}")
            except OSError as e:
                logging.debug(f"OS error while getting size of {file_path}: {e}")

    if large_files:
        logging.warning("The following files exceed the maximum file size:")
        for idx, (path, size) in enumerate(large_files):
            logging.warning(f"{idx}: {path}: {size} bytes")
    else:
        logging.info("No files exceed the maximum file size.")

    return large_files


def remove_files(large_files):
    while True:
        indices_str = input("Enter the indices of files to remove (comma-separated, or 'no' to skip): ")
        if indices_str.lower() == 'no':
            logging.info("No files will be removed.")
            break

        try:
            indices = [int(i) for i in indices_str.split(',')]
            removed_files = [Path("/" + str(large_files[i][0])) for i in indices]

            print("Files to be removed:")
            for file in removed_files:
                print(file)

            confirmation = input("Are you sure you want to delete these files? (yes/no): ")
            if confirmation.lower() == 'yes':
                for file in removed_files:
                    logging.info(f"Removed file: {file}")
                return removed_files;
            else:
                print("Removal cancelled.")
        except (ValueError, IndexError) as e:
            print(f"Invalid input: {e}")


def filter_tar_member(member, removed_files):
    # Filter removed files
    if member.isfile() and any(Path(member.name) == f for f in removed_files):
        logging.info(f"Skipping large file: {member.name} ({member.size} bytes)")
        return False

    return True


# Rebuild tar stream while filtering and injecting Dockerfile
def filter_tar_and_inject_dockerfile(original_tar_path, dockerfile_content, filter_callback):
    buffer = io.BytesIO()

    with tarfile.open(original_tar_path, "r") as old_tar:
        with tarfile.open(fileobj=buffer, mode="w:gz") as new_tar:
            for member in old_tar.getmembers():
                if not filter_callback(member):
                    continue

                file_obj = old_tar.extractfile(member) if member.isfile() else None
                try:
                    new_tar.addfile(member, file_obj)
                finally:
                    if file_obj is not None:
                        file_obj.close()

            # Inject Dockerfile
            dockerfile_data = dockerfile_content.encode("utf-8")
            docker_info = tarfile.TarInfo(name="Dockerfile")
            docker_info.size = len(dockerfile_data)
            new_tar.addfile(docker_info, io.BytesIO(dockerfile_data))

    buffer.seek(0)
    return buffer


def _split_repository_tag(image_name):
    """Split 'repo:tag' into (repository, tag), defaulting tag to 'latest'.
    Only the last path component may carry a tag, so a registry port
    (e.g. 'localhost:5000/img') is not mistaken for a tag."""
    repository, sep, tag = image_name.rpartition(":")
    if sep and "/" not in tag:
        return repository, tag
    return image_name, "latest"


def image_config_to_changes(client, image_name):
    """Translate the original image's runtime config into Dockerfile-style
    ``--change`` directives so an imported image keeps CMD/ENTRYPOINT/ENV/etc.

    ``docker import`` produces a config-less image; passing these ``changes``
    to the import call restores the metadata that the streaming fast-path would
    otherwise drop."""
    config = client.images.get(image_name).attrs.get("Config") or {}
    changes = []

    for env in config.get("Env") or []:
        changes.append(f"ENV {env}")

    workdir = config.get("WorkingDir")
    if workdir:
        changes.append(f"WORKDIR {workdir}")

    user = config.get("User")
    if user:
        changes.append(f"USER {user}")

    for port in (config.get("ExposedPorts") or {}):
        changes.append(f"EXPOSE {port}")

    for volume in (config.get("Volumes") or {}):
        changes.append(f"VOLUME {volume}")

    for key, value in (config.get("Labels") or {}).items():
        changes.append(f"LABEL {json.dumps(key)}={json.dumps(value)}")

    entrypoint = config.get("Entrypoint")
    if entrypoint:
        changes.append(f"ENTRYPOINT {json.dumps(entrypoint)}")

    cmd = config.get("Cmd")
    if cmd:
        changes.append(f"CMD {json.dumps(cmd)}")

    return changes


def rebuild_via_export_import(client, image_name, new_image_name):
    """Fast-path rebuild for the no-filter case: stream the container's
    filesystem straight from ``docker export`` into ``docker import`` without
    ever touching disk or running ``tar.extract``. Runtime metadata from the
    source image is preserved via ``changes``."""
    ensure_image_present(client, image_name)

    repository, tag = _split_repository_tag(new_image_name)
    changes = image_config_to_changes(client, image_name)

    container = None
    try:
        # create (not run) is enough to export the filesystem and avoids
        # spawning a 'sleep infinity' process we would have to reap.
        container = create_temp_container(client, image_name)
        logging.debug(f"Created temporary container: {container.id[:12]}")

        export_stream = client.api.export(container.id)
        client.api.import_image(
            src=export_stream,
            repository=repository,
            tag=tag,
            changes=changes,
            stream_src=True,
        )
        logging.info(
            f"New image successfully created via export|import: {new_image_name}"
        )
    finally:
        _cleanup_container_and_tar(container, None)


def create_new_image(image_name, new_image_name, removed_files):
    client = docker.from_env()

    # No files to filter out -> use the streaming export|import fast-path.
    if not removed_files:
        logging.info(
            f"Creating new image '{new_image_name}' from '{image_name}' "
            f"via streaming export|import (no filtering requested)."
        )
        rebuild_via_export_import(client, image_name, new_image_name)
        return

    container = None
    tmp_tar_path = None
    try:
        logging.info(f"Creating new image '{new_image_name}' from '{image_name}' with filtered files.")
        container, tmp_tar_path = get_or_pull_image_and_export_fs(client, image_name)

        logging.debug(f"Extraction complete. Archive saved at {tmp_tar_path}")

        dockerfile_content = f"""
            FROM scratch
            COPY . /
            """

        # Build filtered tar stream
        filtered_tar_stream = filter_tar_and_inject_dockerfile(
            tmp_tar_path,
            dockerfile_content,
            lambda member: filter_tar_member(member, removed_files)
        )

        # Build Docker image directly from filtered tar stream
        image, logs = client.images.build(
            fileobj=filtered_tar_stream,
            tag=new_image_name,
            rm=True,
            custom_context=True
        )

        for line in logs:
            logging.debug(line)

        logging.info(f"New image successfully created: {new_image_name}")

    finally:
        _cleanup_container_and_tar(container, tmp_tar_path)
