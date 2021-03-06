#!/usr/bin/env python
from __future__ import print_function
from collections import defaultdict
from functools import partial
import os
import stat
import sys
import hashlib
import getopt
import subprocess


def fsencode(x):
    return x


fsdecode = fsencode
stream = sys.stdin

# Python 3 compatibility
if sys.version_info[0] >= 3:
    fsencode = os.fsencode
    fsdecode = os.fsdecode
    stream = sys.stdin.buffer


class FileInfo(object):
    """Filename and stat file information"""

    def __init__(self, f):
        self.filename = f
        self.stat = os.stat(f)

    def regular_file(self):
        mode = self.stat[stat.ST_MODE]
        return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)

    def __str__(self):
        return fsdecode(self.filename)


def read_chunk(stream):
    """Read at most a chunk from a stream"""
    chunk_size = 16 * 1024
    return stream.read(chunk_size)


def sha1(filename):
    """Comprehensive SHA1 hash of entire file"""
    h = hashlib.sha1()
    with open(filename, 'rb') as f:
        for block in iter(partial(read_chunk, f), b''):
            h.update(block)
    return h.digest()


def fast_hash(filename):
    """Quick MD5 hash of first block only"""
    h = hashlib.md5()
    with open(filename, 'rb') as f:
        block = read_chunk(f)
        h.update(block)
    return h.digest()


def stat_files(filenames):
    """Produce FileInfo for all non-empty files"""
    for fname in filenames:
        try:
            info = FileInfo(fname)
            if info.regular_file() and info.stat.st_size:
                yield info
        except OSError:
            print("Could not stat {} skipping..."
                  .format(fsdecode(fname)), file=sys.stderr)


def group_by(files, key):
    """Group files by key function"""
    by_group = defaultdict(list)
    for f in files:
        by_group[key(f)].append(f)
    return by_group


def group_by_hash(files, hash_function):
    by_dev_inode = group_by(
        files,
        lambda f: (
            f.stat.st_ino,
            f.stat.st_dev)).values()
    # If they're all the same inode, no need to calculate hashes at all.
    if len(by_dev_inode) <= 1:
        return [files]

    by_hash = defaultdict(list)
    for same_inode in by_dev_inode:
        try:
            h = hash_function(same_inode[0].filename)
            by_hash[h].extend(same_inode)
        except IOError:
            print("Could not get hash for {} skipping..."
                  .format(same_inode[0]), file=sys.stderr)

    return by_hash.values()


def listing_print(files):
    print()
    for f in files:
        print("{} {} {}".format(f.stat.st_nlink, f.stat.st_ino, f))
    print()


def hardlink(src, dest, dry_run):
    """Make dest a hardlink to the src"""
    assert src.stat.st_dev == dest.stat.st_dev
    print("linking...\n{} to \n{}".format(src, dest))
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
                print("{}: Could not hardlink {} to {} ...skipping"
                      .format(ex, master, f),
                      file=sys.stderr)
    return bytes_hardlinked


def make_hardlinks(files, dry_run):
    bytes_hardlinked = 0
    for files in filter_solo(group_by_dev(files)):
        bytes_hardlinked += make_hardlinks_within_device(files, dry_run)
    return bytes_hardlinked


def system(cmd, params):
    command = [fsencode(i) for i in cmd.split()]
    return subprocess.call(command + [i.filename for i in params])


def group_by_size(files):
    return group_by(files, lambda f: f.stat.st_size).values()


def group_by_dev(files):
    return group_by(files, lambda f: f.stat.st_dev).values()


def filter_solo(items_list):
    return (i for i in items_list if len(i) > 1)


def read_filenames(stream, separator):
    remain = b""
    for buff in iter(partial(read_chunk, stream), b''):
        tokens = (remain + buff).split(separator)
        remain = b""
        # Keep remainder bytes if needed...
        if len(tokens) and len(tokens[-1]):
            tokens, remain = tokens[:-1], tokens[-1]

        for tok in tokens:
            if tok:
                yield tok
    if remain:
        yield remain


class Options(object):
    """Holds script options"""

    def __init__(self):
        """Initialize options from command line"""
        try:
            optlist, args = getopt.getopt(
                sys.argv[1:], "0", ["exec=", "hardlink", "dry-run"])
            if args:
                raise RuntimeError(str(args))
        except BaseException:
            print("Usage: dupes [--exec command | --hardlink]"
                  " [-0] [--dry-run]", file=sys.stderr)
            sys.exit(1)

        self.action = listing_print  # Action on duplicates
        self.separator = b'\n'      # Files separator
        self.dry_run = False        # Dry run only
        self.count_bytes = False    # Do not count bytes

        for opt in optlist:
            if opt[0] == "--hardlink":
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


def group_compose(data, functions):
    """Group of data successively, based on the provided groupping functions"""
    for f in functions:
        newdata = []
        for d in (f(i) for i in data):
            newdata.extend(filter_solo(d))  # After each groupping, filter
        data = newdata
    return data


def deduplicate(filenames):
    """Deduplicate files and yield groups of identical FileInfo objects"""
    # Apply successive groupping functions
    functions = [
        group_by_size,
        lambda x: group_by_hash(x, fast_hash),
        lambda x: group_by_hash(x, sha1)
    ]
    # All files start in one group of FileInfo objects
    all_files = [stat_files(filenames)]

    for group in group_compose(all_files, functions):
        yield group


def main():
    opts = Options()
    total_bytes = 0
    filenames = read_filenames(stream, opts.separator)

    for group in deduplicate(filenames):
        val = opts.action(group)
        if opts.count_bytes:
            total_bytes += val

    if opts.count_bytes:
        print("{:.1f}Kbytes saved by hardlinking".format(total_bytes / 1024.0))
    return 0


if __name__ == "__main__":
    main()
