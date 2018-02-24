#!/usr/bin/env python
from __future__ import print_function
import os
import stat
import sys
import hashlib
import getopt

read_blocksize = 16*1024

class file_info(object):
    def __init__(self, f):
        self.filename = f
        self.stat = os.stat(f)

    def size(self):
        return self.stat.st_size

    def regular_file(self):
        mode = self.stat[stat.ST_MODE]
        return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)

def sha1(filename):
    f = open(filename, 'rb')
    h = hashlib.sha1()
    block = f.read(read_blocksize)
    while block:
        h.update(block)
        block = f.read(read_blocksize)
    return h.digest()

def fast_hash(filename):
    f = open(filename, 'rb')
    h = hashlib.md5()
    block = f.read(read_blocksize)
    h.update(block)
    return h.digest()

def group_by_size():
    by_size = {}
    for fname in sys.stdin.readlines():
        fname = fname[:-1] #discard newline
        try:
            info = file_info(fname)
        except OSError:
            sys.stderr.write("Could not stat " + fname + " skipping...\n")
            continue
        if not info.regular_file():
            continue
        size = info.size()
        if size in by_size:
            by_size[size].append(info)
        else:
            by_size[size] = [info]
    return [item for item in by_size.values() if len(item) > 1 ]

def group_by_inode(files):
    by_inode = {}
    for f in files:
        inode = f.stat.st_ino
        if inode in by_inode:
            by_inode[inode].append(f)
        else:
            by_inode[inode] = [f]
    return by_inode
    
def group_by_hash(files, hash_function):
    by_inode = group_by_inode(files)
    if len(by_inode) <= 1:
        return [files] if len(files)>1 else []

    by_hash = {}
    for inode in by_inode:
        try:
            h = hash_function(by_inode[inode][0].filename)
        except IOError:
            sys.stderr.write("Could not get hash for " +
                             by_inode[inode][0].filename + " skipping...\n")
            continue
        if h in by_hash:
            by_hash[h] = by_hash[h] + by_inode[inode]
        else:
            by_hash[h] = by_inode[inode]
    
    return [files for files in by_hash.values() if len(files) > 1]

def group_identical(files):
    return group_by_hash(files, sha1)

def listing_print(l):
    print('')
    for i in l:
        print("{} {} {}".format(i.stat.st_nlink, i.stat.st_ino, i.filename))
    print('')

def hardlink(src, dest):
    if src.stat.st_dev != dest.stat.st_dev:
        print("{} and {} are not on the same device"\
            .format(src.filename, dest.filename), file=sys.stderr)
        return False

    try:
        backup = dest.filename + ".bak"
        os.rename(dest.filename, backup)
        print("linking...\n{} to \n{}".format(src.filename, dest.filename))
        os.link(src.filename, dest.filename)
        os.unlink(backup)
    except Exception as ex:
        print(ex, file=sys.stderr)
        return False
    return True

def make_hardlinks(files):
    # group by inode
    by_inode = {}
    best_inode = None
    nlink_max = 0
    for f in files:
        inode = f.stat.st_ino
        if f.stat.st_nlink >= nlink_max:
            nlink_max = f.stat.st_nlink
            best_inode = inode
        if inode in by_inode:
            by_inode[inode].append(f)
        else:
            by_inode[inode] = [f]
    # If there are no files or all files are hardlinked with eachother...
    if len(by_inode) <= 1:
        return

    master = by_inode[best_inode][0]
    for inode in by_inode:
        if inode == best_inode:
            continue
        for f in by_inode[inode]:
            if not hardlink(master, f):
                print("Could not hardlink {} to {} ...skipping"\
                      .format(master.filename, f.filename), file=sys.stderr)


def system(cmd, params):
    ex = cmd.split()[0]
    status = os.spawnvp(os.P_WAIT, ex, cmd.split()+params)
    if (status == 127):
        raise ChildProcessError("Could not execute: " + ex, file=sys.stderr)
    return status

def print_help():
    print('Usage: dupes [--exec command | --hardlink]', file=sys.stderr)
    

#parse parameters
try:
    optlist, args = getopt.getopt(sys.argv[1:], '', ['exec=', 'hardlink'])
    if args:
        raise RuntimeError(str(args))
except:
    print_help()
    sys.exit(1)

#setup action on duplicates
action = listing_print
if optlist and optlist[0][0] == '--hardlink':
    action = make_hardlinks 
elif optlist:
    cmd = optlist[0][1]
    action = lambda params: system(cmd, params)

for same_size in group_by_size():
    for same_fhash in group_by_hash(same_size, fast_hash):
        for identical in group_identical(same_fhash):
            # Don't do anything for lonely files
            if len(identical) <= 1:
                continue

            action(identical)

