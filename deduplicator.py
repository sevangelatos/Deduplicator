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
        read = lambda :f.read(read_blocksize)
        for block in iter(read, b''):
            h.update(block)
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
    by_dev_inode = group_by(files, lambda f: (f.stat.st_ino, f.stat.st_dev)).values()
    # If they're all the same inode, no need to calculate hashes at all.
    if len(by_dev_inode) <= 1:
        return [files]

    by_hash = {}
    for same_inode in by_dev_inode:
        try:
            h = hash_function(same_inode[0].filename)
            by_hash.setdefault(h, []).extend(same_inode)
        except IOError:
            sys.stderr.write("Could not get hash for " +
                             same_inode[0].strname() + " skipping...\n")

    return by_hash.values()

def listing_print(files):
    print('')
    for f in files:
        print("{} {} {}".format(f.stat.st_nlink, f.stat.st_ino, f.strname()) )
    print('')

def hardlink(src, dest, dry_run):
    "Make dest a hardlink to the src"
    assert src.stat.st_dev == dest.stat.st_dev
    print("linking...\n{} to \n{}".format(src.strname(), dest.strname()))
    if not dry_run:
        backup = dest.filename + fsencode(".bak")
        os.rename(dest.filename, backup)
        os.link(src.filename, dest.filename)
        os.unlink(backup)
        
    return dest.stat.st_size
    
def make_hardlinks_within_device(files, dry_run):
    by_inode = group_by(files, lambda f: f.stat.st_ino)
    # If there are no files or all files are hardlinked with eachother...
    if len(by_inode) <= 1:
        return 0
    
    bytes_hardlinked = 0
    master = max(files, key=lambda f: f.stat.st_nlink)
    for inode in by_inode:
        if inode == master.stat.st_ino:
            continue
        for f in by_inode[inode]:
            try:
                bytes_hardlinked += hardlink(master, f, dry_run)
            except Exception as ex:
                print("{}: Could not hardlink {} to {} ...skipping"\
                      .format(ex, master.strname(), f.strname()), file=sys.stderr)
    return bytes_hardlinked

def make_hardlinks(files, dry_run):
    bytes_hardlinked = 0
    for files in filter_solo(group_by_dev(files)):
        bytes_hardlinked += make_hardlinks_within_device(files, dry_run)
    return bytes_hardlinked

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

def filter_solo(items_list):
    return (i for i in items_list if len(i) > 1)

def read_filenames(stream, separator = b"\n"):
        read = lambda : stream.read(read_blocksize)
        remain = b""
        for buff in iter(read, b''):
            tokens = (remain + buff).split(separator)
            remain = b""
            # Keep remainder bytes if needed...
            if len(tokens) and len(tokens[-1]):
                tokens, remain = tokens[:-1], tokens[-1]

            for tok in tokens:
                if tok: yield tok
        if remain:
            yield remain

class Options(object):
    "Holds script options"
    def __init__(self):
        "Initialize options from command line"
        try:
            optlist, args = getopt.getopt(sys.argv[1:], '0', ['exec=', 'hardlink', 'dry-run'])
            if args:
                raise RuntimeError(str(args))
        except:
            print('Usage: dupes [--exec command | --hardlink] [-0] [--dry-run]', file=sys.stderr)
            sys.exit(1)
        
        self.action = listing_print # Sction on duplicates
        self.separator = b'\n'      # Files separator
        self.dry_run = False        # Dry run only
        self.count_bytes = False    # Do not count bytes
        
        for opt in optlist:
            if opt[0] == '--hardlink':
                self.action = make_hardlinks
                self.count_bytes = True
            if opt[0] == "--exec":
                self.action = lambda params: system(opt[1], params)
            if opt[0] == "--dry-run":
                self.dry_run = True
            if opt[0] == "-0":
                self.separator = b'\0'
        
        if self.action is make_hardlinks:
            self.action = lambda files: make_hardlinks(files, self.dry_run)

def main():
    opts = Options()
    total_bytes = 0
    for same_size in filter_solo( group_by_size( stat_files(read_filenames(stream, opts.separator)) )):
        for same_fhash in filter_solo( group_by_hash(same_size, fast_hash)):
            for identical in filter_solo( group_by_hash(same_fhash, sha1)):
                val = opts.action(identical)
                if opts.count_bytes:
                    total_bytes += val
    
    if opts.count_bytes:
        print( "{:.1f}Kbytes saved by hardlinking".format(total_bytes/1024.0) )
    return 0

if __name__ == "__main__":
    main()
    