#!/usr/bin/env python3
from setuptools import setup, find_packages
from pathlib import Path

setup(
    name='git-dumper',
    version='1.0',
    py_modules=['git_dumper'],
    entry_points={
        'console_scripts': [
            'git-dumper = git_dumper:main',
        ]
    },
    author='Maxime Arthaud',
    author_email='maxime@arthaud.me',
    description='A tool to dump a git repository from a website',
    license='MIT',
    keywords='dump git repository security vulnerability ctf',
    url='https://github.com/arthaud/git-dumper',
    install_requires=Path('requirements.txt').read_text().strip().split('\n'),
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Topic :: Security',
    ],
)
