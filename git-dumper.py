#!/usr/bin/env python3
from contextlib import closing
import argparse
import codecs
import multiprocessing
import os
import os.path
import re
import socket
import subprocess
import sys
import zlib

import bs4
import requests
import socks


def printf(fmt, *args, file=sys.stdout):
    if args:
        fmt = fmt % args

    file.write(fmt)
    file.flush()


def is_index_html(content):
    ''' Return True if `content` is a directory index '''

    if isinstance(content, str):
        content = content.encode('UTF-8')

    return content.startswith(b'<!DOCTYPE HTML') and b'Index of ' in content


def create_intermediate_dirs(path):
    ''' Create intermediate directories, if necessary '''

    dirname, basename = os.path.split(path)

    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)


def extract_cstring(data):
    ''' Extract a C-string (\0 terminated) from a BLOB '''
    n = data.find(b'\x00')
    assert n != -1
    return data[:n], data[n + 1:]


class Worker(multiprocessing.Process):
    ''' Worker for process_tasks '''

    def __init__(self, pending_tasks, tasks_done, args):
        super().__init__()
        self.daemon = True
        self.pending_tasks = pending_tasks
        self.tasks_done = tasks_done
        self.args = args

    def run(self):
        # initialize process
        self.init(*self.args)

        # fetch and do tasks
        while True:
            task = self.pending_tasks.get(block=True)

            if task is None: # end signal
                return

            result = self.do_task(task, *self.args)

            assert isinstance(result, list), 'do_task() should return a list of tasks'

            self.tasks_done.put(result)

    def init(self, *args):
        raise NotImplementedError

    def do_task(self, task, *args):
        raise NotImplementedError


def process_tasks(initial_tasks, worker, jobs, args=()):
    ''' Process tasks in parallel '''

    pending_tasks = multiprocessing.Queue()
    tasks_done = multiprocessing.Queue()
    num_pending_tasks = 0
    tasks_seen = set()

    # add all initial tasks in the queue
    for task in initial_tasks:
        assert task is not None
        pending_tasks.put(task)
        num_pending_tasks += 1
        tasks_seen.add(task)

    # initialize processes
    processes = [worker(pending_tasks, tasks_done, args) for _ in range(jobs)]

    # launch them all
    for p in processes:
        p.start()

    # collect task results
    while num_pending_tasks > 0:
        task_result = tasks_done.get(block=True)
        num_pending_tasks -= 1

        for task in task_result:
            assert task is not None

            if task not in tasks_seen:
                pending_tasks.put(task)
                num_pending_tasks += 1
                tasks_seen.add(task)

    # send termination signal (task=None)
    for _ in range(jobs):
        pending_tasks.put(None)

    # join all
    for p in processes:
        p.join()


class DownloadWorker(Worker):
    ''' Download a list of files '''

    def init(self, url, directory, retry, timeout):
        self.session = requests.Session()
        self.session.mount(url, requests.adapters.HTTPAdapter(max_retries=retry))

    def do_task(self, filepath, url, directory, retry, timeout):
        with closing(self.session.get('%s/%s' % (url, filepath), stream=True, timeout=timeout)) as response:
            printf('[-] Fetching %s/%s [%d]\n', url, filepath, response.status_code)

            if response.status_code != 200:
                return []

            abspath = os.path.abspath(os.path.join(directory, filepath))
            create_intermediate_dirs(abspath)

            # write file
            with open(abspath, 'wb') as f:
                for chunk in response.iter_content(4096):
                    f.write(chunk)

            return []


class RecursiveDownloadWorker(DownloadWorker):
    ''' Download a directory recursively '''

    def do_task(self, filepath, url, directory, retry, timeout):
        with closing(self.session.get('%s/%s' % (url, filepath), stream=True, timeout=timeout)) as response:
            printf('[-] Fetching %s/%s [%d]\n', url, filepath, response.status_code)

            if response.status_code != 200:
                return []

            it = response.iter_content(4094)
            first_chunk = next(it)

            if is_index_html(first_chunk): # directory index
                html = first_chunk
                for chunk in it:
                    html += chunk

                # find all links
                html = bs4.BeautifulSoup(html, 'html.parser')
                tasks = []

                for link in html.find_all('a'):
                    href = link.get('href')

                    if not href.startswith('/') and not href.startswith('?'):
                        tasks.append(filepath + '/' + href.rstrip('/'))

                return tasks
            else: # file
                abspath = os.path.abspath(os.path.join(directory, filepath))
                create_intermediate_dirs(abspath)

                # write file
                with open(abspath, 'wb') as f:
                    f.write(first_chunk)
                    for chunk in it:
                        f.write(chunk)

                return []


class FindRefsWorker(DownloadWorker):
    ''' Find refs/ '''

    def do_task(self, filepath, url, directory, retry, timeout):
        response = self.session.get('%s/%s' % (url, filepath), timeout=timeout)
        printf('[-] Fetching %s/%s [%d]\n', url, filepath, response.status_code)

        if response.status_code != 200:
            return []

        abspath = os.path.abspath(os.path.join(directory, filepath))
        create_intermediate_dirs(abspath)

        # write file
        with open(abspath, 'w') as f:
            f.write(response.text)

        # find refs
        tasks = []

        for ref in re.findall(r'(refs(/[a-zA-Z0-9\-\.\_\*]+)+)', response.text):
            ref = ref[0]
            if not ref.endswith('*'):
                tasks.append('.git/%s' % ref)
                tasks.append('.git/logs/%s' % ref)

        return tasks


class FindObjectsWorker(DownloadWorker):
    ''' Find objects '''

    def do_task(self, obj, url, directory, retry, timeout):
        filepath = '.git/objects/%s/%s' % (obj[:2], obj[2:])
        response = self.session.get('%s/%s' % (url, filepath), timeout=timeout)
        printf('[-] Fetching %s/%s [%d]\n', url, filepath, response.status_code)

        if response.status_code != 200:
            return []

        abspath = os.path.abspath(os.path.join(directory, filepath))
        create_intermediate_dirs(abspath)

        # write file
        with open(abspath, 'wb') as f:
            f.write(response.content)

        # parse object file to find other objects
        tasks = []
        content = zlib.decompress(response.content)
        content_type, content = extract_cstring(content)

        if content_type.startswith(b'commit '):
            for line in content.split(b'\n'):
                if line.startswith(b'tree ') or line.startswith(b'parent '):
                    obj = line.split()[1].decode()
                    tasks.append(obj)
        elif content_type.startswith(b'tree '):
            while content:
                _, content = extract_cstring(content)
                obj, content = content[:20], content[20:]
                obj = codecs.encode(obj, 'hex').decode()
                tasks.append(obj)
        elif content_type.startswith(b'blob '):
            pass
        else:
            printf('error: unexpected object type: %r\n' % content_type, file=sys.stderr)
            sys.exit(1)

        return tasks


def fetch_git(url, directory, jobs, retry, timeout):
    ''' Dump a git repository into the output directory '''

    assert os.path.isdir(directory), '%s is not a directory' % directory
    assert not os.listdir(directory), '%s is not empty' % directory
    assert jobs >= 1, 'invalid number of jobs'
    assert retry >= 1, 'invalid number of retries'
    assert timeout >= 1, 'invalid timeout'

    # find base url
    url = url.rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]
    url = url.rstrip('/')

    # check for /.git/HEAD
    printf('[-] Testing %s/.git/HEAD ', url)
    response = requests.get('%s/.git/HEAD' % url)
    printf('[%d]\n', response.status_code)
    if response.status_code != 200:
        printf('error: %s/.git/HEAD does not exist\n', url, file=sys.stderr)
        return 1

    # check for directory listing
    printf('[-] Testing %s/.git/ ', url)
    response = requests.get('%s/.git/' % url)
    printf('[%d]\n', response.status_code)
    if response.status_code == 200:
        if not is_index_html(response.text):
            printf('error: unexpected response for %s/.git/\n', url, file=sys.stderr)
            return 1

        printf('[-] Fetching .git recursively\n')
        process_tasks(['.git', '.gitignore'],
                      RecursiveDownloadWorker,
                      jobs,
                      args=(url, directory, retry, timeout))

        printf('[-] Running git checkout .\n')
        os.chdir(directory)
        subprocess.check_call(['git', 'checkout', '.'])
        return 0

    # no directory listing
    printf('[-] Fetching common files\n')
    tasks = [
        '.gitignore',
        '.git/description',
        '.git/index',
        '.git/COMMIT_EDITMSG',
        '.git/info/exclude',
        '.git/info/refs',
        '.git/objects/info/packs',
    ]
    process_tasks(tasks,
                  DownloadWorker,
                  jobs,
                  args=(url, directory, retry, timeout))

    # find refs
    printf('[-] Finding refs/\n')
    tasks = [
        '.git/config',
        '.git/packed-refs',
        '.git/HEAD',
        '.git/logs/HEAD',
        '.git/refs/heads/master'
        '.git/logs/refs/heads/master'
        '.git/refs/remotes/origin/HEAD',
        '.git/logs/refs/remotes/origin/HEAD',
        '.git/refs/stash',
        '.git/logs/refs/stash',
    ]
    process_tasks(tasks,
                  FindRefsWorker,
                  jobs,
                  args=(url, directory, retry, timeout))

    # find objects
    printf('[-] Finding objects\n')
    objs = set()

    # .git/packed-refs, .git/refs/*, .git/logs/*
    files = [
        os.path.join(directory, '.git', 'packed-refs'),
    ]
    for dirpath, _, filenames in os.walk(os.path.join(directory, '.git', 'refs')):
        for filename in filenames:
            files.append(os.path.join(dirpath, filename))
    for dirpath, _, filenames in os.walk(os.path.join(directory, '.git', 'logs')):
        for filename in filenames:
            files.append(os.path.join(dirpath, filename))

    for filepath in files:
        if not os.path.exists(filepath):
            continue

        with open(filepath, 'r') as f:
            content = f.read()

        for obj in re.findall(r'(^|\s)([a-f0-9]{40})($|\s)', content):
            obj = obj[1]
            objs.add(obj)

    # TODO: see .git/index

    if os.path.exists(os.path.join(directory, '.git', 'objects', 'info', 'packs')):
        printf('error: using .git/objects/info/packs is currently not implemented\n', file=sys.stderr)
        return 1

    if os.path.exists(os.path.join(directory, '.git', 'info', 'refs')):
        printf('error: using .git/info/refs is currently not implemented\n', file=sys.stderr)
        return 1

    # fetch all objects
    printf('[-] Fetching objects\n')
    process_tasks(objs,
                  FindObjectsWorker,
                  jobs,
                  args=(url, directory, retry, timeout))

    # git checkout
    printf('[-] Running git checkout .\n')
    os.chdir(directory)

    # ignore errors
    subprocess.call(['git', 'checkout', '.'], stderr=open(os.devnull, 'wb'))

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(usage='%(prog)s [options] URL DIR',
                                     description='Dump a git repository from a website.')
    parser.add_argument('url', metavar='URL',
                        help='url')
    parser.add_argument('directory', metavar='DIR',
                        help='output directory')
    parser.add_argument('--proxy',
                        help='use the specified proxy')
    parser.add_argument('-j', '--jobs', type=int, default=10,
                        help='number of simultaneous requests')
    parser.add_argument('-r', '--retry', type=int, default=3,
                        help='number of request attempts before giving up')
    parser.add_argument('-t', '--timeout', type=int, default=3,
                        help='maximum time in seconds before giving up')
    args = parser.parse_args()

    # jobs
    if args.jobs < 1:
        parser.error('invalid number of jobs')

    # retry
    if args.retry < 1:
        parser.error('invalid number of retries')

    # timeout
    if args.timeout < 1:
        parser.error('invalid timeout')

    # proxy
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

    # output directory
    if not os.path.exists(args.directory):
        os.makedirs(args.directory)

    if not os.path.isdir(args.directory):
        parser.error('%s is not a directory' % args.directory)

    if os.listdir(args.directory):
        parser.error('%s is not empty' % args.directory)

    # fetch everything
    sys.exit(fetch_git(args.url, args.directory, args.jobs, args.retry, args.timeout))
