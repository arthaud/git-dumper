# git-dumper

A tool to dump a git repository from a website.

## Install

This can be installed easily with [`uv`](https://docs.astral.sh/uv/):
```bash
uv tool install git-dumper
```

Alternatively, you can install it via pip. Note that modern Python environments may require you to use a virtual environment or the --user flag to avoid conflicts:
```bash
# Using a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install git-dumper

# OR using the --user flag
pip install --user git-dumper
```

## Usage

```
usage: git-dumper [options] URL DIR

Dump a git repository from a website.

positional arguments:
  URL                   URL
  DIR                   Output directory

options:
  -h, --help            show this help message and exit
  --proxy PROXY         Use the specified proxy
  --client-cert-p12 CLIENT_CERT_P12
                        Client certificate in PKCS#12
  --client-cert-p12-password CLIENT_CERT_P12_PASSWORD
                        Password for the client certificate
  -j, --jobs JOBS       Number of simultaneous requests
  -r, --retry RETRY     Number of request attempts before giving up
  -t, --timeout TIMEOUT
                        Maximum time in seconds before giving up
  -u, --user-agent USER_AGENT
                        User-agent to use for requests
  -H, --header HEADER   Additional http headers, e.g `NAME=VALUE`
  -b, --branch BRANCHES
                        Additional branch names to check for, e.g. `-b dev -b prod`. The default branches (`main`, `master`, `staging`, `production`, `development`) are always checked.
  -F, --force           Ignore any non fatal error
```

### Example

```
git-dumper http://website.com/.git ~/website
```


### Disclaimer

**Use this software at your own risk!**

You should know that if the repository you are downloading is controlled by an attacker,
this could lead to remote code execution on your machine.

## Build from source

Simply install the dependencies with pip:
```
pip install -r requirements.txt
```

Then, simply use:
```
./git_dumper.py http://website.com/.git ~/website
```

## How does it work?

The tool will first check if directory listing is available. If it is, then it will just recursively download the .git directory (what you would do with `wget`).

If directory listing is not available, it will use several methods to find as many files as possible. Step by step, git-dumper will:
* Fetch all common files (`.gitignore`, `.git/HEAD`, `.git/index`, etc.);
* Find as many refs as possible (such as `refs/heads/master`, `refs/remotes/origin/HEAD`, etc.) by analyzing `.git/HEAD`, `.git/logs/HEAD`, `.git/config`, `.git/packed-refs` and so on;
* Find as many objects (sha1) as possible by analyzing `.git/packed-refs`, `.git/index`, `.git/refs/*` and `.git/logs/*`;
* Fetch all objects recursively, analyzing each commits to find their parents;
* Run `git checkout .` to recover the current working tree
