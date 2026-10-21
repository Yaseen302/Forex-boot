"""Platform capabilities required only by native filesystem integration tests."""
import pytest


def _create_symlink(link, target):
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows denies symlink creation (WinError 1314); native symlink integration check unavailable for this user')
        raise


@pytest.fixture
def create_symlink():
    return _create_symlink
