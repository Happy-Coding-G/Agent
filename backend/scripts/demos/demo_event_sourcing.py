"""
事件溯源 + 状态投影 效果演示

这个脚本展示了我们交易系统的核心机制：
1. 如何追加事件
2. 如何投影状态
3. 如何重放历史
4. 如何检测异常
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


# ============================================================================
# 模拟数据模型
# ============================================================================

@dataclass
class Event:
    """事件"""
    sequence: int
    event_type: str
    agent_id: int
    agent_role: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NegotiationState:
    """投影状态"""
    session_id: str
    current_round: int = 0
    current_price: Optional[float] = None
    status: str = "pending"
    buyer_id: int = 0
    seller_id: int = 0
    current_turn: str = "seller"
    history: List[Dict] = field(default_factory=list)
    version: int = 0

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "round": self.current_round,
            "price": f"¥{self.current_price:.2f}" if self.current_price else None,
            "status": self.status,
            "turn": self.current_turn,
            "version": self.version,
            "history_count": len(self.history),
        }


# ============================================================================
# 模拟事件存储
# ============================================================================

class MockEventStore:
    """模拟事件存储"""

    def __init__(self):
        self.events: List[Event] = []
        self._seq = 0

    def append(self, event_type: str, agent_id: int, agent_role: str, payload: Dict) -> Event:
        self._seq += 1
        event = Event(
            sequence=self._seq,
            event_type=event_type,
            agent_id=agent_id,
            agent_role=agent_role,
            payload=payload,
        )
        self.events.append(event)
        return event

    def get_events(self, start_seq: int = 0) -> List[Event]:
        return [e for e in self.events if e.sequence >= start_seq]


# ============================================================================
# 状态投影器
# ============================================================================

class StateProjector:
    """状态投影器 - 核心组件"""

    def project(self, session_id: str, events: List[Event]) -> NegotiationState:
        """将事件流折叠为当前状态"""
        state = NegotiationState(session_id=session_id)

        for event in events:
            state = self._apply(state, event)

        return state

    def _apply(self, state: NegotiationState, event: Event) -> NegotiationState:
        """应用单个事件"""
        payload = event.payload

        if event.event_type == "INITIATE":
            state.buyer_id = event.agent_id
            state.status = "pending"
            state.history.append({
                "round": 0,
                "event": "INITIATE",
                "by": "buyer",
                "message": payload.get("message", ""),
            })

        elif event.event_type == "ANNOUNCE":
            state.seller_id = event.agent_id
            state.current_price = payload.get("price", 0)
            state.status = "active"
            state.current_round = 1
            state.current_turn = "buyer"
            state.history.append({
                "round": 1,
                "event": "ANNOUNCE",
                "by": "seller",
                "price": state.current_price,
            })

        elif event.event_type == "OFFER":
            state.current_price = payload.get("price", 0)
            state.current_round += 1
            state.current_turn = "buyer" if event.agent_role == "seller" else "seller"
            state.history.append({
                "round": state.current_round,
                "event": "OFFER",
                "by": event.agent_role,
                "price": state.current_price,
            })

        elif event.event_type == "COUNTER":
            state.current_price = payload.get("counter_price", 0)
            state.current_round += 1
            state.current_turn = "buyer" if event.agent_role == "seller" else "seller"
            state.history.append({
                "round": state.current_round,
                "event": "COUNTER",
                "by": event.agent_role,
                "price": state.current_price,
            })

        elif event.event_type == "ACCEPT":
            state.status = "agreed"
            state.current_turn = None
            state.history.append({
                "round": state.current_round,
                "event": "ACCEPT",
                "by": event.agent_role,
                "final_price": state.current_price,
            })

        elif event.event_type == "REJECT":
            state.status = "rejected"
            state.current_turn = None
            state.history.append({
                "round": state.current_round,
                "event": "REJECT",
                "by": event.agent_role,
            })

        state.version = event.sequence
        return state


# ============================================================================
# 演示场景
# ============================================================================

def print_section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_events(events: List[Event]):
    """打印事件流"""
    print("\n[事件流] Event Stream:")
    print("-" * 70)
    print(f"{'Seq':<5} {'Time':<12} {'Type':<12} {'Agent':<8} {'Role':<8} Payload")
    print("-" * 70)

    for e in events:
        time_str = e.timestamp.strftime("%H:%M:%S.%f")[:-3]
        payload_str = str(e.payload)[:40] + "..." if len(str(e.payload)) > 40 else str(e.payload)
        print(f"{e.sequence:<5} {time_str:<12} {e.event_type:<12} {e.agent_id:<8} {e.agent_role:<8} {payload_str}")


def print_state(state: NegotiationState):
    """打印投影状态"""
    print("\n[投影状态] Projected State:")
    print("-" * 70)
    print(f"  Session ID: {state.session_id}")
    print(f"  Status:     {state.status.upper()}")
    print(f"  Round:      {state.current_round}")
    print(f"  Price:      CNY {state.current_price:.2f}" if state.current_price else "  Price:      N/A")
    print(f"  Turn:       {state.current_turn}")
    print(f"  Version:    {state.version}")
    print(f"  History:    {len(state.history)} events")
    print("-" * 70)


def print_history(state: NegotiationState):
    """打印历史记录"""
    print("\n[协商历史]")
    for h in state.history:
        if "price" in h:
            print(f"   Round {h['round']}: [{h['event']}] by {h['by']} - CNY {h['price']:.2f}")
        else:
            print(f"   Round {h['round']}: [{h['event']}] by {h['by']}")


def demo_basic_flow():
    """演示基本流程"""
    print_section("场景1: 标准协商流程（买卖双方讨价还价）")

    store = MockEventStore()
    projector = StateProjector()
    session_id = "NEG-2024-001"

    # 模拟协商过程
    print("\n[模拟协商过程]\n")

    # Buyer 发起协商
    print("[1] Buyer (ID:101) 发起协商，预算 CNY 1000")
    store.append("INITIATE", 101, "buyer", {"max_budget": 1000, "message": "想购买数据集"})

    # Seller 发布公告
    print("[2] Seller (ID:202) 发布公告，报价 CNY 800")
    store.append("ANNOUNCE", 202, "seller", {"price": 800.0, "asset": "用户行为数据集"})

    # Buyer 觉得贵，出价 CNY 500
    print("[3] Buyer 还价 CNY 500")
    store.append("OFFER", 101, "buyer", {"price": 500.0, "message": "预算有限"})

    # Seller 反报价 CNY 650
    print("[4] Seller 反报价 CNY 650")
    store.append("COUNTER", 202, "seller", {"counter_price": 650.0, "message": "最低价格"})

    # Buyer 接受
    print("[5] Buyer 接受报价")
    store.append("ACCEPT", 101, "buyer", {"agreed_price": 650.0})

    # 展示结果
    print_events(store.events)

    state = projector.project(session_id, store.events)
    print_state(state)
    print_history(state)

    return store, state


def demo_replay(store: MockEventStore):
    """演示历史重放"""
    print_section("场景2: 历史状态重放（审计/回溯）")

    projector = StateProjector()
    session_id = "NEG-2024-001"

    print("\n[重放] 重放到 Round 2（Buyer 出价后）:")
    events_to_round2 = store.events[:3]  # 只取前3个事件
    state_at_round2 = projector.project(session_id, events_to_round2)
    print_state(state_at_round2)

    print("\n[重放] 重放到 Round 3（Seller 反报价后）:")
    events_to_round3 = store.events[:4]
    state_at_round3 = projector.project(session_id, events_to_round3)
    print_state(state_at_round3)

    print("\n[重放] 重放完整流程:")
    final_state = projector.project(session_id, store.events)
    print_state(final_state)


def demo_audit_trail(store: MockEventStore):
    """演示审计追踪"""
    print_section("场景3: 完整审计追踪")

    print("\n[审计] 审计优势展示:\n")

    print("1. 不可篡改历史:")
    print("   - 每个事件有序列号 (1, 2, 3, 4, 5)")
    print("   - 事件一旦写入不可修改")
    print("   - 可以验证状态计算的准确性")

    print("\n2. 时间线重建:")
    for e in store.events:
        print(f"   [{e.sequence}] {e.timestamp.strftime('%H:%M:%S')} - {e.event_type}")

    print("\n3. 参与方行为分析:")
    agent_events = {}
    for e in store.events:
        agent_events[e.agent_id] = agent_events.get(e.agent_id, 0) + 1
    for agent_id, count in agent_events.items():
        print(f"   Agent {agent_id}: {count} 次操作")


def demo_comparison():
    """对比传统 CRUD 与事件溯源"""
    print_section("场景4: 架构对比")

    print("""
┌─────────────────────────────────────────────────────────────────────┐
│                    传统 CRUD 方式                                    │
├─────────────────────────────────────────────────────────────────────┤
│  数据库状态:                                                        │
│    negotiation: { id: "NEG-001", price: 650, status: "agreed" }     │
│                                                                     │
│  问题:                                                              │
│    ❌ 不知道价格是如何从 800 → 500 → 650 变化的                      │
│    ❌ 无法判断是谁先出价                                             │
│    ❌ 数据被覆盖，历史丢失                                           │
│    ❌ 审计时无法重建决策过程                                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    事件溯源方式                                      │
├─────────────────────────────────────────────────────────────────────┤
│  事件流:                                                            │
│    [1] INITIATE  → Buyer 发起                                       │
│    [2] ANNOUNCE  → Seller 报价 800                                  │
│    [3] OFFER     → Buyer 出价 500                                   │
│    [4] COUNTER   → Seller 反报 650                                  │
│    [5] ACCEPT    → Buyer 接受                                       │
│                                                                     │
│  优势:                                                              │
│    ✅ 完整历史保留，支持任意时刻状态重建                             │
│    ✅ 天然审计日志，满足合规要求                                     │
│    ✅ 可以发现异常模式（如抢先交易）                                 │
│    ✅ 支持时序分析和行为模式挖掘                                     │
│    ✅ 易于调试，可以逐步回放问题发生过程                             │
└─────────────────────────────────────────────────────────────────────┘
    """)


def main():
    """主函数"""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "事件溯源 + 状态投影 架构演示" + " " * 21 + "║")
    print("╚" + "═" * 68 + "╝")

    # 场景1: 基本流程
    store, final_state = demo_basic_flow()

    # 场景2: 历史重放
    demo_replay(store)

    # 场景3: 审计追踪
    demo_audit_trail(store)

    # 场景4: 架构对比
    demo_comparison()

    # 总结
    print_section("总结")
    print("""
[总结] 事件溯源 + 状态投影的核心价值:

1. 数据完整性 (Data Integrity)
   - 所有变更都有迹可循，不可篡改

2. 时序分析 (Temporal Analysis)
   - 可以重放任意历史时刻的状态
   - 支持"时间旅行"调试

3. 审计合规 (Audit Compliance)
   - 天然满足金融级审计要求
   - 每笔交易都有完整上下文

4. 扩展性 (Extensibility)
   - 新增投影视图无需修改事件
   - 可以从同一事件流构建不同视图

5. 冲突解决 (Conflict Resolution)
   - 通过版本号检测并发冲突
   - 支持乐观锁和序列化写入
    """)


if __name__ == "__main__":
    main()
