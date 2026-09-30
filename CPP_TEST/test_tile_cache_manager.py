from CORE.tile_cache_manager import CacheBudgets, TileCacheManager


def test_slow_pan_retains_visible_and_small_halo():
    manager = TileCacheManager(CacheBudgets(projection_tiles=32))
    desired = manager.update({(4, 4)}, pan_delta=(2, 1), zoom=1.0)
    assert (4, 4) in desired
    assert (3, 3) in desired and (5, 5) in desired
    assert manager.snapshot()["prefetch"] == 8


def test_fast_pan_prefetches_direction_and_keeps_recent_projection():
    manager = TileCacheManager(CacheBudgets(projection_tiles=8))
    manager.update({(4, 4)}, pan_delta=(0, 0), zoom=1.0)
    desired = manager.update({(5, 4)}, pan_delta=(-80, 0), zoom=1.0)
    # Screen offset moving left means the viewport travels right in document space.
    assert (6, 4) in desired and (8, 4) in desired
    assert manager.should_retain((4, 4))


def test_zoomed_out_avoids_speculative_directional_band():
    manager = TileCacheManager()
    desired = manager.update({(4, 4)}, pan_delta=(-100, 0), zoom=.25)
    assert desired == {(4, 4)}
