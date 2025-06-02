import docker
import tarfile
import tempfile
import os
import shutil
from pathlib import Path
import logging

def extract_image(image_name: str, output_dir: str):
    client = docker.from_env()

    try:
        image = client.images.get(image_name)
        logging.info(f"Image '{image_name}' found locally.")
    except docker.errors.ImageNotFound:
        logging.info(f"Image '{image_name}' not found locally. Pulling...")
        image = client.images.pull(image_name)

    container = client.containers.run(image=image_name, command="sleep infinity", detach=True)
    logging.debug(f"Created temporary container: {container.id[:12]}")

    try:
        stream, _ = container.get_archive("/")
        tmp_tar_path = tempfile.mktemp(suffix=".tar")
        with open(tmp_tar_path, "wb") as f:
            for chunk in stream:
                f.write(chunk)

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



