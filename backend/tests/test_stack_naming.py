import re

from stack_generator.naming import app_id_for, app_slug_from_prompt


def test_app_id_for() -> None:
    assert (
        app_id_for("run_20261008_101500_ab12cd34", 0)
        == "run-20261008-101500-ab12cd34-op1"
    )

    long_id = app_id_for("run_" + "X" * 196, 0)
    assert re.match(r"^[a-z0-9-]{1,63}$", long_id)
    assert long_id.endswith("-op1")


def test_app_slug_from_prompt() -> None:
    run_id = "run_20261008_101500_ab12cd34"

    assert (
        app_slug_from_prompt("Build me a Coffee Shop landing page!!", run_id)
        == "coffee-shop-landing-page"
    )
    assert app_slug_from_prompt("", run_id) == "app-ab12cd34"
    assert app_slug_from_prompt("Please make a", run_id) == "app-ab12cd34"
    assert len(app_slug_from_prompt("word " * 50, run_id)) <= 40
