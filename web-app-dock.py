#!/usr/bin/env python
# -*- coding: utf-8 -*-
# dockerapp • Deploy and manage web applications as docker containers
# Copyright ©2014 Christopher League <league@contrapunctus.net>

from contextlib import closing
from datetime import datetime
import argparse
import errno
import httplib
import json
import math
import os
import re
import shelve
import subprocess
import sys
import time
import doctest

ABBREV_COMMIT = 5
ABBREV_ID = 12
APT_DEPENDS = ['git', 'nginx', 'make', 'gcc']
APT_INSTALL = 'apt-get install -y'
CONTAINER_DB = os.path.join(os.environ['HOME'], '.dockerapp.db')
DOCKERFILE = 'Dockerfile'
ETC_NGINX = '/etc/nginx'
GIT_HOOK = os.path.join('hooks', 'pre-receive')
HTTP_PATH = '/ping'
HTTP_PORT = 'HTTP_PORT'
NUM_TRIES = 5
REF_MASTER = 'refs/heads/master'
RE_LABEL_COMMIT = re.compile(r'^(.*?)(-([0-9a-fA-F]+))?$')
RE_PORT = re.compile(r'^([0-9]+)/tcp')
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SITES_AVAILABLE = os.path.join(ETC_NGINX, 'sites-available')
SITES_AVAIL_REL = os.path.join('..', 'sites-available')
SITES_ENABLED = os.path.join(ETC_NGINX, 'sites-enabled')
UNUSABLE_PORTS = [22, 25]

opts = None


### Main program and argument parsing

def main():
    global opts
    if sys.argv[0].endswith('receive'):
        opts = argparse.Namespace()
        opts.dry_run = False
        opts.verbose = True
        opts.directory = None
        opts.func = receive_cmd
    else:
        opts = main_args.parse_args()
        if opts.dry_run:
            opts.verbose = True
        if opts.directory:
            announce('cd ' + opts.directory)
            os.chdir(opts.directory)
    opts.func()

def make_cmd_parser(name, **kwargs):
    "Create parser for sub-command, using its doc string for help text"
    f = globals()[name + '_cmd']
    if 'notes' in kwargs:
        kwargs['epilog'] = format_footnotes(kwargs['notes'])
        del kwargs['notes']
    args = subparse.add_parser(
        name, help=f.__doc__, description=f.__doc__,
        parents=[common_args], **kwargs
    )
    args.set_defaults(func=f)
    return args

def format_footnotes(keys):
    notes = []
    for k in keys:
        notes.append(u'  %c %s' % (k, footnotes[k]))
    return '\n'.join(notes).encode('utf-8')

def hex_arg(value):
    '''Raise ArgumentTypeError unless VALUE is a hexadecimal string.

    >>> hex_arg('babe')
    'babe'
    >>> hex_arg('cafeq')
    Traceback (most recent call last):
    ArgumentTypeError: must be a hexadecimal string
    >>> hex_arg('qcafe')
    Traceback (most recent call last):
    ArgumentTypeError: must be a hexadecimal string
    >>> hex_arg('189af')
    '189af'
    >>> hex_arg('')
    Traceback (most recent call last):
    ArgumentTypeError: must be a hexadecimal string
    '''
    try:
        int(value, 16)
    except ValueError:
        raise argparse.ArgumentTypeError('must be a hexadecimal string')
    return value

footnotes = {
    u'♯': 'requires root privilege',
    u'♮': 'can do more if given root privilege',
    u'♭': 'by default, parses current directory name as LABEL-COMMIT'
    }

main_args = argparse.ArgumentParser(
    description='deploy and manage web applications as docker containers',
    epilog=format_footnotes(u'♯♮')
    )
main_args.add_argument('-V', '--version', action='version',
                       version='%(prog)s 0.1')

subparse = main_args.add_subparsers(title='Commands')

common_args = argparse.ArgumentParser(add_help=False)
common_args.add_argument('-n', '--dry-run', action='store_true',
                         help='perform a trial run with no changes made')
common_args.add_argument('-v', '--verbose', action='store_true',
                         help='increase verbosity about what is happening')
common_args.add_argument('-C', '--directory', metavar='DIR',
                         help='change to DIR before doing anything else')


### ‘config’ sub-command

def config_cmd():
    'ensure all dependencies are installed and ready♯'
    cmd = APT_INSTALL.split() + APT_DEPENDS
    dry_call(cmd)
    dry_call(['make'])

config_args = make_cmd_parser('config')


### ‘init’ sub-command

def init_cmd():
    'create bare repository, ready for git push'
    git_dir = opts.label + '.git'
    cmd = 'git init --bare'.split()
    cmd.append(git_dir)
    dry_call(cmd)
    hook = os.path.join(git_dir, GIT_HOOK)
    dry_guard('symlink '+hook, force_symlink,
              os.path.realpath(sys.argv[0]), hook)

init_args = make_cmd_parser('init')
init_args.add_argument('label', metavar='LABEL',
                       help='name to use for the project repository')


### ‘run’ sub-command

def run_cmd():
    'build a docker image and run in a new container'
    label, commit = label_commit_from_opts_or_cwd()
    tag = '%s:%s' % (label,commit)
    docker_build(os.getcwd(), tag)
    id = docker_run(tag)
    if opts.dry_run: return
    info = docker_inspect(id)
    port = opts.port or determine_port(info) or 80
    announce('Using port %d for HTTP' % port)
    with closing(shelve.open(CONTAINER_DB)) as db:
        db[id] = Container(id, label, commit, port).__dict__
    r = try_repeatedly(is_container_responding, id, port)
    if r:
        print id, info['Name']
        return id

run_args = make_cmd_parser('run', notes=u'♭')
run_args.add_argument('-l', '--label', metavar='LABEL',
                      help='name to use for this project♭')
run_args.add_argument('-c', '--commit', metavar='COMMIT', type=hex_arg,
                      help='commit ID for this version♭')
run_args.add_argument('-p', '--port', type=int, metavar='PORT',
                      help='port to use for HTTP connection')
run_args.add_argument('-e', '--ephemeral', action='store_true',
                      help='directory can be removed during clean')

def label_commit_from_opts_or_cwd():
    label, commit = label_commit_from(base_cwd())
    label = opts.label or label
    commit = opts.commit or commit
    if not commit:
        sys.exit('You must specify --commit, unless current directory is named as LABEL-COMMIT')
    announce('Using label=[%s] commit=[%s]' % (label, commit))
    return (label, commit)

def docker_build(dir, tag):
    ensure_dockerfile(os.getcwd())
    cmd = 'docker build -t'.split()
    cmd.append(tag)
    cmd.append('.')
    err = dry_call(cmd)
    if err and not opts.dry_run:
        exit(err)

def ensure_dockerfile(dir):
    '''Die unless there is a Dockerfile.
In the future, this can be used to generate Dockerfile from a Makefile or
similar.'''
    p = os.path.join(dir, DOCKERFILE)
    if not os.path.isfile(p):
        sys.exit('No %s found in %s' % (DOCKERFILE, dir))

def docker_run(tag):
    cmd = 'docker run -d'.split()
    cmd.append(tag)
    container = dry_call(cmd, call=subprocess.check_output)
    if container:
        container = container.rstrip()
    elif not opts.dry_run:
        exit(1)
    return container

def determine_port(info):
    '''Determine HTTP port from container environment or exposed port list.

    >>> i = {'Config':{'Env':['HTTP_PORT=9134']},
    ...      'NetworkSettings':{'Ports':{'22/tcp':True,'9415/tcp':True}}}
    >>> determine_port(i)
    9134
    >>> i = {'Config':{'Env':['HTTP_PORTS=9134']},
    ...      'NetworkSettings':{'Ports':{'22/tcp':True,'9415/tcp':True}}}
    >>> determine_port(i)
    9415
    >>> i = {'Config':{'Env':['SECRET=frobnozz']},
    ...      'NetworkSettings':{'Ports':{'22/tcp':True}}}
    >>> determine_port(i)
    '''
    try:
        return int(env_list_lookup(info['Config']['Env'], HTTP_PORT))
    except ValueError:
        sys.exit("Container environment %s must be an integer" % HTTP_PORT)
    except KeyError:
        for tcp in info['NetworkSettings']['Ports']:
            m = RE_PORT.match(tcp)
            if m:
                p = int(m.group(1))
                if p not in UNUSABLE_PORTS:
                    return p


### ‘deploy’ sub-command

def deploy_cmd():
    'expose a running container as a host site♯'
    if opts.revert:
        sys.exit('--revert not supported yet')
    elif opts.container:
        container, d = lookup_by_container_prefix(opts.container)
    else:
        container, d = lookup_by_label_commit(opts.project or
                                              os.path.basename(os.getcwd()))
    if os.geteuid() != 0:
        announce('Warning: ' + footnotes[u'♯'])
    now = datetime.now()
    info = docker_inspect(container)
    filename = '%s-%s-%s-g%s-k%s' % \
               (d['label'],
                datetime.strftime(now, '%Y%m%d'),
                datetime.strftime(now, '%H%M'),
                d['commit'],
                container[:ABBREV_ID])
    avail = os.path.join(SITES_AVAILABLE, filename)
    announce('Creating ' + avail)
    with closing(shelve.open(CONTAINER_DB)) as db:
        with open(avail, 'w') as outfile:
            url = 'http://%s:%d' % (info['NetworkSettings']['IPAddress'],
                                    db[container]['port'])
            outfile.write(NGINX_PROXY % url)
    avail_rel = os.path.join(SITES_AVAIL_REL, filename)
    enabled = os.path.join(SITES_ENABLED, filename)
    for f in os.listdir(SITES_ENABLED):
        if f.startswith(d['label']):
            announce('Removing ' + f)
            os.unlink(os.path.join(SITES_ENABLED, f))
    announce('Linking ' + enabled)
    os.symlink(avail_rel, enabled)
    dry_call(['service', 'nginx', 'reload'])

NGINX_PROXY = '''
server {
  listen 80 default_server;
  listen [::]:80 default_server ipv6only=on;
  server_name localhost;
  location / {
    proxy_pass       %s;
    proxy_set_header Host      $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
'''

deploy_args = make_cmd_parser('deploy')
deploy_args.add_argument(
    '-r', '--revert', metavar='N', type=int, nargs='?', const=1,
    help='revert to Nth previous deploy of this project'
)
deploy_args.add_argument(
    '-c', '--container', metavar='ID', type=hex_arg,
    help='revert to this container ID'
)
deploy_args.add_argument(
    '-p', '--project', metavar='LABEL-COMMIT',
    help='revert to given COMMIT of project LABEL'
)


### Pre- or post-receive hook

def receive_cmd():
    'deploy a project in response to git push'
    c = git_master_commit()
    if not c:
        print 'No update to', REF_MASTER
        sys.exit(0)
    label, ext = os.path.splitext(os.path.basename(os.getcwd()))
    commit = c[:ABBREV_COMMIT]
    workdir = os.path.join(os.environ['HOME'], '%s-%s' % (label, commit))
    announce('Checking out %s' % workdir)
    if not os.path.isdir(workdir): os.mkdir(workdir)
    dry_call('git archive "%s" | tar -x -C "%s"' % (commit, workdir),
             shell=True)
    os.chdir(workdir)
    opts.label, opts.commit, opts.port = None, None, None
    opts.ephemeral = True
    opts.container = run_cmd()
    if not opts.container: sys.exit(1)
    dry_call([os.path.join(SCRIPT_DIR, 'sudo-deploy'), opts.container])

def git_master_commit():
    '''Parse the standard input for a git receive hook.
Answer the commit hash for an update to master, if any.'''
    # For each ref updated: <old-value> SP <new-value> SP <ref-name> LF
    for line in sys.stdin:
        old, new, ref = line.split()
        if ref == REF_MASTER:
            return new


### ‘clean’ sub-command

def clean_cmd():
    'stop and remove old containers and images♮'
    print opts

clean_args = make_cmd_parser('clean')


### ‘list’ sub-command

def list_cmd():
    'show details about previous builds and deployments'
    with closing(shelve.open(CONTAINER_DB)) as db:
        entries = list(db.iteritems())
    print ' RUNNING'
    print '/ AVAILABLE'
    print '|/ ENABLED'
    print '||/ PROJECT-COMMIT           CONTAINER    CREATED'
    avails = os.listdir(SITES_AVAILABLE)
    enableds = os.listdir(SITES_ENABLED)
    for k,v in sorted(entries, key=lambda kv: (kv[1]['label'], kv[1]['created'])):
        label = v['label']
        commit = v['commit']
        info = docker_inspect(k)
        run = 'R' if info['State']['Running'] else ' '
        prefix = k[:ABBREV_ID]
        kre = re.compile('-k%s$' % prefix)
        avail = 'A' if list_contains_match(avails, kre) else ' '
        enabled = 'E' if list_contains_match(enableds, kre) else ' '
        #ip = info['NetworkSettings']['IPAddress']
        #if ip:
        #    ip = '%s:%s' % (ip, v['port'])
        name = info['Name']
        created = reltime(v['created'])
        print '%c%c%c %-24s %s %s' % \
            (run, avail, enabled, label+'-'+commit, prefix, created)

list_args = make_cmd_parser('list')


### ‘test’ sub-command

def test_cmd():
    'run test cases'
    if not opts.verbose:
        print 'Running test cases...'
    doctest.testmod(verbose=opts.verbose)

test_args = make_cmd_parser('test')


### Persistent container and deployment info

class Container(object):
    def __init__(self, id=None, label=None, commit=None, port=None):
        assert id
        assert label
        assert commit
        assert port
        self.id = id
        self.label = label
        self.commit = commit
        self.port = port
        self.dir = os.getcwd()
        self.ephemeral = opts.ephemeral
        self.created = datetime.now()


### Utility functions

def list_contains_match(xs, regex):
    '''Answer True if list XS contains a string matching REGEX.

    >>> r = re.compile(r'fo?o$')
    >>> list_contains_match(['goo'], r)
    False
    >>> list_contains_match(['goofo'], r)
    True
    >>> list_contains_match(['goofoo'], r)
    True
    >>> list_contains_match(['foofa'], r)
    False
    '''
    for x in xs:
        if regex.search(x):
            return True
    return False

def lookup_by_label_commit(tag):
    label, commit = label_commit_from(tag)
    if not commit:
        sys.exit('You must specify commit using --project, or use --container or --revert')
    container = None
    with closing(shelve.open(CONTAINER_DB)) as db:
        candidates = []
        for k in db:
            d = db[k]
            if d['label'] == label and d['commit'] == commit:
                candidates.append(k)
        if len(candidates) == 1:
            return (candidates[0], db[candidates[0]])
        elif len(candidates) > 1:
            sys.exit('The tag "%s-%s" is ambiguous, could be one of:\n%s' %
                     (label, commit, '\n'.join(candidates)))
        else:
            sys.exit('No containers matched "%s-%s"' % (label, commit))

def lookup_by_container_prefix(prefix):
    with closing(shelve.open(CONTAINER_DB)) as db:
        try:
            return (prefix, db[prefix])
        except KeyError:
            candidates = []
            for k in db:
                if k.startswith(prefix):
                    candidates.append(k)
            if len(candidates) == 1:
                return (candidates[0], db[candidates[0]])
            elif len(candidates) > 1:
                sys.exit('The container prefix "%s" is ambiguous, could be one of:\n%s' %
                         (prefix, '\n'.join(candidates)))
            else:
                sys.exit('No containers matched "%s"' % opts.container)

def env_list_lookup(env_list, key):
    '''In a list of strings of the form 'KEY=VALUE', look for KEY.

    >>> env_list_lookup(['FOO=3', 'BAR=9'], 'FOO')
    '3'
    >>> env_list_lookup(['FOO=3', 'BAR=9'], 'BAR')
    '9'
    >>> env_list_lookup(['FOO=3', 'BAR=9'], 'BAZ')
    Traceback (most recent call last):
    KeyError: 'BAZ'
    '''
    for binding in env_list:
        if binding.startswith(key+'='):
            return binding[len(key)+1:]
    raise KeyError(key)

def try_repeatedly(func, *args, **kwargs):
    '''Call FUNC repeatedly, delaying between, until it returns something.

    >>> x = 0
    >>> def f():
    ...     'do something'
    ...     global x
    ...     x += 1
    ...     if x >= 2: return x
    >>> try_repeatedly(f)
    • do something
      waiting 1 second
    • do something
    • 2
    2
    '''
    tries_left = NUM_TRIES
    interval = 1
    while tries_left > 0:
        print '•', func.__doc__
        try:
            result = func(*args, **kwargs)
            if result is not None:
                print '•', result
                return result
        except SystemExit as e:
            raise e
        except BaseException as e:
            print ' ', e
        print '  waiting %d second%s' % (interval, '' if interval==1 else 's')
        time.sleep(interval)
        interval *= 2
        tries_left -= 1
    print '• giving up, sorry'

def docker_inspect(container_id):
    buf = subprocess.check_output(['docker', 'inspect', container_id])
    return json.loads(buf)[0]

def is_container_responding(container_id, port):
    'Check for HTTP response from container'
    info = docker_inspect(container_id)
    if not info['State']['Running']:
        sys.exit("Container no longer running")
    ip = info['NetworkSettings']['IPAddress']
    if ip:
        return ensure_http_ok(ip, port, HTTP_PATH)

def ensure_http_ok(host, port, path):
    '''Ensure that an HTTP GET to HOST:PORT using PATH succeeds with 200 OK.
    Note: PATH should begin with a slash.

    >>> ensure_http_ok('localhost', 9193, '')
    Traceback (most recent call last):
    AssertionError
    >>> ensure_http_ok('localhost', 9193, '/')
    Traceback (most recent call last):
    error: [Errno 111] Connection refused
    >>> from SimpleHTTPServer import SimpleHTTPRequestHandler
    >>> from SocketServer import TCPServer
    >>> from threading import Thread
    >>> d = TCPServer(('', 9194), SimpleHTTPRequestHandler)
    >>> t = Thread(target=d.serve_forever)
    >>> t.daemon = True
    >>> t.start()
    >>> ensure_http_ok('localhost', 9194, '/')
    True
    >>> ensure_http_ok('localhost', 9194, '/abcq')
    False
    >>> d.shutdown()
    '''
    assert path.startswith('/')
    announce('GET http://%s:%d%s' % (host, port, path))
    h = httplib.HTTPConnection(host, port, timeout=10)
    h.request('GET', path)
    r = h.getresponse()
    announce(' → %s %s' % (r.status, r.reason))
    return r.status == httplib.OK

def base_cwd():
    '''Return base name of current directory.

    >>> os.chdir('/usr/share')
    >>> base_cwd()
    'share'
    '''
    return os.path.basename(os.getcwd())

def label_commit_from(name):
    '''Separate a name like myproject-1f324 into a label, commit pair.

    >>> label_commit_from('myproject-1f324')
    ('myproject', '1f324')
    >>> label_commit_from('my-little-app-cf19')
    ('my-little-app', 'cf19')
    >>> label_commit_from('my-little-app')
    ('my-little-app', None)
    >>> label_commit_from('deceiving-commit-1f2q8')
    ('deceiving-commit-1f2q8', None)
    '''
    m = RE_LABEL_COMMIT.match(name)
    return (m.group(1), m.group(3))

def dry_call(cmd, call=subprocess.check_call, **kwargs):
    '''Run the list CMD using subprocess function CALL.

    >>> opts.dry_run, opts.verbose = True, True
    >>> dry_call(['ab2938742', 'arg293', '-v'])
    » ab2938742 arg293 -v
    >>> dry_call('echo hello', shell=True)
    » echo hello
    >>> opts.dry_run, opts.verbose = False, False
    >>> dry_call(['ab2938742'])
    Traceback (most recent call last):
    OSError: [Errno 2] No such file or directory
    >>> dry_call(['echo', 'hell0'], call=subprocess.check_output)
    'hell0\\n'
    '''
    mesg = ' '.join(cmd) if type(cmd) == list else cmd
    return dry_guard(mesg, call, cmd, **kwargs)

def dry_guard(mesg, f, *args, **kwargs):
    '''If a dry run, announce MESG; otherwise call F.

    >>> def f(): raise ValueError
    >>> opts.dry_run, opts.verbose = True, True
    >>> dry_guard("Don't do this", f)
    » Don't do this
    >>> opts.dry_run, opts.verbose = False, False
    >>> dry_guard("Please do this", f)
    Traceback (most recent call last):
    ValueError
    '''
    announce(mesg)
    if not opts.dry_run:
        return f(*args, **kwargs)

def announce(mesg):
    if opts.verbose:
        print '»', mesg
        sys.stdout.flush()

def force_symlink(file1, file2):
    'Simulate `ln -sf`, replacing `file2` if it exists already.'
    try:
        os.symlink(file1, file2)
    except OSError, e:
        if e.errno == errno.EEXIST:
            os.remove(file2)
            os.symlink(file1, file2)

# From https://gist.github.com/deontologician/3503910
# and https://coderwall.com/p/vnkxfg
def reltime(date, compare_to=None, at='@'):
    r'''Takes a datetime and returns a relative representation of the
    time.
    :param date: The date to render relatively
    :param compare_to: what to compare the date to. Defaults to datetime.now()
    :param at: date/time separator. defaults to "@". "at" is also reasonable.

    >>> from datetime import datetime, timedelta
    >>> today = datetime(2050, 9, 2, 15, 00)
    >>> earlier = datetime(2050, 9, 2, 12)
    >>> reltime(earlier, today)
    'today @ 12:00'
    >>> yesterday = today - timedelta(1)
    >>> reltime(yesterday, compare_to=today)
    'yesterday @ 15:00'
    >>> reltime(datetime(2050, 9, 1, 15, 32), today)
    'yesterday @ 15:32'
    >>> reltime(datetime(2050, 8, 31, 16), today)
    'Wednesday @ 16:00 (2 days ago)'
    >>> reltime(datetime(2050, 8, 26, 14), today)
    'last Friday @ 14:00 (7 days ago)'
    >>> reltime(datetime(2049, 9, 2, 12, 00), today)
    'September 2nd, 2049 @ 12:00 (last year)'
    >>> today = datetime(2012, 8, 29, 13, 52)
    >>> last_mon = datetime(2012, 8, 20, 15, 40, 55)
    >>> reltime(last_mon, today)
    'last Monday @ 15:40 (9 days ago)'
    '''
    def ordinal(n):
        r'''Returns a string ordinal representation of a number
        Taken from: http://stackoverflow.com/a/739301/180718
        '''
        if 10 <= n % 100 < 20:
            return str(n) + 'th'
        else:
            return str(n) + {1 : 'st', 2 : 'nd', 3 : 'rd'}.get(n % 10, "th")

    compare_to = compare_to or datetime.now()
    if date > compare_to:
        return NotImplementedError('reltime only handles dates in the past')
    #get timediff values
    diff = compare_to - date
    if diff.seconds < 60 * 60 * 8: #less than a business day?
        days_ago = diff.days
    else:
        days_ago = diff.days + 1
    months_ago = compare_to.month - date.month
    years_ago = compare_to.year - date.year
    weeks_ago = int(math.ceil(days_ago / 7.0))
    hr = date.strftime('%H')
    wd = compare_to.weekday()
    time = date.strftime('%H:%M')
    #calculate the date string
    if days_ago == 0:
        datestr = 'today {at} {time}'
    elif days_ago == 1:
        datestr = 'yesterday {at} {time}'
    elif (wd in (5, 6) and days_ago in (wd+1, wd+2)) or \
            wd + 3 <= days_ago <= wd + 8:
        #this was determined by making a table of wd versus days_ago and
        #divining a relationship based on everyday speech. This is somewhat
        #subjective I guess!
        datestr = 'last {weekday} {at} {time} ({days_ago} days ago)'
    elif days_ago <= wd + 2:
        datestr = '{weekday} {at} {time} ({days_ago} days ago)'
    elif years_ago == 1:
        datestr = '{month} {day}, {year} {at} {time} (last year)'
    elif years_ago > 1:
        datestr = '{month} {day}, {year} {at} {time} ({years_ago} years ago)'
    elif months_ago == 1:
        datestr = '{month} {day} {at} {time} (last month)'
    elif months_ago > 1:
        datestr = '{month} {day} {at} {time} ({months_ago} months ago)'
    else:
        #not last week, but not last month either
        datestr = '{month} {day} {at} {time} ({days_ago} days ago)'
    return datestr.format(time=time,
                          weekday=date.strftime('%A'),
                          day=ordinal(date.day),
                          days=diff.days,
                          days_ago=days_ago,
                          month=date.strftime('%B'),
                          years_ago=years_ago,
                          months_ago=months_ago,
                          weeks_ago=weeks_ago,
                          year=date.year,
                          at=at)


if __name__ == '__main__': main()
