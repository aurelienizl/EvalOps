"""Small HTTP client for the real backend, including negative assertions."""

import httpx


class Api:
    def __init__(self, url):
        self.client = httpx.Client(base_url=url, timeout=20, trust_env=False)
        self.cookie = ""

    def request(self, method, path, *, expected=200, **kwargs):
        path = path if path.startswith("/api/") else "/api/v1" + path
        headers = {"Cookie": self.cookie} if self.cookie else {}
        response = self.client.request(method, path, headers=headers, **kwargs)
        allowed = expected if isinstance(expected, tuple) else (expected,)
        assert response.status_code in allowed, (
            f"{method} {path}: {response.status_code} {response.text[:800]}"
        )
        return response

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def login(self, email, password):
        response = self.post("/auth/login", json={"email": email, "password": password})
        # Tests reach the internal HTTP service directly, even with COOKIE_SECURE=true.
        self.cookie = "; ".join(f"{key}={value}" for key, value in response.cookies.items())
        return response

    def close(self):
        self.client.close()
