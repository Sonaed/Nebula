"""Integration contract between Nebula and the Existence environment.

This package deliberately contains only orchestration and protocol glue. The
document model, raster tools and brush engine remain owned by Nebula/C++.
"""

__all__ = ["MANIFEST_PATH", "load_manifest", "handle_message"]


def __getattr__(name):
    # Lazy loading keeps ``python -m EXISTENCE.adapter`` free of runpy import
    # warnings and leaves the package itself independent of the transport.
    if name in __all__:
        from . import adapter
        return getattr(adapter, name)
    raise AttributeError(name)
