# Deduplicator

Locate duplicate files and optionally deduplicate them using hard links.
Can be used with both python2 and python3.

Example usage:

```sh
find . -print0 |  python3 deduplicator.py -0 --dry-run --hardlink
```
