"""
Tests for TradeAgent graph binding.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.subagents.trade.agent import TradeAgent


class TestTradeAgent:
    @pytest.mark.asyncio
    async def test_trade_agent_uses_agent_first_graph(self):
        mock_db = AsyncMock()
        with patch(
            "app.agents.subagents.trade.agent.create_agent_first_trade_graph"
        ) as mock_create_graph, patch.object(
            TradeAgent, "_init_skills", return_value={"pricing": AsyncMock()}
        ):
            mock_graph = AsyncMock()
            mock_create_graph.return_value = mock_graph

            agent = TradeAgent(mock_db)

            mock_create_graph.assert_called_once_with(mock_db, agent.skills)
            assert agent.graph == mock_graph
