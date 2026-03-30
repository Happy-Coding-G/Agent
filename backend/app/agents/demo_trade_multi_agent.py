"""
Trade Multi-Agent System Demo

演示 LangGraph 多 Agent 分布式协商架构的工作流程。
"""
import asyncio
from datetime import datetime, timezone

# 模拟状态
class DemoTradeState:
    def __init__(self):
        self.negotiation_id = f"demo_{datetime.now().strftime('%H%M%S')}"
        self.messages = []
        self.round = 0
        self.status = "init"
        self.seller_price = 100.0
        self.buyer_price = 80.0
        self.agreed_price = None

    def log(self, agent: str, action: str, details: str):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{agent:12s}] {action:15s} | {details}")


async def seller_agent(state: DemoTradeState) -> DemoTradeState:
    """Seller Agent: 制定策略和决策"""
    state.log("SellerAgent", "PROCESS", f"当前报价: ${state.seller_price}")

    if state.status == "init":
        # 初始公告
        state.log("SellerAgent", "ANNOUNCE", f"资产上架，底价: ${state.seller_price}")
        state.messages.append({
            "from": "seller",
            "to": "buyer",
            "type": "ANNOUNCE",
            "price": state.seller_price
        })
        state.status = "announced"

    elif state.status == "offer_received":
        # 评估买方出价
        offer = state.buyer_price
        state.log("SellerAgent", "EVALUATE", f"收到出价: ${offer}")

        if offer >= state.seller_price * 0.95:
            # 接受
            state.log("SellerAgent", "DECISION", "接受出价")
            state.messages.append({
                "from": "seller",
                "to": "buyer",
                "type": "ACCEPT",
                "price": offer
            })
            state.agreed_price = offer
            state.status = "agreed"
        elif offer >= state.seller_price * 0.8:
            # 反报价
            counter = (offer + state.seller_price) / 2
            state.seller_price = counter
            state.log("SellerAgent", "DECISION", f"反报价: ${counter:.2f}")
            state.messages.append({
                "from": "seller",
                "to": "buyer",
                "type": "COUNTER",
                "price": counter
            })
            state.status = "countered"
        else:
            # 拒绝
            state.log("SellerAgent", "DECISION", "出价过低，拒绝")
            state.status = "rejected"

    return state


async def buyer_agent(state: DemoTradeState) -> DemoTradeState:
    """Buyer Agent: 评估和出价"""
    state.log("BuyerAgent", "PROCESS", f"当前预算: ${state.buyer_price}")

    # 处理卖方消息
    for msg in state.messages:
        if msg["to"] == "buyer" and msg.get("handled") is None:
            msg["handled"] = True

            if msg["type"] == "ANNOUNCE":
                price = msg["price"]
                state.log("BuyerAgent", "RECEIVE", f"收到公告，价格: ${price}")

                if price <= state.buyer_price * 1.2:
                    # 接受价格，直接出价
                    bid = min(price * 0.9, state.buyer_price)
                    state.buyer_price = bid
                    state.log("BuyerAgent", "BID", f"出价: ${bid:.2f}")
                    state.messages.append({
                        "from": "buyer",
                        "to": "seller",
                        "type": "OFFER",
                        "price": bid
                    })
                    state.status = "offer_sent"
                else:
                    state.log("BuyerAgent", "SKIP", "价格超出预算")
                    state.status = "skipped"

            elif msg["type"] == "COUNTER":
                counter_price = msg["price"]
                state.log("BuyerAgent", "RECEIVE", f"收到反报价: ${counter_price:.2f}")

                if counter_price <= state.buyer_price * 1.1:
                    # 接受反报价
                    state.buyer_price = counter_price
                    state.log("BuyerAgent", "DECISION", "接受反报价")
                    state.messages.append({
                        "from": "buyer",
                        "to": "seller",
                        "type": "ACCEPT",
                        "price": counter_price
                    })
                    state.agreed_price = counter_price
                    state.status = "agreed"
                elif state.round < 5:
                    # 继续协商
                    new_offer = (counter_price + state.buyer_price) / 2
                    state.buyer_price = new_offer
                    state.log("BuyerAgent", "DECISION", f"继续出价: ${new_offer:.2f}")
                    state.messages.append({
                        "from": "buyer",
                        "to": "seller",
                        "type": "OFFER",
                        "price": new_offer
                    })
                    state.status = "offer_sent"
                else:
                    state.log("BuyerAgent", "QUIT", "达到最大轮数")
                    state.status = "terminated"

            elif msg["type"] == "ACCEPT":
                state.agreed_price = msg["price"]
                state.log("BuyerAgent", "SUCCESS", f"交易达成: ${state.agreed_price:.2f}")
                state.status = "settled"

    return state


async def orchestrator(state: DemoTradeState) -> DemoTradeState:
    """Orchestrator: 协调 Agent 交互"""
    state.round += 1
    state.log("Orchestrator", "ROUND", f"第 {state.round} 轮")

    # 路由消息
    for msg in state.messages:
        if msg.get("handled") is None:
            if msg["to"] == "seller" and msg["type"] == "OFFER":
                state.status = "offer_received"
            break

    # 检查终止条件
    if state.round >= 10:
        state.log("Orchestrator", "TERMINATE", "达到最大轮数")
        state.status = "terminated"

    if state.status in ["agreed", "rejected", "terminated", "settled"]:
        state.log("Orchestrator", "COMPLETE", f"最终状态: {state.status}")

    return state


async def run_bilateral_negotiation_demo():
    """运行双边协商演示"""
    print("=" * 70)
    print("双边协商多 Agent 演示")
    print("=" * 70)
    print()

    state = DemoTradeState()
    state.log("System", "INIT", f"协商ID: {state.negotiation_id}")
    state.log("System", "SETUP", f"卖方底价: ${state.seller_price}, 买方预算: ${state.buyer_price}")
    print()

    # 状态流转
    while state.status not in ["agreed", "rejected", "terminated", "settled", "skipped"]:
        # Orchestrator 控制
        state = await orchestrator(state)

        if state.status in ["agreed", "rejected", "terminated", "settled"]:
            break

        # Seller Agent 行动
        state = await seller_agent(state)

        if state.status in ["agreed", "rejected", "terminated", "settled"]:
            break

        # Buyer Agent 行动
        state = await buyer_agent(state)

        print()
        await asyncio.sleep(0.5)  # 模拟处理时间

    # 结算
    print("=" * 70)
    if state.agreed_price:
        print(f"交易成功!")
        print(f"  - 协商ID: {state.negotiation_id}")
        print(f"  - 成交价格: ${state.agreed_price:.2f}")
        print(f"  - 总轮数: {state.round}")
        print(f"  - 消息数: {len(state.messages)}")
    else:
        print(f"交易未达成")
        print(f"  - 最终状态: {state.status}")
    print("=" * 70)


async def run_auction_demo():
    """运行拍卖演示"""
    print()
    print("=" * 70)
    print("拍卖多 Agent 演示 (英式拍卖)")
    print("=" * 70)
    print()

    auction_id = f"auction_{datetime.now().strftime('%H%M%S')}"
    starting_price = 100.0
    current_price = starting_price
    bids = []

    print(f"[System] 拍卖启动: {auction_id}")
    print(f"[Seller] 起拍价: ${starting_price}")
    print()

    # 模拟多个买方 Agent 出价
    buyers = [
        {"id": "buyer_A", "max_budget": 150.0, "strategy": "aggressive"},
        {"id": "buyer_B", "max_budget": 130.0, "strategy": "conservative"},
        {"id": "buyer_C", "max_budget": 180.0, "strategy": "aggressive"},
    ]

    round_num = 0
    while round_num < 10:
        round_num += 1
        print(f"[Orchestrator] 第 {round_num} 轮出价")

        new_bids_this_round = []

        for buyer in buyers:
            # Buyer Agent 决策
            if buyer["max_budget"] > current_price:
                if buyer["strategy"] == "aggressive":
                    increment = min(20.0, (buyer["max_budget"] - current_price) * 0.3)
                else:
                    increment = min(10.0, (buyer["max_budget"] - current_price) * 0.2)

                bid_amount = current_price + increment

                if bid_amount <= buyer["max_budget"]:
                    bid = {
                        "buyer": buyer["id"],
                        "amount": round(bid_amount, 2),
                        "round": round_num
                    }
                    new_bids_this_round.append(bid)
                    print(f"  [{buyer['id']}] 出价: ${bid['amount']:.2f}")

        if not new_bids_this_round:
            print("  本轮无人出价")
            break

        # 更新当前最高价
        highest_bid = max(new_bids_this_round, key=lambda x: x["amount"])
        current_price = highest_bid["amount"]
        bids.append(highest_bid)

        print(f"  [Auction] 当前最高价: ${current_price:.2f} by {highest_bid['buyer']}")
        print()

        await asyncio.sleep(0.3)

    # 拍卖结束
    print("=" * 70)
    if bids:
        winner = max(bids, key=lambda x: x["amount"])
        print(f"拍卖结束!")
        print(f"  - 获胜者: {winner['buyer']}")
        print(f"  - 成交价: ${winner['amount']:.2f}")
        print(f"  - 总出价次数: {len(bids)}")
    else:
        print("流拍")
    print("=" * 70)


async def main():
    """主函数"""
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "Trade Multi-Agent System Demo" + " " * 18 + "║")
    print("║" + " " * 68 + "║")
    print("║  演示 LangGraph 多 Agent 分布式协商架构" + " " * 28 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    # 演示1: 双边协商
    await run_bilateral_negotiation_demo()

    print()
    print()

    # 演示2: 拍卖
    await run_auction_demo()

    print()
    print("演示完成!")
    print()
    print("在实际系统中:")
    print("  - Agent 通过 LangGraph State 传递消息")
    print("  - 每个 Agent 是一个独立的 Node")
    print("  - Orchestrator 控制状态流转和路由")
    print("  - 支持持久化和人工干预 (human_in_the_loop)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
