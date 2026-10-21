"""A missing Windows privilege is distinct from a failing filesystem check."""
import pytest


def test_native_symlink_check_reports_windows_privilege_skip(create_symlink):
    class Denied:
        def symlink_to(self, target):
            error=OSError('A required privilege is not held by the client')
            error.winerror=1314
            raise error
    with pytest.raises(pytest.skip.Exception,match='WinError 1314'):
        create_symlink(Denied(),'target')


@pytest.mark.parametrize('winerror',[None,5])
def test_unexpected_symlink_errors_still_fail(create_symlink,winerror):
    error=PermissionError(13,'Unexpected filesystem access denial')
    if winerror is not None:error.winerror=winerror
    class Denied:
        def symlink_to(self,target):raise error
    with pytest.raises(PermissionError) as failure:
        create_symlink(Denied(),'target')
    assert failure.value is error
