import docker
import tarfile
import tempfile
import os
from pathlib import Path
import logging
import io


def get_or_pull_image_and_export_fs(client, image_name):
    try:
        client.images.get(image_name)
        logging.info(f"Image '{image_name}' found locally.")
    except docker.errors.ImageNotFound:
        logging.info(f"Image '{image_name}' not found locally. Pulling...")
        client.images.pull(image_name)

    container = client.containers.run(image=image_name, command="sleep infinity", detach=True)
    logging.debug(f"Created temporary container: {container.id[:12]}")

    try:
        stream, _ = container.get_archive("/")
        tmp_tar_path = tempfile.mktemp(suffix=".tar")
        with open(tmp_tar_path, "wb") as f:
            for chunk in stream:
                f.write(chunk)
        return container, tmp_tar_path
    except Exception as e:
        container.remove(force=True)
        raise e


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
        container.remove(force=True)
        if os.path.exists(tmp_tar_path):
            os.remove(tmp_tar_path)
        logging.debug("Cleaned up temporary container and tar file.")


def extract_tar_safely(tar_path: str, output_path: Path):
    # def is_safe_path(base: Path, target: Path) -> bool:
    #     try:
    #         return target.resolve().is_relative_to(base.resolve())
    #     except AttributeError:
    #         # For Python < 3.9 fallback
    #         return str(target.resolve()).startswith(str(base.resolve()))

    with tarfile.open(tar_path, "r") as tar:
        for member in tar.getmembers():
            member.name = member.name.lstrip("/")
            member_path = output_path / member.name

            # if not is_safe_path(output_path, member_path):
            #     logging.warning(f"Blocked unsafe path: {member.name}, output_path: {output_path}, member_path: {member_path}")
            #     continue

            tar.extract(member, path=output_path)
            logging.debug(f"Extracted: {member.name}")

    logging.info(f"Extraction completed to: {output_path}")


def check_large_files(output_dir, max_size_bytes):
    logging.info(f"Checking for files larger than {max_size_bytes} bytes.")
    large_files = []
    for root, _, files in os.walk(output_dir):
        for file in files:
            file_path = Path(root) / file
            try:
                file_size = os.path.getsize(file_path)
                if file_size > max_size_bytes:
                    large_files.append((file_path, file_size))
            except FileNotFoundError:
                logging.debug(f"File not found: {file_path}")
            except OSError as e:
                logging.debug(f"OS error while getting size of {file_path}: {e}")

    if large_files:
        logging.warning("The following files exceed the maximum file size:")
        for path, size in large_files:
            logging.warning(f"- {path}: {size} bytes")
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
            files_to_remove = [large_files[i][0] for i in indices]

            print("Files to be removed:")
            for file in files_to_remove:
                print(file)

            confirmation = input("Are you sure you want to delete these files? (yes/no): ")
            if confirmation.lower() == 'yes':
                for file in files_to_remove:
                    os.remove(file)
                    logging.info(f"Removed file: {file}")
                break
            else:
                print("Removal cancelled.")
        except (ValueError, IndexError) as e:
            print(f"Invalid input: {e}")


def filter_tar_member(member, large_files):
    blocked_prefixes = [
        "proc/",
        "sys/",
        "dev/",
        "run/",
        "tmp/",
        "var/cache/",
        "var/log/",
        "usr/share/doc/",
        "usr/share/man/",
        "usr/share/locale/"
    ]

    for prefix in blocked_prefixes:
        if member.name.startswith(prefix):
            logging.info(f"Skipping blocked path: {member.name}")
            return False

    # Filter large files
    if member.isfile() and any(Path(member.name) == Path(f[0].name) for f in large_files):
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
                new_tar.addfile(member, file_obj)

            # Inject Dockerfile
            dockerfile_data = dockerfile_content.encode("utf-8")
            docker_info = tarfile.TarInfo(name="Dockerfile")
            docker_info.size = len(dockerfile_data)
            new_tar.addfile(docker_info, io.BytesIO(dockerfile_data))

    buffer.seek(0)
    return buffer


def create_new_image(image_name, new_image_name, large_files):
    container = None
    tmp_tar_path = None
    try:
        logging.info(f"Creating new image '{new_image_name}' from '{image_name}' with filtered files.")
        client = docker.from_env()
        container, tmp_tar_path = get_or_pull_image_and_export_fs(client, image_name)

        logging.info(f"Extraction complete. Archive saved at {tmp_tar_path}")

        dockerfile_content = f"""
            FROM scratch
            COPY . /
            """

        # Build filtered tar stream
        filtered_tar_stream = filter_tar_and_inject_dockerfile(
            tmp_tar_path,
            dockerfile_content,
            lambda member: filter_tar_member(member, large_files)
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
        container.remove(force=True)
        if os.path.exists(tmp_tar_path):
            os.remove(tmp_tar_path)
        logging.debug("Cleaned up temporary container and tar file.")
