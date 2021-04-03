#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name='git-dumper',
    version='1.0.2',
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
    install_requires=[
        'PySocks',
        'requests',
        'beautifulsoup4',
        'dulwich',
    ],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Topic :: Security',
    ],
)
