import docker
import tarfile
import tempfile
import os
from pathlib import Path
import logging
import io

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
                logging.error(f"File not found: {file_path}")
            except OSError as e:
                logging.error(f"OS error while getting size of {file_path}: {e}")

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

def create_new_image(output_dir, new_image_name):
    client = docker.from_env()
    logging.info(f"Creating new image from directory: {output_dir}")

    def generate_tar(directory):
        with io.BytesIO() as tar_buffer:
            with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                for root, _, files in os.walk(directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, directory)
                        tarinfo = tarfile.TarInfo(name=rel_path)
                        try:
                            tarinfo.size = os.path.getsize(file_path)
                            with open(file_path, 'rb') as f:
                                tar.addfile(tarinfo, fileobj=f)
                        except FileNotFoundError:
                            logging.error(f"File not found while creating tar: {file_path}")
                            continue  # Skip this file and continue with the next
                        except Exception as e:
                            logging.error(f"Error adding {file_path} to tar: {e}")
                            continue

            tar_buffer.seek(0)
            return tar_buffer

    tar_stream = generate_tar(output_dir)
    try:
        response = client.images.build(fileobj=tar_stream, tag=new_image_name, rm=True)
        logging.info(f"New image created: {new_image_name}")
    except docker.errors.BuildError as e:
        logging.error(f"Failed to build image: {e}")
        raise