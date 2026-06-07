def test_can_import_exp_graph_engine():
    # masbench bridges to the sibling exp_graph engine (uv editable install, or
    # the sys.path fallback in masbench/__init__).
    import masbench  # noqa: F401
    from exp_graph.runner import SynchronousRunner  # noqa: F401
    from exp_graph.tasks.base import TaskAdapter  # noqa: F401


def test_masbench_version_present():
    import masbench

    assert isinstance(masbench.__version__, str)
