from setuptools import setup, find_packages
from setuptools import setup

setup(
    name="firecracker-python",
    description="A Python client library to interact with Firecracker microVMs",
    author="Muhammad Yuga Nugraha",
    packages=find_packages(),
    install_requires=[
        "requests==2.32.3",
        "requests-unixsocket==0.4.1",
        "tenacity==9.0.0",
        "psutil==7.0.0",
        "pyroute2==0.8.1",
        "paramiko==3.5.1"
    ],
    python_requires=">=3.8",
    entry_points={
        'console_scripts': [
            'firecracker-check=firecracker.scripts:check_firecracker_binary',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    use_scm_version={
        "write_to": "firecracker/_version.py",
        "version_scheme": "post-release",
    },
    setup_requires=['setuptools_scm'],
)