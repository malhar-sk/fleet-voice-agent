import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import fleet_tools  # noqa: E402
from tests.fake_vm import FakeVM  # noqa: E402


@pytest.fixture
def fake_vm():
    with FakeVM() as vm:
        fleet_tools.set_client(fleet_tools.VMClient(vm.url))
        yield vm
    fleet_tools.set_client(None)
