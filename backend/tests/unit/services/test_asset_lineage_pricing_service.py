"""
Tests for AssetLineagePricingService.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.asset_lineage_pricing_service import (
    AssetLineagePricingService,
    BASE_PRICE_BY_TYPE,
    LINEAGE_HASH_VERSION,
)
from app.services.trade.data_rights_events import (
    DataSensitivityLevel,
    DataRightsType,
)
from app.db.models import DataLineageType


class TestLineage:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return AssetLineagePricingService(mock_db)

    @pytest.mark.asyncio
    async def test_record_lineage_and_query_graph(self, service, mock_db):
        """血缘写入后能查询图。"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        lineage = await service.record_lineage(
            source_type=DataLineageType.FILE,
            source_id="doc_1",
            current_entity_type=DataLineageType.ASSET,
            current_entity_id="ast_1",
            relationship="derived",
            user_id=1,
            space_id="sp_1",
        )
        assert lineage.lineage_id.startswith("lin_")
        mock_db.flush.assert_awaited()
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verify_integrity_no_lineage_returns_true(self, service, mock_db):
        """无血缘时完整性校验返回 True（安全 fallback）。"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        assert await service.verify_lineage_integrity("ast_1") is True

    @pytest.mark.asyncio
    async def test_verify_integrity_service_hash_returns_true(self, service, mock_db):
        """统一服务写入格式的 hash 应可通过完整性校验。"""
        mock_record = MagicMock()
        mock_record.source_type = "file"
        mock_record.source_id = "doc_1"
        mock_record.current_entity_type = "asset"
        mock_record.current_entity_id = "ast_1"
        mock_record.relationship = "derived"
        mock_record.transformation_logic = "normalize"
        mock_record.parent_hash = None
        mock_record.step_index = 0
        mock_record.extra_metadata = {
            "hash_version": LINEAGE_HASH_VERSION,
            "parent_hashes": [],
        }
        mock_record.lineage_hash = service._calculate_lineage_hash(
            source_type=mock_record.source_type,
            source_id=mock_record.source_id,
            current_entity_type=mock_record.current_entity_type,
            current_entity_id=mock_record.current_entity_id,
            relationship=mock_record.relationship,
            transformation_logic=mock_record.transformation_logic,
            parent_hashes=[],
            step_index=mock_record.step_index,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_db.execute.return_value = mock_result

        assert await service.verify_lineage_integrity("ast_1") is True

    @pytest.mark.asyncio
    async def test_verify_integrity_hash_mismatch_returns_false(self, service, mock_db):
        """hash 不匹配时返回 False。"""
        mock_record = MagicMock()
        mock_record.lineage_hash = "bad_hash"
        mock_record.relationship = "derived"
        mock_record.source_type = "file"
        mock_record.source_id = "doc_1"
        mock_record.current_entity_type = "asset"
        mock_record.current_entity_id = "ast_1"
        mock_record.transformation_logic = None
        mock_record.parent_hash = None
        mock_record.lineage_id = "lin_123"
        mock_record.confidence_score = 1.0
        mock_record.step_index = 0
        mock_record.extra_metadata = {"hash_version": LINEAGE_HASH_VERSION}

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_db.execute.return_value = mock_result

        assert await service.verify_lineage_integrity("ast_1") is False


class TestPricing:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return AssetLineagePricingService(mock_db)

    def _make_asset(self, **kwargs):
        asset = MagicMock()
        asset.asset_id = kwargs.get("asset_id", "ast_1")
        asset.data_type = kwargs.get("data_type", "generic")
        asset.quality_overall_score = kwargs.get("quality_overall_score", 0.5)
        asset.quality_completeness = kwargs.get("quality_completeness", 0.5)
        asset.quality_accuracy = kwargs.get("quality_accuracy", 0.5)
        asset.quality_timeliness = kwargs.get("quality_timeliness", 0.5)
        asset.quality_consistency = kwargs.get("quality_consistency", 0.5)
        asset.quality_uniqueness = kwargs.get("quality_uniqueness", 0.5)
        asset.sensitivity_level = kwargs.get("sensitivity_level", DataSensitivityLevel.MEDIUM)
        asset.record_count = kwargs.get("record_count", 0)
        asset.data_size_bytes = kwargs.get("data_size_bytes", 0)
        asset.is_active = kwargs.get("is_active", True)
        asset.is_available_for_trade = kwargs.get("is_available_for_trade", True)
        return asset

    @pytest.mark.asyncio
    async def test_price_fallback_without_lineage(self, service, mock_db):
        """无血缘时 lineage_multiplier = 0.9。"""
        asset = self._make_asset(data_type="generic")

        with patch.object(service, "_get_asset", return_value=asset):
            with patch.object(service, "verify_lineage_integrity", return_value=True):
                with patch.object(service, "get_upstream_lineage", return_value=[]):
                    with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                        pricing = await service.calculate_price("ast_1")

        assert pricing.factors.lineage_multiplier == 0.9

    @pytest.mark.asyncio
    async def test_quality_higher_price_higher(self, service, mock_db):
        """质量越高，价格越高。"""
        asset_low = self._make_asset(quality_overall_score=0.2)
        asset_high = self._make_asset(quality_overall_score=0.9)

        for asset in [asset_low, asset_high]:
            with patch.object(service, "_get_asset", return_value=asset):
                with patch.object(service, "verify_lineage_integrity", return_value=True):
                    with patch.object(service, "get_upstream_lineage", return_value=[]):
                        with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                            if asset == asset_low:
                                pricing_low = await service.calculate_price("ast_1")
                            else:
                                pricing_high = await service.calculate_price("ast_1")

        assert pricing_high.fair_value > pricing_low.fair_value

    @pytest.mark.asyncio
    async def test_integrity_failure_reduces_price(self, service, mock_db):
        """完整性失败 → lineage_multiplier = 0.7。"""
        asset = self._make_asset()

        with patch.object(service, "_get_asset", return_value=asset):
            with patch.object(service, "verify_lineage_integrity", return_value=False):
                with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                    pricing = await service.calculate_price("ast_1")

        assert pricing.factors.lineage_multiplier == 0.7

    @pytest.mark.asyncio
    async def test_rights_scope_affects_price(self, service, mock_db):
        """权益范围影响价格。"""
        asset = self._make_asset()

        with patch.object(service, "_get_asset", return_value=asset):
            with patch.object(service, "verify_lineage_integrity", return_value=True):
                with patch.object(service, "get_upstream_lineage", return_value=[]):
                    with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                        pricing_minimal = await service.calculate_price(
                            "ast_1", rights_types=["view"]
                        )
                        pricing_full = await service.calculate_price(
                            "ast_1", rights_types=["view", "download", "derivative", "sub_license"]
                        )

        assert pricing_full.fair_value > pricing_minimal.fair_value

    @pytest.mark.asyncio
    async def test_sensitivity_discount(self, service, mock_db):
        """敏感度折扣。"""
        asset_critical = self._make_asset(sensitivity_level=DataSensitivityLevel.CRITICAL)
        asset_low = self._make_asset(sensitivity_level=DataSensitivityLevel.LOW)

        for asset in [asset_critical, asset_low]:
            with patch.object(service, "_get_asset", return_value=asset):
                with patch.object(service, "verify_lineage_integrity", return_value=True):
                    with patch.object(service, "get_upstream_lineage", return_value=[]):
                        with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                            if asset == asset_critical:
                                pricing_critical = await service.calculate_price("ast_1")
                            else:
                                pricing_low = await service.calculate_price("ast_1")

        assert pricing_critical.factors.sensitivity_multiplier == 0.5
        assert pricing_low.factors.sensitivity_multiplier == 1.0
        assert pricing_low.fair_value > pricing_critical.fair_value

    @pytest.mark.asyncio
    async def test_computation_cost_additive(self, service, mock_db):
        """计算成本加成。"""
        asset = self._make_asset(data_type="generic")

        with patch.object(service, "_get_asset", return_value=asset):
            with patch.object(service, "verify_lineage_integrity", return_value=True):
                with patch.object(service, "get_upstream_lineage", return_value=[]):
                    with patch.object(service, "_calculate_scarcity_multiplier", return_value=1.0):
                        pricing_raw = await service.calculate_price(
                            "ast_1", computation_method="raw_data"
                        )
                        pricing_mpc = await service.calculate_price(
                            "ast_1", computation_method="mpc"
                        )

        assert pricing_mpc.factors.computation_cost > pricing_raw.factors.computation_cost
        assert pricing_mpc.fair_value > pricing_raw.fair_value
