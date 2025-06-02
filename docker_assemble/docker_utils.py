import docker

def list_docker_images():
    client = docker.from_env()
    return client.images.list()
