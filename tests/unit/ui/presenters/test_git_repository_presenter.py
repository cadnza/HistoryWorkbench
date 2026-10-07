# File responsibility: Unit tests for GitRepositoryPresenter.
# These tests verify that the presenter connects to the command presenter's
# repository_changed signal and updates the panel UI reactively.
"""Unit tests for GitRepositoryPresenter."""

from collections.abc import Callable
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from freecad.history_wb.domain.git.models import GitCommit, GitRepository
from freecad.history_wb.qt import QtCore
from freecad.history_wb.ui.presenters.git_repository_presenter import GitRepositoryPresenter


@pytest.fixture
def mock_view() -> MagicMock:
    """Create a mock HistoryView."""
    return MagicMock()


@pytest.fixture
def mock_dialog_view() -> MagicMock:
    """Create a mock DialogView."""
    return MagicMock()


@pytest.fixture
def mock_get_commits_action() -> MagicMock:
    """Create a mock GetCommitsAction."""
    return MagicMock()


@pytest.fixture
def mock_application_state() -> MagicMock:
    """Create a mock ApplicationState."""
    return MagicMock()


@pytest.fixture
def mock_command_presenter() -> MagicMock:
    """Create a mock WorkbenchCommandPresenter with repository_changed signal."""
    mock = MagicMock()
    mock.repository_changed = MagicMock()
    mock.get_git_executable.return_value = "git"
    return mock


def _wait_for_mock_call(
    mock_method: MagicMock,
    trigger: Callable[[], None],
    on_call: Callable[[], None] | None = None,
) -> None:
    """Run a callback and wait for its asynchronous UI update."""
    event_loop = QtCore.QEventLoop()

    def finish_wait(*_args: object, **_kwargs: object) -> None:
        if on_call is not None:
            on_call()
        event_loop.quit()

    mock_method.side_effect = finish_wait
    QtCore.QTimer.singleShot(5000, event_loop.quit)
    trigger()
    event_loop.exec()


@pytest.fixture
def presenter(
    mock_view: MagicMock,
    mock_dialog_view: MagicMock,
    mock_get_commits_action: MagicMock,
    mock_application_state: MagicMock,
    mock_command_presenter: MagicMock,
) -> GitRepositoryPresenter:
    """Create a GitRepositoryPresenter instance with mocked dependencies."""
    return GitRepositoryPresenter(
        history_view=mock_view,
        dialog_view=mock_dialog_view,
        get_commits_action=mock_get_commits_action,
        application_state=mock_application_state,
        clear_doc_diffs=MagicMock(),
        workbench_command_presenter=mock_command_presenter,
    )


class TestGitRepositoryPresenter:
    """Tests for GitRepositoryPresenter."""

    def test_connects_to_repository_changed_signal(
        self,
        mock_command_presenter: MagicMock,
        presenter: GitRepositoryPresenter,
    ) -> None:
        """Presenter connects _on_repository_changed to repository_changed signal on init."""
        mock_command_presenter.repository_changed.connect.assert_called_once_with(presenter._on_repository_changed)

    def test_on_workbench_activated_calls_refresh(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """on_workbench_activated() delegates to refresh_repository_and_commits()."""
        presenter.on_workbench_activated()
        mock_command_presenter.refresh_git_repository.assert_called_once()

    def test_refresh_repository_and_commits_delegates_to_command_presenter(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """refresh_repository_and_commits() triggers detection via command presenter."""
        presenter.refresh_repository_and_commits()
        mock_command_presenter.refresh_git_repository.assert_called_once()

    def test_on_repository_changed_with_repository_updates_view(
        self,
        presenter: GitRepositoryPresenter,
        mock_view: MagicMock,
        mock_get_commits_action: MagicMock,
    ) -> None:
        """_on_repository_changed() shows repo and loads commits when repo is provided."""
        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")

        commits = [
            GitCommit(
                id="a1b2c3d",
                message="Test",
                author="Test",
                timestamp=datetime.fromisoformat("2024-01-15T10:30:00+00:00"),
            )
        ]
        mock_result = MagicMock()
        mock_result.is_success = True
        mock_result.data = commits
        worker_threads: list[QtCore.QThread] = []
        ui_threads: list[QtCore.QThread] = []
        app = QtCore.QCoreApplication.instance()
        assert app is not None
        mock_get_commits_action.execute.side_effect = lambda *_args, **_kwargs: (
            worker_threads.append(QtCore.QThread.currentThread()) or mock_result
        )

        _wait_for_mock_call(
            mock_view.show_commits,
            lambda: presenter._on_repository_changed(repo),
            on_call=lambda: ui_threads.append(QtCore.QThread.currentThread()),
        )

        assert worker_threads
        assert worker_threads[0] != app.thread()
        assert ui_threads == [app.thread()]
        mock_view.show_repository.assert_called_once_with(repo)
        mock_get_commits_action.execute.assert_called_once_with(
            repo,
            limit=20,
            skip=0,
            git_executable="git",
        )

    def test_on_repository_changed_with_none_shows_empty(
        self,
        presenter: GitRepositoryPresenter,
        mock_view: MagicMock,
    ) -> None:
        """_on_repository_changed() shows empty state when None is passed."""
        presenter._on_repository_changed(None)

        mock_view.show_repository.assert_called_once_with(None)
        mock_view.show_commits.assert_called_once_with([], show_special_items=False)

    def test_presenter_initialization_stores_dependencies(
        self,
        mock_view: MagicMock,
        mock_dialog_view: MagicMock,
        mock_get_commits_action: MagicMock,
        mock_application_state: MagicMock,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter stores all dependencies correctly on initialization."""
        presenter = GitRepositoryPresenter(
            history_view=mock_view,
            dialog_view=mock_dialog_view,
            get_commits_action=mock_get_commits_action,
            application_state=mock_application_state,
            clear_doc_diffs=MagicMock(),
            workbench_command_presenter=mock_command_presenter,
        )

        assert presenter._history_view is mock_view
        assert presenter._dialog_view is mock_dialog_view
        assert presenter._get_commits_action is mock_get_commits_action
        assert presenter._application_state is mock_application_state
        assert presenter._command_presenter is mock_command_presenter


class TestSaveIterationFlow:
    """Tests for save-iteration delegation in GitRepositoryPresenter."""

    def test_save_iteration_delegates_to_command_presenter(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter delegates save-iteration to command presenter."""
        mock_command_presenter.save_iteration.return_value = True

        with patch.object(presenter, "refresh_repository_and_commits") as refresh:
            presenter.save_iteration()

        mock_command_presenter.save_iteration.assert_called_once()
        refresh.assert_called_once_with()

    def test_save_iteration_skips_refresh_on_command_presenter_failure(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter does not refresh when command presenter returns False."""
        mock_command_presenter.save_iteration.return_value = False

        with patch.object(presenter, "refresh_repository_and_commits") as refresh:
            presenter.save_iteration()

        mock_command_presenter.save_iteration.assert_called_once()
        refresh.assert_not_called()


class TestInitializeRepositoryFlow:
    """Tests for initialize-repository delegation in GitRepositoryPresenter."""

    def test_initialize_repository_delegates_and_refreshes_on_success(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter delegates to command presenter and refreshes on success."""
        mock_command_presenter.initialize_repository.return_value = True

        with patch.object(presenter, "refresh_repository_and_commits") as refresh:
            presenter.initialize_repository()

        mock_command_presenter.initialize_repository.assert_called_once()
        refresh.assert_called_once_with()

    def test_initialize_repository_skips_refresh_on_failure(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter does not refresh when command presenter returns False."""
        mock_command_presenter.initialize_repository.return_value = False

        with patch.object(presenter, "refresh_repository_and_commits") as refresh:
            presenter.initialize_repository()

        mock_command_presenter.initialize_repository.assert_called_once()
        refresh.assert_not_called()


class TestUpdateGitignoreFlow:
    """Tests for gitignore delegation in GitRepositoryPresenter."""

    def test_update_gitignore_delegates_to_command_presenter(
        self,
        presenter: GitRepositoryPresenter,
        mock_command_presenter: MagicMock,
    ) -> None:
        """Presenter delegates update_gitignore to command presenter."""
        presenter.update_gitignore()

        mock_command_presenter.update_gitignore.assert_called_once()


class TestCommitLoading:
    """Tests for GitRepositoryPresenter commit loading functionality."""

    def test_load_initial_commits_calls_show_commits_on_success(
        self,
        presenter: GitRepositoryPresenter,
        mock_view: MagicMock,
        mock_get_commits_action: MagicMock,
    ) -> None:
        """_load_initial_commits() calls show_commits with commits on success."""
        commits = [
            GitCommit(
                id="a1b2c3d4e5f67890",
                message="Test commit",
                author="Test Author",
                timestamp=datetime.fromisoformat("2024-01-15T10:30:00+00:00"),
            ),
        ]
        mock_result = MagicMock()
        mock_result.is_success = True
        mock_result.data = commits
        mock_get_commits_action.execute.return_value = mock_result

        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")
        presenter._reset_commit_pagination(repo)

        _wait_for_mock_call(mock_view.show_commits, lambda: presenter._load_initial_commits(repo))

        mock_get_commits_action.execute.assert_called_once_with(
            repo,
            limit=20,
            skip=0,
            git_executable="git",
        )
        mock_view.show_commits.assert_called_once_with(commits)

    def test_load_initial_commits_shows_empty_list_on_failure(
        self,
        presenter: GitRepositoryPresenter,
        mock_view: MagicMock,
        mock_get_commits_action: MagicMock,
    ) -> None:
        """_load_initial_commits() shows empty list when action fails."""
        mock_result = MagicMock()
        mock_result.is_success = False
        mock_result.message = "Git error"
        mock_get_commits_action.execute.return_value = mock_result

        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")
        presenter._reset_commit_pagination(repo)

        _wait_for_mock_call(mock_view.show_commits, lambda: presenter._load_initial_commits(repo))

        mock_view.show_commits.assert_called_once_with([])

    def test_load_more_commits_loads_next_page(self, presenter: GitRepositoryPresenter) -> None:
        """Scroll near bottom loads next commit page with skip offset."""
        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")
        presenter._application_state.git_repository = repo
        presenter._active_repo_path = repo.absolute_path
        presenter._loaded_commit_count = 20
        presenter._has_more_commits = True

        commits = [
            GitCommit(
                id="z9y8x7w",
                message="Older commit",
                author="Dev",
                timestamp=datetime.fromisoformat("2024-01-10T10:30:00+00:00"),
            )
        ]
        result = MagicMock()
        result.is_success = True
        result.data = commits
        presenter._get_commits_action.execute.return_value = result

        _wait_for_mock_call(presenter._history_view.append_commits, presenter.load_more_commits)

        presenter._get_commits_action.execute.assert_called_once_with(
            repo,
            limit=20,
            skip=20,
            git_executable="git",
        )
        presenter._history_view.append_commits.assert_called_once_with(commits)

    def test_load_more_commits_skips_when_no_more(self, presenter: GitRepositoryPresenter) -> None:
        """Scroll near bottom does nothing when no further pages exist."""
        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")
        presenter._application_state.git_repository = repo
        presenter._active_repo_path = repo.absolute_path
        presenter._has_more_commits = False

        presenter.load_more_commits()

        presenter._get_commits_action.execute.assert_not_called()

    def test_load_more_commits_throttles_rapid_calls(self, presenter: GitRepositoryPresenter) -> None:
        """Rapid bottom-scroll callbacks are throttled to one load call."""
        repo = GitRepository(name="test_project", absolute_path="/home/user/test_project")
        presenter._application_state.git_repository = repo
        presenter._active_repo_path = repo.absolute_path
        presenter._loaded_commit_count = 20
        presenter._has_more_commits = True

        result = MagicMock()
        result.is_success = True
        result.data = [
            GitCommit(
                id="older",
                message="Older commit",
                author="Dev",
                timestamp=datetime.fromisoformat("2024-01-10T10:30:00+00:00"),
            )
        ]
        presenter._get_commits_action.execute.return_value = result

        with patch("freecad.history_wb.ui.presenters.git_repository_presenter.monotonic", return_value=10.0):
            presenter.load_more_commits()
            _wait_for_mock_call(presenter._history_view.append_commits, presenter.load_more_commits)

            presenter._get_commits_action.execute.assert_called_once_with(
                repo,
                limit=20,
                skip=20,
                git_executable="git",
            )
