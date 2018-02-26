#!/usr/bin/env python
from __future__ import print_function
import os
import stat
import sys
import hashlib
import getopt

read_blocksize = 16*1024

fsencode = lambda x:x
fsdecode = lambda x:x
stream = sys.stdin

# Python 3 compatibility
if sys.version_info[0] >= 3:
    fsencode = os.fsencode
    fsdecode = os.fsdecode
    stream = sys.stdin.buffer

class FileInfo(object):
    "Filename and stat information "
    def __init__(self, f):
        self.filename = f
        self.stat = os.stat(f)

    def regular_file(self):
        mode = self.stat[stat.ST_MODE]
        return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)

    def strname(self):
        return fsdecode(self.filename)

def sha1(filename):
    "Comprehensive SHA1 hash of entire file"
    h = hashlib.sha1()
    with open(filename, 'rb') as f:
        block = f.read(read_blocksize)
        while block:
            h.update(block)
            block = f.read(read_blocksize)
    return h.digest()

def fast_hash(filename):
    "Quick MD5 hash of first block only"
    h = hashlib.md5()
    with open(filename, 'rb') as f:
        block = f.read(read_blocksize)
        h.update(block)
    return h.digest()

def stat_files(filenames):
    "Produce FileInfo for all non-empty files"
    for fname in filenames:
        try:
            info = FileInfo(fname)
        except OSError:
            sys.stderr.write("Could not stat " + fsdecode(fname) + " skipping...\n")
            continue
        if not info.regular_file() or info.stat.st_size == 0:
            continue
        yield info

def group_by(files, key):
    "Group files by key function"
    by_group = {}
    for f in files:
        by_group.setdefault(key(f), []).append(f)
    return by_group

    
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
                             by_inode[inode][0].strname() + " skipping...\n")
            continue
        if h in by_hash:
            by_hash[h] = by_hash[h] + by_inode[inode]
        else:
            by_hash[h] = by_inode[inode]
    
    return [files for files in by_hash.values() if len(files) > 1]

def listing_print(files):
    print('')
    for f in files:
        print("{} {} {}".format(f.stat.st_nlink, f.stat.st_ino, f.strname()) )
    print('')

def hardlink(src, dest):
    if src.stat.st_dev != dest.stat.st_dev:
        print("{} and {} are not on the same device"\
            .format(src.strname(), dest.strname()), file=sys.stderr)
        return False

    try:
        backup = dest.filename + fsencode(".bak")
        os.rename(dest.filename, backup)
        print("linking...\n{} to \n{}".format(src.strname(), dest.strname()))
        os.link(src.filename, dest.filename)
        os.unlink(backup)
    except Exception as ex:
        print(ex, file=sys.stderr)
        return False
    return True
    
def make_hardlinks(files):
    by_inode = group_by_inode(files)
    # If there are no files or all files are hardlinked with eachother...
    if len(by_inode) <= 1:
        return

    master = max(files, key=lambda f: f.stat.st_nlink)
    for inode in by_inode:
        if inode == master.stat.st_ino:
            continue
        for f in by_inode[inode]:
            if not hardlink(master, f):
                print("Could not hardlink {} to {} ...skipping"\
                      .format(master.strname(), f.strname()), file=sys.stderr)

def system(cmd, params):
    command = [fsencode(i) for i in cmd.split()]
    ex = command[0]
    status = os.spawnvp(os.P_WAIT, ex, command + [i.filename for i in params])
    if (status == 127):
        raise ChildProcessError("Could not execute: " + fsdecode(ex))
    return status

def group_by_size(files):
    return group_by(files, lambda f: f.stat.st_size).values()

def group_by_dev(files):
    return group_by(files, lambda f: f.stat.st_dev).values()

def group_by_inode(files):
    return group_by(files, lambda f: f.stat.st_ino)
    
def filter_solo(items_list):
    return (i for i in items_list if len(i) > 1)

def print_help():
    print('Usage: dupes [--exec command | --hardlink] [-0]', file=sys.stderr)
    
def read_filenames(stream, separator = b"\n"):
        buff = stream.read(read_blocksize)
        remain = b""
        while buff:
            tokens = (remain + buff).split(separator)
            remain = b""
            # Keep remainder bytes if needed...
            if len(tokens) and len(tokens[-1]):
                tokens, remain = tokens[:-1], tokens[-1]

            for tok in tokens:
                if tok: yield tok
            buff = stream.read(read_blocksize)
        if remain:
            yield remain

class Options(object):
    "Holds script options"
    def parse(self):
        "Initialize options from command line"
        try:
            optlist, args = getopt.getopt(sys.argv[1:], '0', ['exec=', 'hardlink', 'dry-run'])
            if args:
                raise RuntimeError(str(args))
        except:
            print_help()
            sys.exit(1)
        
        self.action = listing_print # Sction on duplicates
        self.separator = b'\n'      # Files separator
        self.dry_run = False        # Dry run only
        
        for opt in optlist:
            if opt[0] == '--hardlink':
                self.action = make_hardlinks
            if opt[0] == "--exec":
                self.action = lambda params: system(opt[1], params)
            if opt[0] == "--dry-run":
                self.dry_run = True
            if opt[0] == "-0":
                self.separator = b'\0'

def main():
    opts = Options()
    opts.parse()
    
    for same_size in filter_solo( group_by_size( stat_files(read_filenames(stream, opts.separator)) )):
        for same_fhash in filter_solo( group_by_hash(same_size, fast_hash)):
            for identical in filter_solo( group_by_hash(same_fhash, sha1)):
                opts.action(identical)

if __name__ == "__main__":
    main()
