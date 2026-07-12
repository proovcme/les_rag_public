from pathlib import Path
import plistlib

from tools.rag_generation_supervisor import render_launchd_plist


def test_launchd_generation_job_restarts_only_after_unsuccessful_exit(tmp_path: Path):
    payload = plistlib.loads(
        render_launchd_plist(
            label="me.ovc.les.rag-generation",
            python=Path("/runtime/python"),
            script=Path("/repo/tools/rag_generation_supervisor.py"),
            worker_args=["--src", "old", "--dst", "new"],
            workdir=tmp_path,
            log_path=tmp_path / "job.log",
        )
    )

    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProgramArguments"][:3] == [
        "/runtime/python",
        "/repo/tools/rag_generation_supervisor.py",
        "run",
    ]
    assert payload["ProgramArguments"][-4:] == ["--src", "old", "--dst", "new"]
    assert payload["ThrottleInterval"] == 30
