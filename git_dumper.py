#!/usr/bin/env python3
from contextlib import closing
import argparse
import multiprocessing
import os
import os.path
import re
import socket
import subprocess
import sys
import traceback
import urllib.parse
import urllib3
import bs4
import dulwich.index
import dulwich.objects
import dulwich.pack
import requests
import socks
from dataclasses import dataclass
from requests_pkcs12 import Pkcs12Adapter




class GitDumper:

    def __init__(self):
        self.args: Arguments = None
        self.session: requests.Session = None
        self.response: requests.Response = None
        self.environment: dict[str, str] = None


    
    def execute(self):
        self._get_args()
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._valid_args()
        self._create_session()
        self._find_base_url()
        self._try_to_connect()
        self._valid_response()
        self._setup_env_for_proxy()
        self._try_fast_dump()    # if successful, it stops here
        self._fetch_common_files()
        self._discover_references()
        self._fetch_git_packs()
        self._discover_and_fetch_objects()
        self._finalize_checkout()



    def _get_args(self):
        parser = Parser()
        parser.parse()
        self.args = parser.get_args()


    
    def _valid_args(self):
        assert os.path.isdir(self.args.directory), "%s is not a directory" % self.args.directory
        assert self.args.jobs >= 1, "invalid number of jobs"
        assert self.args.retry >= 1, "invalid number of retries"
        assert self.args.timeout >= 1, "invalid timeout"


    
    def _create_session(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers = self.args.http_headers
        self._configure_session()

        if os.listdir(self.args.directory):
            printf("Warning: Destination '%s' is not empty\n", self.args.directory)



    def _configure_session(self):
        if self.args.client_cert_p12:
            self.session.mount(
                self.args.url, 
                Pkcs12Adapter(
                    pkcs12_filename=self.args.client_cert_p12, 
                    pkcs12_password=self.args.client_cert_p12_password,
                    max_retries=self.args.retry,
                )
            )
        else:        
            self.session.mount(self.args.url, requests.adapters.HTTPAdapter(max_retries=self.args.retry))



    def _find_base_url(self):
        url: str = self.args.url

        url = url.rstrip("/")
        if url.endswith("HEAD"):
            url = url[:-4]
        
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        
        self.args.url = url.rstrip("/")

    

    def _try_to_connect(self):
        printf("[!] Force flag used. Ignoring non fatal errors...\n")

        try:
            printf("[#] Testing %s/.git/HEAD ", self.args.url)
            self.response = self.session.get(
                "%s/.git/HEAD" % self.args.url,
                timeout = self.args.timeout,
                allow_redirects = False
            )
        except Exception as e:
            printf("\nerror: Unable to connect to %s. Error: %s\n", self.args.url, e)
            sys.exit(1)

        printf("[%d]\n", self.response.status_code)



    def _valid_response(self):
        valid, error_message = verify_response(self.response)

        if self.args.force:
            return
        
        if not valid:
            printf(error_message, self.args.url, "/.git/HEAD", file=sys.stderr)
            sys.exit(1)
        
        if not re.match(r"^(ref:.*|[0-9a-f]{40}$)", self.response.text.strip()):
            printf(
                "error: %s/.git/HEAD is not a git HEAD file\n",
                self.args.url,
                file=sys.stderr,
            )
            sys.exit(1)



    def _setup_env_for_proxy(self):
        self.environment = os.environ.copy()
        configured_proxy = socks.getdefaultproxy()

        if configured_proxy is None:
            return
        
        proxy_types = ["http", "socks4h", "socks5h"]
        self.environment["ALL_PROXY"] = f"http.proxy={proxy_types[configured_proxy[0]]}://{configured_proxy[1]}:{configured_proxy[2]}"



    def _try_fast_dump(self):
        printf("[#] Testing %s/.git/ ", self.args.url)
        response = self.session.get("%s/.git/" % self.args.url, allow_redirects=False)
        printf("[%d]\n", response.status_code)

        if (
            response.status_code == 200
            and is_html(response)
            and "HEAD" in get_indexed_files(response)
        ):
            printf("[#] Fetching .git recursively\n")
            process_tasks(
                [".git/", ".gitignore"],
                RecursiveDownloadWorker,
                self.args.jobs,
                args=(
                    self.args.url, self.args.directory, self.args.retry, self.args.timeout, 
                    self.args.http_headers, self.args.force
                ),
            )

            os.chdir(self.args.directory)

            printf("[-] Sanitizing .git/config\n")
            self.sanitize_file()

            printf("[-] Running git checkout .\n")
            subprocess.check_call(["git", "checkout", "."], env=self.environment)
            
            sys.exit(0)
    


    def sanitize_file(self, filepath=".git/config"):
        """ Inplace comment out possibly unsafe lines based on regex """
        if not os.path.isfile(filepath):
            return

        UNSAFE=r"^\s*fsmonitor|sshcommand|askpass|editor|pager"

        with open(filepath, 'r+') as f:
            content = f.read()
            modified_content = re.sub(UNSAFE, r'# \g<0>', content, flags=re.IGNORECASE)
            if content != modified_content:
                printf("Warning: '%s' file was altered\n" % filepath)
                f.seek(0)
                f.write(modified_content)



    def _fetch_common_files(self):
        printf("[#] Fetching common files\n")

        TASKS = [
            ".gitignore",
            ".git/COMMIT_EDITMSG",
            ".git/description",
            ".git/hooks/applypatch-msg.sample",
            ".git/hooks/commit-msg.sample",
            ".git/hooks/post-commit.sample",
            ".git/hooks/post-receive.sample",
            ".git/hooks/post-update.sample",
            ".git/hooks/pre-applypatch.sample",
            ".git/hooks/pre-commit.sample",
            ".git/hooks/pre-push.sample",
            ".git/hooks/pre-rebase.sample",
            ".git/hooks/pre-receive.sample",
            ".git/hooks/prepare-commit-msg.sample",
            ".git/hooks/update.sample",
            ".git/index",
            ".git/info/exclude",
            ".git/objects/info/packs",
        ]

        process_tasks(
            TASKS,
            DownloadWorker,
            self.args.jobs,
            args=(
                self.args.url, self.args.directory, self.args.retry, self.args.timeout, self.args.http_headers, 
                self.args.force, self.args.client_cert_p12, self.args.client_cert_p12_password,
            ),
        )


    
    def _discover_references(self):
        printf("[#] Finding refs/\n")

        TASKS = [
            ".git/FETCH_HEAD",
            ".git/HEAD",
            ".git/ORIG_HEAD",
            ".git/config",
            ".git/info/refs",
            ".git/logs/HEAD",
            ".git/logs/refs/heads/main",
            ".git/logs/refs/heads/master",
            ".git/logs/refs/heads/staging",
            ".git/logs/refs/heads/production",
            ".git/logs/refs/heads/development",
            ".git/logs/refs/remotes/origin/HEAD",
            ".git/logs/refs/remotes/origin/main",
            ".git/logs/refs/remotes/origin/master",
            ".git/logs/refs/remotes/origin/staging",
            ".git/logs/refs/remotes/origin/production",
            ".git/logs/refs/remotes/origin/development",
            ".git/logs/refs/stash",
            ".git/packed-refs",
            ".git/refs/heads/main",
            ".git/refs/heads/master",
            ".git/refs/heads/staging",
            ".git/refs/heads/production",
            ".git/refs/heads/development",
            ".git/refs/remotes/origin/HEAD",
            ".git/refs/remotes/origin/main",
            ".git/refs/remotes/origin/master",
            ".git/refs/remotes/origin/staging",
            ".git/refs/remotes/origin/production",
            ".git/refs/remotes/origin/development",
            ".git/refs/stash",
            ".git/refs/wip/wtree/refs/heads/main",
            ".git/refs/wip/wtree/refs/heads/master",
            ".git/refs/wip/wtree/refs/heads/staging",
            ".git/refs/wip/wtree/refs/heads/production",
            ".git/refs/wip/wtree/refs/heads/development",
            ".git/refs/wip/index/refs/heads/main",
            ".git/refs/wip/index/refs/heads/master",
            ".git/refs/wip/index/refs/heads/staging",
            ".git/refs/wip/index/refs/heads/production",
            ".git/refs/wip/index/refs/heads/development"
        ]

        self._add_user_specified_branches(TASKS)

        process_tasks(
            TASKS,
            FindRefsWorker,
            self.args.jobs,
            args=(
                self.args.url, self.args.directory, self.args.retry, self.args.timeout, self.args.http_headers, 
                self.args.force, self.args.client_cert_p12, self.args.client_cert_p12_password
            ),
        )


    
    def _add_user_specified_branches(self, tasks: list):
        if not self.args.branches:
            return
        
        for branch in self.args.branches:
            if not re.match(r'^[A-Za-z0-9\-\._]+$', branch):
                printf("Warning: ignoring invalid branch name '%s'\n", branch)
                continue
            
            tasks.extend([
                f".git/logs/refs/heads/{branch}",
                f".git/refs/heads/{branch}",
                f".git/logs/refs/remotes/origin/{branch}",
                f".git/refs/remotes/origin/{branch}",
                f".git/refs/wip/wtree/refs/heads/{branch}",
                f".git/refs/wip/index/refs/heads/{branch}",
            ])



    def _fetch_git_packs(self):
        printf("[-] Finding packs\n")
        tasks = []

        # use .git/objects/info/packs to find packs
        info_packs_path = os.path.join(
            self.args.directory, ".git", "objects", "info", "packs"
        )

        if os.path.exists(info_packs_path):
            with open(info_packs_path, "r") as f:
                info_packs = f.read()

            for sha1 in re.findall(r"pack-([a-f0-9]{40})\.pack", info_packs):
                tasks.append(".git/objects/pack/pack-%s.idx" % sha1)
                tasks.append(".git/objects/pack/pack-%s.pack" % sha1)

        process_tasks(
            tasks,
            DownloadWorker,
            self.args.jobs,
            args=(
                self.args.url, self.args.directory, self.args.retry, self.args.timeout, self.args.http_headers, 
                self.args.force, self.args.client_cert_p12, self.args.client_cert_p12_password
            ),
        )

    

    def _discover_and_fetch_objects(self):
        printf("[-] Finding objects\n")
        objs = set()
        packed_objs = set()

        # .git/packed-refs, .git/info/refs, .git/refs/*, .git/logs/*
        files = [
            os.path.join(self.args.directory, ".git", "packed-refs"),
            os.path.join(self.args.directory, ".git", "info", "refs"),
            os.path.join(self.args.directory, ".git", "FETCH_HEAD"),
            os.path.join(self.args.directory, ".git", "ORIG_HEAD"),
        ]

        self._collect_file_paths_from_git_subdir(files, "refs")
        self._collect_file_paths_from_git_subdir(files, "logs")
        self._extract_sha1_hashes_from_files(files, objs)
        self._parse_staging_area(objs)
        self._process_pack_files(packed_objs, objs)

        printf("[-] Fetching objects\n")
        process_tasks(
            objs,
            FindObjectsWorker,
            self.args.jobs,
            args=(
                self.args.url, self.args.directory, self.args.retry, self.args.timeout, self.args.http_headers, 
                self.args.force, self.args.client_cert_p12, self.args.client_cert_p12_password
            ),
            tasks_done=packed_objs,
        )

    

    def _collect_file_paths_from_git_subdir(self, files: list, subpath: str):
        base_path = os.path.join(self.args.directory, ".git", subpath)

        if not os.path.isdir(base_path):
            return

        for dirpath, _, filenames in os.walk(base_path):
            for filename in filenames:
                files.append(os.path.join(dirpath, filename))

    

    @staticmethod
    def _extract_sha1_hashes_from_files(files: list, objs: set):
        for filepath in files:
            if not os.path.isfile(filepath):  # race condition
                continue

            try:
                with open(filepath, "r", encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception:
                continue

            for match in re.findall(r"(^|\s)([a-f0-9]{40})($|\s)", content):
                objs.add(match[1])

    

    def _parse_staging_area(self, objs: set):
        index_path = os.path.join(self.args.directory, ".git", "index")

        if not os.path.exists(index_path):
            return

        try:
            index = dulwich.index.Index(index_path)
            for entry in index.iterobjects():
                objs.add(entry[1].decode())
        except Exception:
            pass



    def _process_pack_files(self, packed_objs: set, objs: set):
        pack_file_dir = os.path.join(self.args.directory, ".git", "objects", "pack")

        if not os.path.isdir(pack_file_dir):
            return

        for filename in os.listdir(pack_file_dir):
            if not filename.startswith("pack-") or not filename.endswith(".pack"):
                continue
            
            try:
                pack_data_path = os.path.join(pack_file_dir, filename)
                pack_idx_path = os.path.join(pack_file_dir, filename[:-5] + ".idx")
                pack_data = dulwich.pack.PackData(pack_data_path, ...)
                pack_idx = dulwich.pack.load_pack_index(pack_idx_path, ...)
                pack = dulwich.pack.Pack.from_objects(pack_data, pack_idx)
                for obj_file in pack.iterobjects():
                    packed_objs.add(obj_file.sha().hexdigest())
                    objs |= set(get_referenced_sha1(obj_file))
            except Exception:
                continue



    def _finalize_checkout(self):
        # git checkout
        printf("[-] Running git checkout .\n")
        os.chdir(self.args.directory)
        self.sanitize_file()

        # ignore errors
        subprocess.call(
            ["git", "checkout", "."],
            stderr=open(os.devnull, "wb"),
            env=self.environment
        )





@dataclass(slots=True)
class Arguments:
    url: str
    directory: str
    proxy: str
    client_cert_p12: str
    client_cert_p12_password: str
    jobs: int
    retry: int
    timeout: int
    http_headers: dict[str, str]
    branches: list[str]
    force: bool





class Parser:

    def __init__(self):
        self.args: argparse.Namespace = None
        self.parser: argparse.ArgumentParser = None

    
    
    def parse(self):
        self.create_args()
        self.args = self.parser.parse_args()
        self.valid_jobs()
        self.valid_retry()
        self.valid_timeout()
        self.valid_proxy()
        self.valid_certificate()
        self.create_dir()

    

    def create_args(self):
        self.parser = argparse.ArgumentParser(
            usage="git-dumper [options] URL DIR",
            description="Dump a git repository from a website.",
        )
        self.parser.add_argument("url", metavar="URL", help="URL")
        self.parser.add_argument("directory", metavar="DIR", help="Output directory")
        self.parser.add_argument("--proxy", help="Use the specified proxy")
        self.parser.add_argument("--client-cert-p12", help="Client certificate in PKCS#12")
        self.parser.add_argument("--client-cert-p12-password", help="Password for the client certificate")
        self.parser.add_argument(
            "-j", "--jobs", type=int, default=10,
            help="Number of simultaneous requests",
        )
        self.parser.add_argument(
            "-r", "--retry", type=int, default=3,
            help="Number of request attempts before giving up",
        )
        self.parser.add_argument(
            "-t", "--timeout", type=int, default=3,
            help="Maximum time in seconds before giving up",
        )
        self.parser.add_argument(
            "-u", "--user-agent", type=str,
            default="Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0",
            help="User-agent to use for requests",
        )
        self.parser.add_argument(
            "-H", "--header", type=str, action="append",
            help="Additional http headers, e.g `NAME=VALUE`",
        )
        self.parser.add_argument(
            "-b", "--branch", dest="branches", action="append",
            help="Additional branch names to check for, e.g. `-b dev -b prod`. The default branches (`main`, `master`, `staging`, `production`, `development`) are always checked.",
        )
        self.parser.add_argument(
            "-F", "--force", action="store_true",
            help="Ignores any non fatal error",
        )


    
    def valid_jobs(self):
        if self.args.jobs < 1:
            self.parser.error("invalid number of jobs, got `%d`" % self.args.jobs)



    def valid_retry(self):
        if self.args.retry < 1:
            self.parser.error("invalid number of retries, got `%d`" % self.args.retry)



    def valid_timeout(self):
        if self.args.timeout < 1:
            self.parser.error("invalid timeout, got `%d`" % self.args.timeout)



    def valid_proxy(self):
        if self.args.proxy:
            proxy_valid = False

            for pattern, proxy_type in [
                (r"^socks5:(.*):(\d+)$", socks.PROXY_TYPE_SOCKS5),
                (r"^socks4:(.*):(\d+)$", socks.PROXY_TYPE_SOCKS4),
                (r"^http://(.*):(\d+)$", socks.PROXY_TYPE_HTTP),
                (r"^(.*):(\d+)$", socks.PROXY_TYPE_SOCKS5),
            ]:
                m = re.match(pattern, self.args.proxy)
                if m:
                    socks.setdefaultproxy(proxy_type, m.group(1), int(m.group(2)))
                    socket.socket = socks.socksocket
                    proxy_valid = True
                    break

            if not proxy_valid:
                self.parser.error("invalid proxy, got `%s`" % self.args.proxy)

    

    def create_dir(self):
        if not os.path.exists(self.args.directory):
            os.makedirs(self.args.directory)

        if not os.path.isdir(self.args.directory):
            self.parser.error("`%s` is not a directory" % self.args.directory)



    def valid_certificate(self):
        if not self.args.client_cert_p12:
            return
        
        if not os.path.exists(self.args.client_cert_p12):
            self.parser.error(
                "client certificate `%s` does not exist" % self.args.client_cert_p12
            )

        if not os.path.isfile(self.args.client_cert_p12):
            self.parser.error(
                "client certificate `%s` is not a file" % self.args.client_cert_p12
            )

        if self.args.client_cert_p12_password is None:
            self.parser.error("client certificate password is required")



    def valid_headers(self) -> dict:
        http_headers = {"User-Agent": self.args.user_agent}
        
        if not self.args.header:
            return http_headers
        
        for header in self.args.header:
            tokens = header.split("=", maxsplit=1)
            
            if len(tokens) != 2:
                self.parser.error("http header must have the form NAME=VALUE, got `%s`" % header)
            
            name, value = tokens
            http_headers[name.strip()] = value.strip()
        
        return http_headers
    

    
    def get_args(self) -> Arguments:
        return Arguments(
            url = self.args.url,
            directory = self.args.directory,
            proxy = self.args.proxy,
            client_cert_p12 = self.args.client_cert_p12,
            client_cert_p12_password = self.args.client_cert_p12_password,
            jobs = self.args.jobs,
            retry = self.args.retry,
            timeout = self.args.timeout,
            http_headers = self.valid_headers(),
            branches = self.args.branches,
            force = self.args.force,
        )







def printf(fmt, *args, file=sys.stdout):
    if args:
        fmt = fmt % args

    file.write(fmt)
    file.flush()



def is_html(response: requests.Response):
    """ Return True if the response is a HTML webpage """
    return (
        "Content-Type" in response.headers
        and "text/html" in response.headers["Content-Type"]
    )



def is_safe_path(path: str):
    """ Prevent directory traversal attacks """
    if path.startswith("/"):
        return False

    safe_path = os.path.expanduser("~")
    return (
        os.path.commonpath(
            (os.path.realpath(os.path.join(safe_path, path)), safe_path)
        )
        == safe_path
    )



def get_indexed_files(response: requests.Response):
    """ Return all the files in the directory index webpage """
    html = bs4.BeautifulSoup(response.text, "html.parser")
    files = []

    for link in html.find_all("a"):
        url = urllib.parse.urlparse(link.get("href"))

        if (
            url.path
            and is_safe_path(url.path)
            and not url.scheme
            and not url.netloc
        ):
            files.append(url.path)

    return files




def verify_response(response: requests.Response):
    if response.status_code != 200:
        return (
            False,
            "[-] %s/%s responded with status code {code}\n".format(
                code=response.status_code
            ),
        )
    elif (
        "Content-Length" in response.headers
        and response.headers["Content-Length"] == 0
    ):
        return False, "[-] %s/%s responded with a zero-length body\n"
    elif (
        "Content-Type" in response.headers
        and "text/html" in response.headers["Content-Type"]
    ):
        return False, "[-] %s%s responded with HTML\n"
    else:
        return True, True




def create_intermediate_dirs(path: str):
    """ Create intermediate directories, if necessary """

    dirname, basename = os.path.split(path)

    if dirname and not os.path.exists(dirname):
        try:
            os.makedirs(dirname)
        except FileExistsError:
            pass  # race condition




def get_referenced_sha1(obj_file):
    """ Return all the referenced SHA1 in the given object file """
    objs = []

    if isinstance(obj_file, dulwich.objects.Commit):
        objs.append(obj_file.tree.decode())

        for parent in obj_file.parents:
            objs.append(parent.decode())

    elif isinstance(obj_file, dulwich.objects.Tree):
        for item in obj_file.iteritems():
            objs.append(item.sha.decode())
    
    elif isinstance(obj_file, dulwich.objects.Blob):
        pass
    elif isinstance(obj_file, dulwich.objects.Tag):
        pass
    else:
        printf(
            "error: unexpected object type: %r\n" % obj_file, file=sys.stderr
        )
        sys.exit(1)

    return objs



def process_tasks(initial_tasks, worker, jobs, args=(), tasks_done=None):
    """ Process tasks in parallel """

    if not initial_tasks:
        return

    tasks_seen = set(tasks_done) if tasks_done else set()
    pending_tasks = multiprocessing.Queue()
    tasks_done = multiprocessing.Queue()
    num_pending_tasks = 0

    # add all initial tasks in the queue
    for task in initial_tasks:
        assert task is not None

        if task not in tasks_seen:
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






class Worker(multiprocessing.Process):
    """ Worker for process_tasks """

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

            if task is None:  # end signal
                return

            try:
                result = self.do_task(task, *self.args)
            except Exception:
                printf("Task %s raised exception:\n", task, file=sys.stderr)
                traceback.print_exc()
                result = []

            assert isinstance(
                result, list
            ), "do_task() should return a list of tasks"

            self.tasks_done.put(result)


    def init(self, *args):
        raise NotImplementedError


    def do_task(self, task, *args):
        raise NotImplementedError





class DownloadWorker(Worker):
    """ Download a list of files """

    def init(self, url, directory, retry, timeout, http_headers, force, client_cert_p12=None, client_cert_p12_password=None):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers = http_headers

        if client_cert_p12:
            self.session.mount(url, Pkcs12Adapter(pkcs12_filename=client_cert_p12, pkcs12_password=client_cert_p12_password))
        else:
            self.session.mount(url, requests.adapters.HTTPAdapter(max_retries=retry))



    def do_task(self, filepath, url, directory, retry, timeout, http_headers, force, client_cert_p12=None, client_cert_p12_password=None):
        if os.path.isfile(os.path.join(directory, filepath)):
            printf("[-] Already downloaded %s/%s\n", url, filepath)
            return []

        with closing(
            self.session.get(
                "%s/%s" % (url, filepath),
                allow_redirects=False,
                stream=True,
                timeout=timeout,
            )
        ) as response:
            printf(
                "[-] Fetching %s/%s [%d]\n",
                url,
                filepath,
                response.status_code,
            )

            valid, error_message = verify_response(response)
            if not valid and force is not True:
                printf(error_message, url, filepath, file=sys.stderr)
                return []

            abspath = os.path.abspath(os.path.join(directory, filepath))
            create_intermediate_dirs(abspath)

            # write file
            with open(abspath, "wb") as f:
                for chunk in response.iter_content(4096):
                    f.write(chunk)

            return []





class RecursiveDownloadWorker(DownloadWorker):
    """ Download a directory recursively """

    def do_task(self, filepath, url, directory, retry, timeout, http_headers, force):
        if os.path.isfile(os.path.join(directory, filepath)):
            printf("[-] Already downloaded %s/%s\n", url, filepath)
            return []

        with closing(
            self.session.get(
                "%s/%s" % (url, filepath),
                allow_redirects=False,
                stream=True,
                timeout=timeout,
            )
        ) as response:
            printf(
                "[-] Fetching %s/%s [%d]\n",
                url,
                filepath,
                response.status_code,
            )

            if (
                response.status_code in (301, 302)
                and "Location" in response.headers
                and response.headers["Location"].endswith(filepath + "/")
            ):
                return [filepath + "/"]

            if filepath.endswith("/"):  # directory index
                assert is_html(response)

                return [
                    filepath + filename
                    for filename in get_indexed_files(response)
                ]
            else:  # file
                valid, error_message = verify_response(response)
                if not valid and force is not True:
                    printf(error_message, url, filepath, file=sys.stderr)
                    return []

                abspath = os.path.abspath(os.path.join(directory, filepath))
                create_intermediate_dirs(abspath)

                # write file
                with open(abspath, "wb") as f:
                    for chunk in response.iter_content(4096):
                        f.write(chunk)

                return []





class FindRefsWorker(DownloadWorker):
    """ Find refs/ """

    def do_task(self, filepath, url, directory, retry, timeout, http_headers, force, client_cert_p12=None, client_cert_p12_password=None):
        response = self.session.get(
            "%s/%s" % (url, filepath), allow_redirects=False, timeout=timeout
        )
        printf(
            "[-] Fetching %s/%s [%d]\n", url, filepath, response.status_code
        )

        valid, error_message = verify_response(response)
        if not valid and force is not True:
            printf(error_message, url, filepath, file=sys.stderr)
            return []

        abspath = os.path.abspath(os.path.join(directory, filepath))
        create_intermediate_dirs(abspath)

        # write file
        with open(abspath, "w") as f:
            f.write(response.text)

        # find refs
        tasks = []

        for ref in re.findall(
            r"(refs(/[a-zA-Z0-9\-\.\_\*]+)+)", response.text
        ):
            ref = ref[0]
            if not ref.endswith("*") and is_safe_path(ref):
                tasks.append(".git/%s" % ref)
                tasks.append(".git/logs/%s" % ref)

        return tasks





class FindObjectsWorker(DownloadWorker):
    """ Find objects """

    def do_task(self, obj, url, directory, retry, timeout, http_headers, force, client_cert_p12=None, client_cert_p12_password=None):
        filepath = ".git/objects/%s/%s" % (obj[:2], obj[2:])

        if os.path.isfile(os.path.join(directory, filepath)):
            printf("[-] Already downloaded %s/%s\n", url, filepath)
        else:
            response = self.session.get(
                "%s/%s" % (url, filepath),
                allow_redirects=False,
                timeout=timeout,
            )
            printf(
                "[-] Fetching %s/%s [%d]\n",
                url,
                filepath,
                response.status_code,
            )

            valid, error_message = verify_response(response)
            if not valid and force is not True:
                printf(error_message, url, filepath, file=sys.stderr)
                return []

            abspath = os.path.abspath(os.path.join(directory, filepath))
            create_intermediate_dirs(abspath)

            # write file
            with open(abspath, "wb") as f:
                f.write(response.content)

        abspath = os.path.abspath(os.path.join(directory, filepath))
        # parse object file to find other objects
        obj_file = dulwich.objects.ShaFile.from_path(abspath)
        return get_referenced_sha1(obj_file)





if __name__ == "__main__":
    git_dumper = GitDumper()
    git_dumper.execute()
    sys.exit(0)
