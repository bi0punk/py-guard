import json
import os
from parser import (
    AccessEvent,
    ErrorEvent,
    LogAnalyzer,
    load_summary,
    save_summary,
)


class TestAccessPatterns:
    def test_common_log_format(self, analyzer):
        line = '192.168.1.10 - - [09/Apr/2026:10:15:03 +0000] "GET /login HTTP/1.1" 200 532'
        event = analyzer._parse_access_line(line)
        assert event is not None
        assert event.ip == "192.168.1.10"
        assert event.method == "GET"
        assert event.path == "/login"
        assert event.status == 200
        assert event.timestamp is not None

    def test_django_dev_format(self, analyzer):
        line = '[09/Apr/2026 10:16:11] "GET /health HTTP/1.1" 200 15'
        event = analyzer._parse_access_line(line)
        assert event is not None
        assert event.method == "GET"
        assert event.path == "/health"
        assert event.status == 200

    def test_uvicorn_like_format(self, analyzer):
        line = '192.168.1.10:8080 - "GET /api/test HTTP/1.1" 200'
        event = analyzer._parse_access_line(line)
        assert event is not None
        assert event.method == "GET"
        assert event.path == "/api/test"
        assert event.status == 200

    def test_no_match_returns_none(self, analyzer):
        line = "this is not a log line"
        assert analyzer._parse_access_line(line) is None

    def test_empty_line(self, analyzer):
        assert analyzer._parse_access_line("") is None


class TestErrorPatterns:
    def test_error_level_line(self, analyzer):
        line = "2026-04-09 10:16:13,101 ERROR django.request Internal Server Error: /api/orders/125"
        event = analyzer._parse_error_line(line)
        assert event is not None
        assert event.kind == "error"
        assert "Internal Server Error" in event.message
        assert event.path_hint == "/api/orders/125"
        assert event.timestamp is not None

    def test_critical_level_line(self, analyzer):
        line = "2026-04-09 10:17:00,001 CRITICAL app.db Database timeout"
        event = analyzer._parse_error_line(line)
        assert event is not None
        assert event.kind == "error"

    def test_normal_line_no_error_keyword(self, analyzer):
        line = '192.168.1.1 - - [10/May/2026:12:00:00 +0000] "GET / HTTP/1.1" 200 100'
        assert analyzer._parse_error_line(line) is None

    def test_exception_keyword(self, analyzer):
        line = "Some Exception: happened"
        event = analyzer._parse_error_line(line)
        assert event is not None

    def test_normal_line_returns_none(self, analyzer):
        line = '192.168.1.1 - - [10/May/2026:12:00:00 +0000] "GET / HTTP/1.1" 200 100'
        assert analyzer._parse_error_line(line) is None

    def test_blank_line_returns_none(self, analyzer):
        assert analyzer._parse_error_line("") is None
        assert analyzer._parse_error_line("   ") is None


class TestTimestampParsing:
    def test_common_log_timestamp(self, analyzer):
        result = analyzer.parse_timestamp("09/Apr/2026:10:15:03 +0000")
        assert result is not None
        assert "2026-04-09T10:15:03" in result

    def test_iso_timestamp(self, analyzer):
        result = analyzer.parse_timestamp("2026-04-09 10:16:13,101")
        assert result is not None
        assert "2026-04-09T10:16:13" in result

    def test_django_dev_timestamp(self, analyzer):
        result = analyzer.parse_timestamp("09/Apr/2026 10:16:11")
        assert result is not None
        assert "2026-04-09T10:16:11" in result

    def test_none_returns_none(self, analyzer):
        assert analyzer.parse_timestamp(None) is None

    def test_empty_returns_none(self, analyzer):
        assert analyzer.parse_timestamp("") is None

    def test_garbage_returns_none(self, analyzer):
        assert analyzer.parse_timestamp("not-a-timestamp") is None


class TestPathNormalization:
    def test_plain_path(self, analyzer):
        assert analyzer.normalize_path("/dashboard") == "/dashboard"

    def test_path_with_numeric_segment(self, analyzer):
        assert analyzer.normalize_path("/api/orders/123") == "/api/orders/<num>"

    def test_path_with_multiple_numerics(self, analyzer):
        result = analyzer.normalize_path("/admin/users/899/profile")
        assert result == "/admin/users/<num>/profile"

    def test_path_with_uuid(self, analyzer):
        result = analyzer.normalize_path("/api/users/a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
        assert result == "/api/users/<uuid>"

    def test_path_with_query_string(self, analyzer):
        result = analyzer.normalize_path("/search?q=test&page=1")
        assert result == "/search"

    def test_root_path(self, analyzer):
        assert analyzer.normalize_path("/") == "/"


class TestErrorNormalization:
    def test_ip_replacement(self, analyzer):
        result = analyzer.normalize_error_message("Login failed from 192.168.1.10")
        assert "<ip>" in result
        assert "192.168.1.10" not in result

    def test_uuid_replacement(self, analyzer):
        result = analyzer.normalize_error_message("User a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d not found")
        assert "<uuid>" in result

    def test_number_replacement(self, analyzer):
        result = analyzer.normalize_error_message("Error code 42 occurred")
        assert "<num>" in result
        assert "42" not in result

    def test_quoted_string_replacement(self, analyzer):
        result = analyzer.normalize_error_message('File "/tmp/test.txt" not found')
        assert '"<text>"' in result

    def test_truncation(self, analyzer):
        long_msg = "x" * 300
        result = analyzer.normalize_error_message(long_msg)
        assert len(result) == 250

    def test_empty_message(self, analyzer):
        assert analyzer.normalize_error_message("") == ""


class TestTracebackParsing:
    def test_traceback_collected_as_single_error(self, analyzer):
        tb_lines = [
            "Traceback (most recent call last):",
            '  File "/app/views.py", line 40, in post',
            '    raise ValueError("invalid payload")',
            "ValueError: invalid payload",
        ]
        analyzer._flush_traceback(tb_lines)
        assert len(analyzer.error_events) == 1
        event = analyzer.error_events[0]
        assert "ValueError: invalid payload" in event.message
        assert event.kind == "error"

    def test_traceback_boundary_detection(self, analyzer):
        tb = [
            "Traceback (most recent call last):",
            '  File "x.py", line 1',
            "ValueError: test",
        ]
        analyzer._flush_traceback(tb)
        assert len(analyzer.error_events) == 1

    def test_empty_traceback_no_error(self, analyzer):
        analyzer._flush_traceback([])
        assert len(analyzer.error_events) == 0


class TestFullFileParsing:
    def test_parse_sample_log(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])

        assert result["summary"]["total_lines"] == 19
        assert result["summary"]["access_events"] == 12
        assert result["summary"]["error_events"] == 4
        assert result["summary"]["unparsed_lines"] == 0

    def test_top_ips(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])
        top_ips = {item["ip"]: item["count"] for item in result["top_ips"]}
        assert top_ips["192.168.1.10"] == 4
        assert top_ips["192.168.1.12"] == 2

    def test_top_paths(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])
        paths = {item["path"]: item["count"] for item in result["top_paths"]}
        assert paths["/dashboard"] == 3
        assert paths["/api/orders/<num>"] == 3

    def test_error_rate(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])
        assert result["summary"]["error_rate_pct"] == pytest.approx(21.05, rel=0.1)

    def test_parse_empty_file(self, tmp_path, analyzer):
        empty_file = tmp_path / "empty.log"
        empty_file.write_text("", encoding="utf-8")
        result = analyzer.parse_files([str(empty_file)])
        assert result["summary"]["total_lines"] == 0
        assert result["summary"]["access_events"] == 0
        assert result["summary"]["error_events"] == 0

    def test_parse_unparseable_lines(self, tmp_path, analyzer):
        f = tmp_path / "bad.log"
        f.write_text("foo\nbar\nbaz\n", encoding="utf-8")
        result = analyzer.parse_files([str(f)])
        assert result["summary"]["total_lines"] == 3
        assert result["summary"]["unparsed_lines"] == 3


class TestHourlyActivity:
    def test_hour_bucket_with_valid(self, analyzer):
        assert analyzer._hour_bucket("2026-04-09T10:15:03") == "2026-04-09 10:00"

    def test_hour_bucket_with_none(self, analyzer):
        assert analyzer._hour_bucket(None) == "unknown"

    def test_hour_bucket_with_invalid(self, analyzer):
        assert analyzer._hour_bucket("garbage") == "unknown"


class TestSaveLoadSummary:
    def test_save_and_load_roundtrip(self, tmp_path):
        data = {"analysis_id": "test-123", "summary": {"total_lines": 10}}
        path = save_summary(str(tmp_path), data)
        assert os.path.exists(path)
        loaded = load_summary(str(tmp_path), "test-123")
        assert loaded == data

    def test_load_nonexistent(self, tmp_path):
        assert load_summary(str(tmp_path), "nonexistent") is None


class TestIPStatusMatrix:
    def test_matrix_counts(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])
        matrix = result["ip_status_matrix"]
        assert len(matrix) > 0
        ip_10 = next(item for item in matrix if item["ip"] == "192.168.1.10")
        assert ip_10["total"] == 4
        assert ip_10["2xx"] == 3
        assert ip_10["5xx"] == 1


class TestRouteStatusMatrix:
    def test_route_matrix(self, sample_log_file, analyzer):
        result = analyzer.parse_files([sample_log_file])
        matrix = result["route_status_matrix"]
        dashboard = next(item for item in matrix if item["path"] == "/dashboard")
        assert dashboard["total"] == 3
        assert dashboard["2xx"] == 3
import pytest
