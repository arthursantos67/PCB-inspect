from fastapi.testclient import TestClient

from app.main import app


def test_openapi_schema_reachable() -> None:
    client = TestClient(app)
    response = client.get("/api/schema")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "PCB-Inspect"


def test_docs_reachable() -> None:
    client = TestClient(app)
    response = client.get("/api/docs")
    assert response.status_code == 200
