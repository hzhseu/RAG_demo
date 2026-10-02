import os
import subprocess
import sys
import time
import pytest
from nordrag.processes import run_owned


@pytest.mark.skipif(os.name!='nt',reason='Windows process tree ownership')
def test_timeout_terminates_descendant_inherited_pipes():
    script="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)']); time.sleep(5)"
    started=time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable,'-c',script],timeout=.5)
    assert time.monotonic()-started < 3
