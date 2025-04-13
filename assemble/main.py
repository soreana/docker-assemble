import argparse
import logging
from assemble.docker_utils import list_docker_images

def run():
    parser = argparse.ArgumentParser(description="Docker Assemble CLI")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("args", nargs="*", help="Arguments for the assemble command")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("Debug mode is ON")
    else:
        logging.basicConfig(level=logging.INFO)

    logging.info(f"Assemble called with args: {args.args}")
    images = list_docker_images()
    logging.info(f"Found {len(images)} images")

    for img in images:
        logging.debug(f"Image: {img.tags} - ID: {img.short_id}")
