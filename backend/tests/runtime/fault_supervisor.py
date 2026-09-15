"""Test-only role factory; never collected by the production entrypoint."""

from app.runtime import supervisor
from app.runtime.python_launch import python_launch

supervisor.python_launch = lambda _module, _arguments: python_launch(
    "tests.runtime.stubborn_api", []
)
raise SystemExit(supervisor.run_supervisor())
