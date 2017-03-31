#!/usr/bin/env python3
import argparse
import codecs
import os
import os.path
import re
import requests
import socket
import socks
import sys
import zlib


# return the content of a file
def read_file(path, mode='rb'):
    with open(path, mode) as f:
        return f.read()


# write a file, creating intermediate directories if necessary
def write_file(path, content, mode='wb'):
    dirname, basename = os.path.split(path)

    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)

    with open(path, mode) as f:
        f.write(content)


# download a file in /.git/ and store it in the output directory
def download(base_url, filename, directory):
    print('[-] Fetching %s ... ' % filename, end='')
    req = requests.get('%s/%s' % (base_url, filename))

    print('[%d]' % req.status_code)
    if req.status_code == 200:
        write_file(os.path.join(directory, '.git', filename), req.content)
        return req.content
    else:
        return False


def extract_string(data):
    n = data.find(b'\x00')
    assert n != 1
    return data[:n], data[n + 1:]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Dump a git repository from a website')
    parser.add_argument('url', metavar='URL', help='Starting URL')
    parser.add_argument('directory', metavar='DIR', help='Output directory')
    parser.add_argument('--proxy', help='A proxy to use')
    args = parser.parse_args()

    if args.proxy:
        proxy_valid = False

        for pattern, proxy_type in [
                (r'^socks5:(.*):(\d+)$', socks.PROXY_TYPE_SOCKS5),
                (r'^socks4:(.*):(\d+)$', socks.PROXY_TYPE_SOCKS4),
                (r'^http://(.*):(\d+)$', socks.PROXY_TYPE_HTTP),
                (r'^(.*):(\d+)$', socks.PROXY_TYPE_SOCKS5)]:
            m = re.match(pattern, args.proxy)
            if m:
                socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, m.group(1), int(m.group(2)))
                socket.socket = socks.socksocket
                proxy_valid = True
                break

        if not proxy_valid:
            parser.error('invalid proxy')

    # base url
    base_url = args.url.rstrip('/')
    if not base_url.endswith('.git'):
        base_url += '/.git'

    # check for /.git/HEAD
    if requests.get('%s/HEAD' % base_url).status_code != 200:
        print('error: %s does not seem to have a .git' % base_url[:-5], file=sys.stderr)
        exit(1)

    # check for directory listing
    if requests.get('%s/objects' % base_url).status_code == 200:
        print('error: directory listing is allowed, you should use wget -r', file=sys.stderr)
        exit(2)

    # output directory
    directory = args.directory

    if not os.path.exists(directory):
        os.makedirs(directory)

    if os.listdir(directory):
        parser.error('%s is not empty' % directory)

    # fetch the basic schema
    queue = [
        'HEAD',
        'config',
        'description',
        'index',
        'packed-refs',
        'COMMIT_EDITMSG',
        'logs/HEAD',
        'logs/refs/remotes/origin/HEAD',
        'refs/remotes/origin/HEAD',
        'refs/stash',
        'info/exclude',
        'info/refs',
        'objects/info/packs',
    ]

    while queue:
        filename = queue.pop(0)
        download(base_url, filename, directory)

    # get the current head
    head_content = read_file(os.path.join(directory, '.git', 'HEAD'), 'r')
    m = re.match(r'^ref: refs/heads/([a-zA-Z0-9\-\._]+)$', head_content)
    assert m, 'error while parsing /.git/HEAD'
    head = m.group(1)

    # get head info
    obj = download(base_url, 'refs/heads/%s' % head, directory)
    download(base_url, 'logs/refs/heads/%s' % head, directory)

    queue = [obj.decode().strip()]
    mapping = {}
    seen = set()

    # fetch all objects
    while queue:
        obj = queue.pop(0)

        if obj in seen:
            continue

        seen.add(obj)

        print('[-] Current queue: %d' % (len(queue) + 1))

        content = download(base_url, 'objects/%s/%s' % (obj[:2], obj[2:]), directory)

        if content:
            content = zlib.decompress(content)

            if content.startswith(b'commit '):
                _, content = extract_string(content)

                for line in content.split(b'\n'):
                    if line.startswith(b'tree '):
                        obj = line.split()[1].decode()
                        queue.insert(0, obj)
                    elif line.startswith(b'parent '):
                        obj = line.split()[1].decode()
                        queue.append(obj)
                    elif not line:
                        break # end
            elif content.startswith(b'tree '):
                _, content = extract_string(content)
                while content:
                    line, content = extract_string(content)
                    obj, content = content[:20], content[20:]
                    filename = line[7:].decode()
                    obj = codecs.encode(obj, 'hex').decode()
                    mapping[obj] = filename
                    queue.insert(0, obj)
            elif content.startswith(b'blob '):
                _, content = extract_string(content)
                write_file(os.path.join(directory, mapping[obj], obj), content)
            else:
                print('error: unexpected object', file=sys.stderr)
                exit(1)
