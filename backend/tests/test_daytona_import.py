import asyncio
from types import SimpleNamespace

import pytest


class FakeProcess:
    def __init__(self, output, exit_code):
        self.output = output
        self.exit_code = exit_code
        self.command = None

    async def exec(self, command, timeout):
        self.command = command
        return SimpleNamespace(result=self.output, exit_code=self.exit_code)


def test_github_import_uses_clone_command_without_shell_globs(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    import daytona_service

    process = FakeProcess("Cloning into '/home/daytona/project'...", 0)
    sandbox = SimpleNamespace(process=process)

    result = asyncio.run(daytona_service.import_github_repo(
        sandbox, "https://github.com/owner/repo", branch="main"
    ))

    assert result["exit_code"] == 0
    assert "git clone --depth 1 --branch main" in process.command
    assert "rm -rf" not in process.command


def test_private_github_import_reports_missing_token(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    import daytona_service

    process = FakeProcess("fatal: could not read Username for 'https://github.com': No such device or address", 128)
    sandbox = SimpleNamespace(process=process)

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        asyncio.run(daytona_service.import_github_repo(sandbox, "https://github.com/owner/repo"))


def test_dev_server_command_does_not_kill_its_own_shell(monkeypatch):
    monkeypatch.setenv("DAYTONA_API_KEY", "test-key")
    import daytona_service

    class SessionProcess:
        command = None

        async def get_session(self, session_id):
            raise RuntimeError("No existing session")

        async def create_session(self, session_id):
            return None

        async def execute_session_command(self, session_id, request):
            self.command = request.command

    process = SessionProcess()
    asyncio.run(daytona_service.start_dev_server(SimpleNamespace(process=process)))

    assert "pkill -f vite" not in process.command
    assert "npm run dev" in process.command
