# File responsibility: Run blocking git-backed operations without blocking Qt's UI thread.
"""Qt worker for background git operations."""

from collections.abc import Callable

from ....qt import QtCore
from ....utils import Log


class GitOperationThread(QtCore.QThread):
    """Execute one operation in a worker thread and report completion to its owner."""

    succeeded = QtCore.Signal(object, object)
    failed = QtCore.Signal(object, str)

    def __init__(
        self,
        operation: Callable[[], object],
        context: object,
        parent: QtCore.QObject,
    ) -> None:
        """Create a worker for one operation."""
        super().__init__(parent)
        self._operation = operation
        self._context = context

    def run(self) -> None:
        """Execute the operation and send its outcome to the owning Qt thread."""
        try:
            result = self._operation()
        except (OSError, RuntimeError, ValueError) as error:
            Log.exception(f"Background git operation failed: {error}")
            self.failed.emit(self._context, str(error))
        else:
            self.succeeded.emit(self._context, result)
