def test_can_import_exp_graph_engine():
    # masbench must make the sibling exp_graph engine importable.
    import masbench  # noqa: F401  (triggers sys.path bootstrap)
    from exp_graph.runner import SynchronousRunner  # noqa: F401
    from exp_graph.tasks.base import TaskAdapter  # noqa: F401


def test_masbench_version_present():
    import masbench

    assert isinstance(masbench.__version__, str)
