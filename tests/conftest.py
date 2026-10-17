"""One clean real deployment per run; fresh accounts per test."""

import pytest
from tests.tools.deployment import Deployment
from tests.tools.users import Student


@pytest.fixture(scope="session", autouse=True)
def deployment(request):
    stack = Deployment()
    try:
        stack.start()
        yield stack
    finally:
        if request.session.testsfailed:
            print(stack.logs())
        stack.close()


@pytest.fixture
def users(deployment, tmp_path):
    created = []

    def create(**kwargs):
        directory = tmp_path / str(len(created))
        directory.mkdir()
        user = Student(deployment, directory, **kwargs)
        created.append(user)
        return user

    yield create
    for user in reversed(created):
        user.close()
