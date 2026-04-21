from pathlib import Path
import sys

from setuptools import find_packages, setup


PROJECT_ROOT = str(Path(__file__).resolve().parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

setup(
    packages=find_packages(
        include=[
            "agent",
            "acp_adapter",
            "cron",
            "gateway",
            "gateway.*",
            "hermes_cli",
            "plugins",
            "plugins.*",
            "tools",
            "tools.*",
        ]
    ),
    py_modules=[
        "run_agent",
        "model_tools",
        "toolsets",
        "batch_runner",
        "trajectory_compressor",
        "toolset_distributions",
        "cli",
        "hermes_constants",
        "hermes_state",
        "hermes_time",
        "hermes_logging",
        "rl_cli",
        "utils",
    ],
)
