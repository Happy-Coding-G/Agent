"""
Tests for lineage API endpoints using AssetLineagePricingService.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.api.deps.auth import get_current_user, get_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def override_dependencies():
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.is_admin = True

    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.clear()


class TestLineageAPI:
    def test_get_lineage_returns_correct_structure(self, client, override_dependencies):
        """GET /lineage/{type}/{id} 返回正确结构。"""
        mock_graph = {
            "nodes": [
                {"id": "file:doc_1", "type": "file", "name": "doc_1"},
                {"id": "asset:ast_1", "type": "asset", "name": "ast_1"},
            ],
            "edges": [
                {"source": "file:doc_1", "target": "asset:ast_1", "relationship": "derived"},
            ],
            "total_confidence": 1.0,
        }

        with patch(
            "app.api.v1.endpoints.lineage.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.get_upstream_lineage.return_value = [mock_graph]
            mock_svc.get_downstream_lineage.return_value = []
            mock_svc_cls.return_value = mock_svc

            response = client.get("/api/v1/lineage/asset/ast_1?direction=both&max_depth=3")
            assert response.status_code == 200
            data = response.json()
            assert "upstream" in data
            assert data["upstream"][0]["confidence"] == 1.0

    def test_get_lineage_graph_edge_format(self, client, override_dependencies):
        """GET /lineage/{type}/{id}/graph 边字段为 source/target。"""
        mock_graph = {
            "nodes": [
                {"id": "asset:src_1", "type": "asset", "name": "src_1"},
                {"id": "asset:ast_1", "type": "asset", "name": "ast_1"},
            ],
            "edges": [
                {"source": "asset:src_1", "target": "asset:ast_1", "relationship": "derived"},
            ],
            "total_confidence": 1.0,
        }

        with patch(
            "app.api.v1.endpoints.lineage.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.get_lineage_graph.return_value = mock_graph
            mock_svc_cls.return_value = mock_svc

            response = client.get("/api/v1/lineage/asset/ast_1/graph?max_depth=3")
            assert response.status_code == 200
            data = response.json()
            assert "edges" in data
            assert data["edges"][0]["source"] == "asset:src_1"
            assert data["edges"][0]["target"] == "asset:ast_1"

    def test_get_impact_report(self, client, override_dependencies):
        """GET /lineage/{type}/{id}/impact 风险评分计算。"""
        mock_report = {
            "source": "asset:ast_1",
            "summary": {
                "total_affected": 2,
                "critical_paths": 0,
                "risk_score": 0.1,
                "risk_level": "low",
            },
            "affected_entities": [],
        }

        with patch(
            "app.api.v1.endpoints.lineage.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.get_impact_report.return_value = mock_report
            mock_svc_cls.return_value = mock_svc

            response = client.get("/api/v1/lineage/asset/ast_1/impact?max_depth=3")
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["risk_level"] == "low"
