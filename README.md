# git-dumper

A tool to dump a git repository from a website.

## Install

To install `git-dumper`, it is recommended to use a Python virtual environment to avoid conflicts with your system's packages (especially on Linux distributions enforcing **PEP 668**).

Follow these steps:

```
git clone https://github.com/arthaud/git-dumper.git

cd git-dumper

python -m venv .venv

source venv/bin/activate

pip install -r requirements.txt
```

**Note:** Whenever you want to run  git-dumper  again in a new terminal session, remember to navigate to the folder and run  `source venv/bin/activate ` first.

## Usage

```
usage: git-dumper [options] URL DIR

Dump a git repository from a website.

positional arguments:
  URL                   url
  DIR                   output directory

optional arguments:
  -h, --help            show this help message and exit
  --proxy PROXY         use the specified proxy
  -j JOBS, --jobs JOBS  number of simultaneous requests
  -r RETRY, --retry RETRY
                        number of request attempts before giving up
  -t TIMEOUT, --timeout TIMEOUT
                        maximum time in seconds before giving up
  -u USER_AGENT, --user-agent USER_AGENT
                        user-agent to use for requests
  -H HEADER, --header HEADER
                        additional http headers, e.g `NAME=VALUE`
  --client-cert-p12 CLIENT_CERT_P12
                        client certificate in PKCS#12 format
  --client-cert-p12-password CLIENT_CERT_P12_PASSWORD
                        password for the client certificate
  -b BRANCH, --branch BRANCH
                        additional branch name to check for (repeatable)
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
