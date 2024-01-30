import json
import os
from urllib.parse import (
    urlsplit,
)
import pytest
import requests
from dotenv import (
    load_dotenv,
)

load_dotenv()

TARGET_URL = os.getenv("TARGET_URL")
X_API_KEY = os.getenv("X_API_KEY")
os.environ["test_mode"] = "true"


@pytest.fixture(scope="session")
def make_request():
    def f(url, **options) -> requests.Response:
        target = urlsplit(TARGET_URL)
        url = f"{target.scheme}://{target.hostname}/{url}"
        headers = options.pop("headers", {})
        headers["x-api-key"] = X_API_KEY
        return requests.request(url=url, headers=headers, **options)

    return f
