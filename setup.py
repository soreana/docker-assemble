from setuptools import setup, find_packages

setup(
    name="docker-assemble",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["docker"],
    entry_points={
        "console_scripts": [
            "docker-assemble=docker_assemble.main:run",
        ],
    },
    license="Apache-2.0",
    author="Sina",
    description="A CLI tool to extract and analyze Docker images",
)