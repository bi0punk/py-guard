import pytest
from parser import LogAnalyzer


@pytest.fixture
def analyzer():
    return LogAnalyzer()


@pytest.fixture
def sample_log_content():
    return """\
192.168.1.10 - - [09/Apr/2026:10:15:03 +0000] "GET /login HTTP/1.1" 200 532
192.168.1.10 - - [09/Apr/2026:10:15:04 +0000] "POST /api/auth HTTP/1.1" 500 221
192.168.1.11 - - [09/Apr/2026:10:15:05 +0000] "GET /dashboard HTTP/1.1" 200 1032
192.168.1.12 - - [09/Apr/2026:10:15:06 +0000] "GET /api/orders/123 HTTP/1.1" 200 774
192.168.1.12 - - [09/Apr/2026:10:15:07 +0000] "GET /api/orders/124 HTTP/1.1" 404 122
192.168.1.15 - - [09/Apr/2026:10:16:01 +0000] "GET /admin/users/899/profile HTTP/1.1" 200 390
192.168.1.15 - - [09/Apr/2026:10:16:07 +0000] "GET /admin/users/900/profile HTTP/1.1" 200 390
[09/Apr/2026 10:16:11] "GET /health HTTP/1.1" 200 15
[09/Apr/2026 10:16:12] "GET /api/orders/125 HTTP/1.1" 500 0
2026-04-09 10:16:13,101 ERROR django.request Internal Server Error: /api/orders/125
2026-04-09 10:16:13,103 ERROR app.auth Login failed for user id=44 from 192.168.1.10
Traceback (most recent call last):
  File "/app/views.py", line 40, in post
    raise ValueError("invalid payload")
ValueError: invalid payload
2026-04-09 10:17:00,001 CRITICAL app.db Database timeout for tenant=acme request=1299
192.168.1.10 - - [09/Apr/2026:10:18:03 +0000] "GET /dashboard HTTP/1.1" 200 1001
192.168.1.10 - - [09/Apr/2026:10:18:04 +0000] "GET /dashboard HTTP/1.1" 200 1001
192.168.1.13 - - [09/Apr/2026:10:18:04 +0000] "GET /favicon.ico HTTP/1.1" 404 43
"""


@pytest.fixture
def sample_log_file(tmp_path, sample_log_content):
    log_file = tmp_path / "test.log"
    log_file.write_text(sample_log_content, encoding="utf-8")
    return str(log_file)
