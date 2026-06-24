import json
import os
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = "/tmp/test-uploads"
    with app.test_client() as client:
        yield client


class TestRoutes:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json == {"status": "ok"}

    def test_analyze_without_files(self, client):
        resp = client.post("/analyze", data={})
        assert resp.status_code == 400

    def test_analyze_with_invalid_extension(self, client, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b,c\n")
        with open(str(f), "rb") as fp:
            resp = client.post(
                "/analyze",
                data={"log_files": (fp, "test.csv")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400

    def test_analyze_with_valid_log(self, client, tmp_path):
        f = tmp_path / "test.log"
        f.write_text('192.168.1.1 - - [09/Apr/2026:10:15:03 +0000] "GET / HTTP/1.1" 200 100\n')
        with open(str(f), "rb") as fp:
            resp = client.post(
                "/analyze",
                data={"log_files": (fp, "test.log")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 302

    def test_nonexistent_report_returns_404(self, client):
        resp = client.get("/report/nonexistent-id")
        assert resp.status_code == 404

    def test_api_nonexistent_report_returns_404(self, client):
        resp = client.get("/api/report/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json == {"error": "analysis not found"}
