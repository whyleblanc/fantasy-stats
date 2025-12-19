import os
import pytest

from webapp import create_app


@pytest.fixture(scope="session")
def app():
    # Ensure Flask is in testing mode
    os.environ["FLASK_ENV"] = "testing"

    app = create_app()
    app.config.update(
        TESTING=True,
    )
    return app


@pytest.fixture()
def client(app):
    return app.test_client()