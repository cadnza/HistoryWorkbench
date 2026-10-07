# File responsibility: Unit tests for FindActiveGitRepositoryAction orchestration and result contracts.
"""Unit tests for FindActiveGitRepositoryAction."""

from unittest.mock import MagicMock

from freecad.history_wb.application.actions.git_repo.find_active_git_repository import (
    FindActiveGitRepositoryAction,
)
from freecad.history_wb.domain.git.git_service import GitService
from freecad.history_wb.domain.git.models import GitRepository
from tests.fakes.fake_freecad_port import FakeFreeCadPort
from tests.fakes.fake_git_port import FakeGitPort


def _execute(action: FindActiveGitRepositoryAction, current_repository: GitRepository | None = None):
    """Run repository resolution with document and preference snapshots."""
    return action.execute(
        action.get_open_document_paths(),
        current_repository=current_repository,
        git_executable=action.get_git_executable(),
    )


class TestFindActiveGitRepositoryAction:
    """Tests for FindActiveGitRepositoryAction execute behavior."""

    def test_execute_returns_repository_when_document_in_git_repo(self) -> None:
        fake_freecad = FakeFreeCadPort()
        fake_git = FakeGitPort()
        fake_git.add_git_repo("/home/user/project")

        mock_doc = MagicMock()
        mock_doc.FileName = "/home/user/project/src/file.FCStd"
        fake_freecad._open_documents = [mock_doc]

        service = GitService(fake_git)
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is True
        assert isinstance(result.data, GitRepository)
        assert result.data.name == "project"
        assert result.data.absolute_path == "/home/user/project"

    def test_execute_fails_when_no_documents_open(self) -> None:
        fake_freecad = FakeFreeCadPort(open_documents=[])
        service = GitService(FakeGitPort())
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is False
        assert result.data is None
        assert result.message == "No documents are open"

    def test_execute_fails_when_document_not_in_git_repo(self) -> None:
        fake_freecad = FakeFreeCadPort()
        mock_doc = MagicMock()
        mock_doc.FileName = "/home/user/dir/unsaved.FCStd"
        fake_freecad._open_documents = [mock_doc]

        service = GitService(FakeGitPort())
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is False
        assert result.message == "No git repository found for open documents"

    def test_execute_skips_unsaved_documents(self) -> None:
        fake_freecad = FakeFreeCadPort()
        fake_git = FakeGitPort()
        fake_git.add_git_repo("/home/user/saved")

        unsaved = MagicMock()
        unsaved.FileName = ""
        saved = MagicMock()
        saved.FileName = "/home/user/saved/file.FCStd"
        fake_freecad._open_documents = [unsaved, saved]

        service = GitService(fake_git)
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is True
        assert result.data.name == "saved"

    def test_execute_fails_when_all_documents_unsaved(self) -> None:
        fake_freecad = FakeFreeCadPort()
        doc1 = MagicMock()
        doc1.FileName = ""
        doc2 = MagicMock()
        doc2.FileName = ""
        fake_freecad._open_documents = [doc1, doc2]

        service = GitService(FakeGitPort())
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is False
        assert result.message == "No git repository found for open documents"

    def test_execute_keeps_current_repo_when_documents_still_belong_to_it(self) -> None:
        """Sticky repo: keeps current repo when open documents still belong to it."""
        fake_freecad = FakeFreeCadPort()
        fake_git = FakeGitPort()
        fake_git.add_git_repo("/home/user/project1")
        fake_git.add_git_repo("/home/user/project2")

        doc1 = MagicMock()
        doc1.FileName = "/home/user/project2/file2.FCStd"
        doc2 = MagicMock()
        doc2.FileName = "/home/user/project1/file1.FCStd"
        fake_freecad._open_documents = [doc1, doc2]

        service = GitService(fake_git)
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        current_repo = GitRepository(name="project1", absolute_path="/home/user/project1")
        result = _execute(action, current_repo)

        assert result.is_success is True
        assert result.data.absolute_path == "/home/user/project1"

    def test_execute_switches_repo_when_current_has_no_open_documents(self) -> None:
        """Sticky repo: switches to new repo when current repo has no open documents."""
        fake_freecad = FakeFreeCadPort()
        fake_git = FakeGitPort()
        fake_git.add_git_repo("/home/user/project1")
        fake_git.add_git_repo("/home/user/project2")

        doc = MagicMock()
        doc.FileName = "/home/user/project2/file.FCStd"
        fake_freecad._open_documents = [doc]

        service = GitService(fake_git)
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        current_repo = GitRepository(name="project1", absolute_path="/home/user/project1")
        result = _execute(action, current_repo)

        assert result.is_success is True
        assert result.data.absolute_path == "/home/user/project2"

    def test_execute_finds_first_repo_when_no_current_repo(self) -> None:
        """Without a current repo, picks the first repository found."""
        fake_freecad = FakeFreeCadPort()
        fake_git = FakeGitPort()
        fake_git.add_git_repo("/home/user/project1")
        fake_git.add_git_repo("/home/user/project2")

        doc1 = MagicMock()
        doc1.FileName = "/home/user/project2/file2.FCStd"
        doc2 = MagicMock()
        doc2.FileName = "/home/user/project1/file1.FCStd"
        fake_freecad._open_documents = [doc1, doc2]

        service = GitService(fake_git)
        action = FindActiveGitRepositoryAction(fake_freecad, service)

        result = _execute(action)

        assert result.is_success is True
        assert result.data.absolute_path == "/home/user/project2"
