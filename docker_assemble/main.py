import argparse
import logging
import os
from docker_assemble.image_exporter import extract_image

def run():
    parser = argparse.ArgumentParser(description="Docker Assemble CLI")
    parser.add_argument("-d", action="store_true", help="Disassemble an image")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("image", help="Docker image name")
    parser.add_argument("output_dir", nargs="?", default=".", help="Optional output directory")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    logging.debug(f"Extracting image: {args.image} to directory: {args.output_dir}")
    extract_image(image_name=args.image, output_dir=args.output_dir)
