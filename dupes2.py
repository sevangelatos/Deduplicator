#!/usr/bin/env python
import os
import stat
import sys
import hashlib
import getopt

read_blocksize = 409600
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

##def identical(f1, f2):
##    try:
##        f1 = open(f2, "rb")
##        f2 = open(f2, "rb")
##        d1, d2 = 'foo', 'bar'
##        while d1 and d2:
##            d1 = f1.read(read_blocksize)
##            d2 = f2.read(read_blocksize)
##            if d1 != d2 or len(d1) != len(d2):
##                return False
##        return True
##    except:
##        return False

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

def group_identical(files, onlyhash = True):
    by_inode = {}
    for f in files:
        inode = f.stat.st_ino
        if inode in by_inode:
            by_inode[inode].append(f)
        else:
            by_inode[inode] = [f]
    
    if len(by_inode) <= 1:
        return [files]

    by_hash = {}
    for inode in by_inode:
        try:
            h = sha1(by_inode[inode][0].filename)
        except IOError:
            sys.stderr.write("Could not get signature for " +
                             by_inode[inode][0].filename + " skipping...\n")
            continue
        if h in by_hash:
            by_hash[h] = by_hash[h] + by_inode[inode]
        else:
            by_hash[h] = by_inode[inode]
    
    return [files for files in by_hash.values() if len(files) > 1]

def listing_print(l):
    print('')
    for i in l:
        print("{} {} {}".format(i.stat.st_nlink, i.stat.st_ino, i.filename))
    print('')

def hardlink(src, dest):
    if src.stat.st_dev != dest.stat.st_dev:
        print("{} and {} are not on the same device"\
            .format(src.filename, dest.filename))
        return False

    try:
        backup = dest.filename + ".bak"
        os.rename(dest.filename, backup)
        os.link(src.filename, dest.filename)
        os.unlink(backup)
    except Exception as ex:
        print(ex)
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
            hardlink(master, f)
            
    # for each of the files with inode != best_inode
        # rm (unlink?) file
        # Link file with the best_inode (master) file


def system(cmd, params):
    ex = cmd.split()[0]
    status = os.spawnvp(os.P_WAIT, ex, cmd.split()+params)
    if (status == 127):
        raise ChildProcessError("Could not execute: " + ex)
    return status

def print_help():
    print('Usage: dupes [--exec command | --hardlink]')
    

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

for ss in group_by_size():
    for sf in group_identical(ss):
        action(sf)
