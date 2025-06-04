import argparse
import logging
import docker_assemble.image_exporter as image_exporter


def parse_size(size_str):
    suffixes = {'K': 1024, 'M': 1024**2, 'G': 1024**3}
    size_str = size_str.upper()
    if size_str[-1] in suffixes:
        num = size_str[:-1]
        suffix = size_str[-1]
        return int(float(num) * suffixes[suffix])
    else:
        return int(size_str)

def run():
    parser = argparse.ArgumentParser(description="Docker Assemble CLI")
    parser.add_argument("-d", action="store_true", help="Disassemble an image")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--maximum-file-size", type=str, help="Maximum file size (e.g., 1G, 100M, 10K). Files larger than this size will be listed.")
    parser.add_argument("--new-image-name", type=str, help="Name for the new Docker image after removing files.")
    parser.add_argument("image", help="Docker image name")
    parser.add_argument("output_dir", nargs="?", default=".", help="Optional output directory")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    logging.debug(f"Extracting image: {args.image} to directory: {args.output_dir}")
    image_exporter.extract_image(image_name=args.image, output_dir=args.output_dir)

    if args.maximum_file_size:
        max_size_bytes = parse_size(args.maximum_file_size)
        large_files = image_exporter.check_large_files(args.output_dir, max_size_bytes)

        if large_files:
            image_exporter.remove_files(large_files)

        if args.new_image_name:
            image_exporter.create_new_image(args.image, args.new_image_name, large_files)
