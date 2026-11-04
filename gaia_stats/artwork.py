"""Locally served original-site artwork and pinned presentation dependencies."""
from pathlib import Path


ASSETS = {
    '/art/gaia-project-cover.jpeg': ('gaia-project-cover.jpeg', 'image/jpeg'),
    '/art/site-art.css': ('site-art.css', 'text/css; charset=utf-8'),
    '/art/site-art.js': ('site-art.js', 'application/javascript'),
    '/art/vendor/three.r119.min.js': ('vendor/three.r119.min.js', 'application/javascript'),
    '/art/vendor/vanta.fog.min.js': ('vendor/vanta.fog.min.js', 'application/javascript'),
}


def response(path):
    if path not in ASSETS:
        raise FileNotFoundError(path)
    filename, content_type = ASSETS[path]
    root = Path(__file__).resolve().parent.parent / 'web' / 'art'
    return (root / filename).read_bytes(), content_type
