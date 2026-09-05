"""Runtime identity must survive credential isolation for model subprocesses."""

import json
import os
import subprocess
import sys

import pytest

from application.launcher import child_process_environment


@pytest.mark.parametrize("identity_key", ["LOGNAME", "USER", "LNAME", "USERNAME"])
def test_filtered_child_can_resolve_username_without_inheriting_credentials(identity_key):
    identity_keys = {"LOGNAME", "USER", "LNAME", "USERNAME"}
    base = {key: value for key, value in os.environ.items() if key.upper() not in identity_keys}
    expected_user = "synthetic-model-user"
    forbidden = [
        "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN", "YOUTUBE_API_KEY",
        "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AZURE_CLIENT_SECRET", "SECRET_ALIAS",
        "USER_PASSWORD",
    ]
    base.update({name: "synthetic-secret" for name in forbidden})
    base[identity_key] = expected_user
    environment = child_process_environment(
        [sys.executable, "-m", "processing.face_analysis"],
        base_environment=base,
    )

    # Use a real subprocess: on Windows, getpass otherwise tries importing the
    # unavailable Unix pwd module. PyTorch uses this lookup for its cache path.
    code = (
        "import getpass, json, os; "
        "print(json.dumps({'username': getpass.getuser(), "
        f"'forbidden': [name for name in {forbidden!r} if name in os.environ]}}))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"username": expected_user, "forbidden": []}
    assert base[identity_key] == expected_user
    assert base["HF_TOKEN"] == "synthetic-secret"
