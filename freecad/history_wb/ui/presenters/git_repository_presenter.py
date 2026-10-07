# File responsibility: Presents git repository information and manages commit loading in the UI.
"""Git repository presenter for UI layer."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import cast

from freecad.history_wb.application.actions.git_history.get_commits import GetCommitsAction
from freecad.history_wb.application.actions.result_models import Result
from freecad.history_wb.domain.git.models import GitRepository
from freecad.history_wb.qt import QtCore
from freecad.history_wb.ui.state import ApplicationState
from freecad.history_wb.ui.views.diff_panel.dialog_view import DialogView
from freecad.history_wb.ui.views.history.panel import HistoryPanelWidget
from freecad.history_wb.utils import Log, translate

from .git_repository.background_task import GitOperationThread
from .workbench_command_presenter import WorkbenchCommandPresenter


@dataclass(frozen=True)
class _CommitLoadRequest:
    """Identify a commit page request and the repository state it belongs to."""

    repo: GitRepository
    skip: int
    generation: int


class GitRepositoryPresenter(QtCore.QObject):
    """Handles git repository UI display and commit loading.

    This presenter is responsible for:
    1. Displaying the repository information in the view
    2. Loading and displaying commits for the repository

    Repository detection and application state updates are delegated to
    WorkbenchCommandPresenter. This presenter connects to the
    repository_changed signal to update the panel UI reactively.
    """

    def __init__(
        self,
        history_view: HistoryPanelWidget,
        dialog_view: DialogView,
        get_commits_action: GetCommitsAction,
        application_state: ApplicationState,
        clear_doc_diffs: Callable[[], None],
        workbench_command_presenter: WorkbenchCommandPresenter,
        parent: QtCore.QObject | None = None,
    ) -> None:
        """Initialize the presenter with required dependencies.

        Args:
            history_view: History-column view implementation.
            dialog_view: Dialog and message view implementation.
            get_commits_action: The action for getting git commits.
            application_state: Application-scoped state holder for storing repository.
            clear_doc_diffs: Callback to clear document diffs.
            workbench_command_presenter: App-scoped presenter for detection and shared command flows.
            parent: Qt owner that controls this presenter's panel lifetime.
        """
        super().__init__(parent)
        self._history_view = history_view
        self._dialog_view = dialog_view
        self._get_commits_action = get_commits_action
        self._application_state = application_state
        self._clear_doc_diffs = clear_doc_diffs
        self._command_presenter = workbench_command_presenter
        self._page_size = 20
        self._loaded_commit_count = 0
        self._has_more_commits = False
        self._is_loading_commits = False
        self._active_repo_path: str | None = None
        self._load_generation = 0
        self._commit_threads: set[GitOperationThread] = set()
        self._last_scroll_load_ts = 0.0
        self._scroll_load_interval_seconds = 0.2

        # Listen for repository changes from the command presenter
        workbench_command_presenter.repository_changed.connect(self._on_repository_changed)

    def on_workbench_activated(self) -> None:
        """Detect and display git repository when workbench activates."""
        self.refresh_repository_and_commits()

    def refresh_repository_and_commits(self) -> None:
        """Trigger repository detection via the command presenter.

        The repository_changed signal will fire and update the panel UI.
        """
        self._command_presenter.refresh_git_repository()

    def save_iteration(self) -> None:
        """Execute save-iteration flow from toolbar or panel button."""
        success = self._command_presenter.save_iteration()
        if success:
            Log.info("Commit successful")
            self.refresh_repository_and_commits()

    def initialize_repository(self) -> None:
        """Execute repository initialization flow from toolbar command."""
        initialized = self._command_presenter.initialize_repository()
        if initialized:
            self.refresh_repository_and_commits()

    def update_gitignore(self) -> None:
        """Execute gitignore editor flow from toolbar command."""
        self._command_presenter.update_gitignore()

    def _on_repository_changed(self, repo: GitRepository | None) -> None:
        """Update panel UI when the command presenter refreshes the repository."""
        if repo is not None:
            self._history_view.show_repository(repo)
            self._reset_commit_pagination(repo)
            self._load_initial_commits(repo)
        else:
            self._reset_commit_pagination(None)
            self._history_view.show_repository(None)
            self._history_view.show_commits([], show_special_items=False)
            self._clear_doc_diffs()

    def _load_initial_commits(self, repo: GitRepository) -> None:
        """Load first commit page and replace list content.

        Args:
            repo: The GitRepository to load commits from.
        """
        if self._is_loading_commits:
            return
        self._is_loading_commits = True
        self._start_commit_load(repo, skip=0)

    def load_more_commits(self) -> None:
        """Load next commit page when history scroll reaches bottom area."""
        now = monotonic()
        if now - self._last_scroll_load_ts < self._scroll_load_interval_seconds:
            return

        repo = self._application_state.git_repository
        if repo is None:
            return
        if self._active_repo_path != repo.absolute_path:
            return
        if self._is_loading_commits or not self._has_more_commits:
            return

        self._last_scroll_load_ts = now
        self._is_loading_commits = True
        self._start_commit_load(repo, skip=self._loaded_commit_count)

    def _start_commit_load(self, repo: GitRepository, *, skip: int) -> None:
        """Start a commit-page query after capturing preferences on the UI thread."""
        git_executable = self._command_presenter.get_git_executable()
        if git_executable is None:
            self._command_presenter.check_git_availability()
            self._is_loading_commits = False
            self._has_more_commits = False
            if skip == 0:
                self._loaded_commit_count = 0
                self._clear_doc_diffs()
                self._history_view.show_commits([])
            return

        request = _CommitLoadRequest(repo, skip, self._load_generation)
        application = QtCore.QCoreApplication.instance()
        if application is None:
            raise RuntimeError("A Qt application must exist before loading Git history.")

        get_commits_action = self._get_commits_action
        page_size = self._page_size
        worker = GitOperationThread(
            lambda: (
                request,
                get_commits_action.execute(
                    repo,
                    limit=page_size,
                    skip=skip,
                    git_executable=git_executable,
                ),
            ),
            request,
            application,
        )
        self._commit_threads.add(worker)
        worker.succeeded.connect(self._on_commit_load_succeeded)
        worker.failed.connect(self._on_commit_load_failed)
        worker.finished.connect(self._on_commit_thread_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_commit_load_succeeded(self, context: object, payload: object) -> None:
        """Apply loaded commit rows on the UI thread if request is still current."""
        request, result = cast(tuple[_CommitLoadRequest, Result], payload)
        if context != request:
            return
        if request.generation != self._load_generation or request.repo.absolute_path != self._active_repo_path:
            return

        self._is_loading_commits = False
        if not result.is_success:
            self._on_commit_load_result_failed(request, result.message or "Git history query failed")
            return

        commits = result.data
        if request.skip == 0:
            self._loaded_commit_count = len(commits)
            self._has_more_commits = len(commits) == self._page_size
            self._clear_doc_diffs()
            self._history_view.show_commits(commits)
            return

        if not commits:
            self._has_more_commits = False
            return

        self._history_view.append_commits(commits)
        self._loaded_commit_count += len(commits)
        self._has_more_commits = len(commits) == self._page_size

    def _on_commit_load_failed(self, context: object, error: str) -> None:
        """Report an unexpected worker failure without applying stale results."""
        request = cast(_CommitLoadRequest, context)
        if request.generation != self._load_generation or request.repo.absolute_path != self._active_repo_path:
            return

        self._is_loading_commits = False
        self._on_commit_load_result_failed(request, error)

    def _on_commit_load_result_failed(self, request: _CommitLoadRequest, message: str) -> None:
        """Show failed commit loading state and report its cause."""
        Log.warning(f"Failed to load commits: {message}")
        self._has_more_commits = False
        if request.skip == 0:
            self._loaded_commit_count = 0
            self._clear_doc_diffs()
            self._history_view.show_commits([])
        self._dialog_view.show_error_message(
            translate("History", "History Load Failed"),
            translate("History", "Could not load project history: %1").replace("%1", message),
        )

    def _on_commit_thread_finished(self) -> None:
        """Release completed commit workers after their result signals are handled."""
        worker = self.sender()
        if isinstance(worker, GitOperationThread) and worker in self._commit_threads:
            self._commit_threads.remove(worker)
            worker.deleteLater()

    def _reset_commit_pagination(self, repo: GitRepository | None) -> None:
        """Reset pagination state for current repository."""
        self._load_generation += 1
        self._loaded_commit_count = 0
        self._has_more_commits = repo is not None
        self._is_loading_commits = False
        self._active_repo_path = repo.absolute_path if repo is not None else None
        self._last_scroll_load_ts = 0.0
