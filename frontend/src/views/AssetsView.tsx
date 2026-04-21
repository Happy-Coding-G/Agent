import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createTradeListing,
  generateAsset,
  getTradeOrderDelivery,
  getTradePrivacyPolicy,
  getTradeWallet,
  listAssets,
  listSpaceTradeListings,
  listTradeMarket,
  listTradeOrders,
  listTradeYieldJournal,
  purchaseTradeListing,
  runTradeAutoYield,
} from "../api/ptds";
import { useAuth } from "../store/auth";
import { useWorkbench } from "../store/workbench";
import {
  AssetSummary,
  TradeListingOwnerDetail,
  TradeMarketListing,
  TradeOrderSummary,
  TradePrivacyPolicy,
  TradeWallet,
  TradeYieldReport,
} from "../types";

export default function AssetsView() {
  const space = useAuth((s) => s.currentSpace);
  const openTab = useWorkbench((s) => s.openTab);
  const log = useWorkbench((s) => s.log);

  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [prompt, setPrompt] = useState("Generate a practical personal knowledge asset report.");
  const [assets, setAssets] = useState<AssetSummary[]>([]);
  const [policy, setPolicy] = useState<TradePrivacyPolicy | null>(null);
  const [wallet, setWallet] = useState<TradeWallet | null>(null);
  const [market, setMarket] = useState<TradeMarketListing[]>([]);
  const [myListings, setMyListings] = useState<TradeListingOwnerDetail[]>([]);
  const [orders, setOrders] = useState<TradeOrderSummary[]>([]);
  const [yieldJournal, setYieldJournal] = useState<TradeYieldReport[]>([]);
  const [tradeLoading, setTradeLoading] = useState(false);
  const [trading, setTrading] = useState(false);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [listingPrice, setListingPrice] = useState("");
  const [listingCategory, setListingCategory] = useState("knowledge_report");
  const [listingTags, setListingTags] = useState("knowledge, report");
  const [yieldStrategy, setYieldStrategy] = useState("");
  const [lastYieldReport, setLastYieldReport] = useState<TradeYieldReport | null>(null);

  const loadAssets = useCallback(async () => {
    if (!space?.public_id) {
      setAssets([]);
      return;
    }

    setLoading(true);
    try {
      const data = await listAssets(space.public_id);
      setAssets(data || []);
    } catch (e: any) {
      log(`[Assets] load failed: ${e?.message ?? String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [space?.public_id, log]);

  const loadTradeData = useCallback(async () => {
    if (!space?.public_id) {
      setPolicy(null);
      setWallet(null);
      setMarket([]);
      setMyListings([]);
      setOrders([]);
      setYieldJournal([]);
      return;
    }

    setTradeLoading(true);
    try {
      const [policyData, walletData, marketData, listingData, orderData, journalData] = await Promise.all([
        getTradePrivacyPolicy(space.public_id),
        getTradeWallet(),
        listTradeMarket(),
        listSpaceTradeListings(space.public_id),
        listTradeOrders(),
        listTradeYieldJournal(space.public_id),
      ]);
      setPolicy(policyData);
      setWallet(walletData);
      setMarket(marketData || []);
      setMyListings(listingData || []);
      setOrders(orderData || []);
      setYieldJournal(journalData || []);
    } catch (e: any) {
      log(`[Trade] load failed: ${e?.message ?? String(e)}`);
    } finally {
      setTradeLoading(false);
    }
  }, [space?.public_id, log]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  useEffect(() => {
    void loadTradeData();
  }, [loadTradeData]);

  const onGenerate = async () => {
    if (!space?.public_id) return;
    setGenerating(true);
    try {
      const asset = await generateAsset(space.public_id, prompt);
      log(`[Assets] generated: ${asset.asset_id}`);
      await loadAssets();
      await loadTradeData();
      openTab({
        id: `tab-asset-${asset.asset_id}`,
        kind: "asset",
        title: `Asset · ${asset.title}`,
        payload: {
          assetId: asset.asset_id,
          spacePublicId: space.public_id,
        },
      });
    } catch (e: any) {
      log(`[Assets] generate failed: ${e?.message ?? String(e)}`);
    } finally {
      setGenerating(false);
    }
  };

  const onCreateListing = async () => {
    if (!space?.public_id || !selectedAssetId) return;
    setTrading(true);
    try {
      const parsedPrice = Number(listingPrice);
      const price = Number.isFinite(parsedPrice) && parsedPrice > 0 ? parsedPrice : undefined;
      const created = await createTradeListing(space.public_id, {
        asset_id: selectedAssetId,
        price_credits: price,
        category: listingCategory,
        tags: listingTags
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      log(`[Trade] listing created: ${created.listing_id}`);
      setSelectedAssetId("");
      setListingPrice("");
      await loadTradeData();
    } catch (e: any) {
      log(`[Trade] create listing failed: ${e?.message ?? String(e)}`);
    } finally {
      setTrading(false);
    }
  };

  const onPurchase = async (listingId: string) => {
    if (!space?.public_id) return;
    setTrading(true);
    try {
      const order = await purchaseTradeListing(listingId);
      log(`[Trade] purchased listing ${listingId}, order=${order.order_id}`);
      await loadTradeData();
    } catch (e: any) {
      log(`[Trade] purchase failed: ${e?.message ?? String(e)}`);
    } finally {
      setTrading(false);
    }
  };

  const onRunYield = async () => {
    if (!space?.public_id) return;
    setTrading(true);
    try {
      const report = await runTradeAutoYield(space.public_id, yieldStrategy || undefined);
      setLastYieldReport(report);
      log(`[Trade] auto-yield done, gain=${report.yield_amount}`);
      await loadTradeData();
    } catch (e: any) {
      log(`[Trade] auto-yield failed: ${e?.message ?? String(e)}`);
    } finally {
      setTrading(false);
    }
  };

  const onOpenDelivery = async (orderId: string) => {
    try {
      const delivery = await getTradeOrderDelivery(orderId);
      openTab({
        id: `tab-trade-delivery-${orderId}`,
        kind: "markdown",
        title: `Delivery · ${delivery.asset_title}`,
        payload: {
          content: delivery.content_markdown,
        },
      });
      log(`[Trade] delivery opened: ${orderId}`);
    } catch (e: any) {
      log(`[Trade] open delivery failed: ${e?.message ?? String(e)}`);
    }
  };

  const visibleMarket = useMemo(
    () => market.filter((item) => item.status === "active"),
    [market],
  );
  const prePurchaseFields = useMemo(() => {
    const value = policy?.buyer_visibility?.["pre_purchase"];
    return Array.isArray(value) ? (value as string[]) : [];
  }, [policy]);
  const neverExposedFields = useMemo(() => {
    const value = policy?.buyer_visibility?.["never_exposed"];
    return Array.isArray(value) ? (value as string[]) : [];
  }, [policy]);

  return (
    <div className="col" style={{ gap: 16, minHeight: 0, padding: "16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: "16px" }}>📦</span> 知识资产及交易
        </h3>
        <button 
          style={{ padding: "4px 8px", fontSize: 12, background: "transparent", color: "#94A3B8", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, cursor: "pointer", transition: "all 0.2s" }} 
          onClick={() => { void loadAssets(); void loadTradeData(); }} 
          disabled={loading || tradeLoading}
          onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.05)", color: "#E2E8F0" })}
          onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent", color: "#94A3B8" })}
        >
          {loading || tradeLoading ? "↻" : "⟳ Refresh"}
        </button>
      </div>

      {!space && (
        <div style={{ padding: "40px 20px", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px dashed rgba(255,255,255,0.05)" }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }}>📂</div>
          <div style={{ color: "#94A3B8", fontSize: 13 }}>请先选择一个 Space</div>
        </div>
      )}

      {space && (
        <>
          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6 }}>
              <span>🚀</span> 生成私有资产 (LangGraph)
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              style={{ minHeight: 80, resize: "vertical", padding: "10px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "#E2E8F0", outline: "none", lineHeight: 1.5 }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button 
                style={{ padding: "8px 16px", fontSize: 13, background: "#3B82F6", color: "white", border: "none", borderRadius: 6, cursor: generating ? "not-allowed" : "pointer", opacity: generating ? 0.7 : 1, fontWeight: 500 }} 
                onClick={() => void onGenerate()} 
                disabled={generating}
              >
                {generating ? "生成中..." : "开始生成"}
              </button>
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6 }}>
              <span>💼</span> 交易钱包及隐私 {tradeLoading && <span style={{ color: "#94A3B8", fontSize: 11, fontWeight: 400 }}>(loading...)</span>}
            </div>
            <div style={{ display: "grid", gap: 8, padding: "8px 12px", background: "rgba(0,0,0,0.2)", borderRadius: 8, border: "1px solid rgba(255,255,255,0.05)" }}>
              <div style={{ fontSize: 13, color: "#E2E8F0", display: "flex", justifyContent: "space-between" }}>
                <span>余额:</span>
                <span style={{ fontWeight: 600, color: "#10B981" }}>{wallet ? `${wallet.liquid_credits.toFixed(2)} Credits` : "-"}</span>
              </div>
              <div style={{ fontSize: 12, color: "#94A3B8", display: "flex", justifyContent: "space-between" }}>
                <span>策略: </span>
                <span>{wallet?.yield_strategy ?? "balanced"}</span>
              </div>
              <div style={{ fontSize: 12, color: "#94A3B8", display: "flex", justifyContent: "space-between" }}>
                <span>销售收益 / 孳息: </span>
                <span>{wallet?.cumulative_sales_earnings ?? 0} / {wallet?.cumulative_yield_earnings ?? 0}</span>
              </div>
              
              <div style={{ margin: "4px 0", height: 1, background: "rgba(255,255,255,0.05)" }} />
              
              <div style={{ fontSize: 12, color: "#94A3B8" }}>
                <span style={{ color: "#E2E8F0" }}>购前可见:</span> {prePurchaseFields.length > 0 ? prePurchaseFields.join(", ") : "-"}
              </div>
              <div style={{ fontSize: 12, color: "#94A3B8" }}>
                <span style={{ color: "#E2E8F0" }}>永不可见:</span> {neverExposedFields.length > 0 ? neverExposedFields.join(", ") : "-"}
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <select 
                  value={yieldStrategy} 
                  onChange={(e) => setYieldStrategy(e.target.value)} 
                  style={{ flex: 1, padding: "6px 8px", fontSize: 12, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none" }}
                >
                  <option value="">使用默认策略</option>
                  <option value="conservative">conservative</option>
                  <option value="balanced">balanced</option>
                  <option value="aggressive">aggressive</option>
                </select>
                <button 
                  style={{ padding: "6px 12px", fontSize: 12, background: "transparent", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.3)", borderRadius: 6, cursor: "pointer", transition: "all 0.2s" }} 
                  onClick={() => void onRunYield()} 
                  disabled={trading}
                  onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(59,130,246,0.1)" })}
                  onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent" })}
                >
                  运行增值
                </button>
              </div>
              
              {lastYieldReport && (
                <div style={{ fontSize: 12, color: "#10B981", marginTop: 4, background: "rgba(16,185,129,0.1)", padding: "4px 8px", borderRadius: 4 }}>
                  上次增值: +{lastYieldReport.yield_amount} ({lastYieldReport.strategy}, 年化 {lastYieldReport.annual_rate})
                </div>
              )}
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", display: "flex", alignItems: "center", gap: 6 }}>
              <span>➕</span> 发布交易资产
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <select 
                value={selectedAssetId} 
                onChange={(e) => setSelectedAssetId(e.target.value)}
                style={{ padding: "8px 12px", fontSize: 13, width: "100%", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none" }}
              >
                <option value="">选择一个资产</option>
                {assets.map((asset) => (
                  <option key={asset.asset_id} value={asset.asset_id}>
                    {asset.title}
                  </option>
                ))}
              </select>
              <input
                value={listingPrice}
                onChange={(e) => setListingPrice(e.target.value)}
                placeholder="价格 Credits (选填, 留空则自适应)"
                style={{ padding: "8px 12px", fontSize: 13, width: "100%", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }}
              />
              <div style={{ display: "flex", gap: 8 }}>
                <input 
                  value={listingCategory} 
                  onChange={(e) => setListingCategory(e.target.value)} 
                  placeholder="类别" 
                  style={{ flex: 1, padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }}
                />
                <input 
                  value={listingTags} 
                  onChange={(e) => setListingTags(e.target.value)} 
                  placeholder="标签 (逗号分隔)" 
                  style={{ flex: 1, padding: "8px 12px", fontSize: 13, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, color: "#E2E8F0", outline: "none", boxSizing: "border-box" }}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                <button 
                  style={{ padding: "8px 16px", fontSize: 13, background: "linear-gradient(135deg, #10B981, #059669)", color: "white", border: "none", borderRadius: 6, cursor: trading || !selectedAssetId ? "not-allowed" : "pointer", opacity: trading || !selectedAssetId ? 0.5 : 1, fontWeight: 500 }} 
                  onClick={() => void onCreateListing()} 
                  disabled={trading || !selectedAssetId}
                >
                  {trading ? "处理中..." : "创建 Listing"}
                </button>
              </div>
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <span>📄</span> 已生成的资产 ({assets.length})
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 260, overflow: "auto", paddingRight: 4 }}>
              {assets.map((asset) => (
                <div
                  key={asset.asset_id}
                  style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "10px 12px", background: "rgba(255,255,255,0.02)", cursor: "pointer", transition: "all 0.2s" }}
                  onClick={() =>
                    openTab({
                      id: `tab-asset-${asset.asset_id}`,
                      kind: "asset",
                      title: `Asset · ${asset.title}`,
                      payload: {
                        assetId: asset.asset_id,
                        spacePublicId: space.public_id,
                      },
                    })
                  }
                  onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.05)", borderColor: "rgba(255,255,255,0.1)" })}
                  onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "rgba(255,255,255,0.02)", borderColor: "rgba(255,255,255,0.05)" })}
                >
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0" }}>{asset.title}</div>
                  <div style={{ fontSize: 11, color: "#64748B", marginTop: 2 }}>{asset.created_at}</div>
                  <div style={{ fontSize: 12, marginTop: 6, color: "#94A3B8", lineHeight: 1.4 }}>{asset.summary}</div>
                </div>
              ))}
              {assets.length === 0 && <div style={{ fontSize: 12, color: "#64748B", textAlign: "center", padding: "20px 0" }}>暂无生成的资产</div>}
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <span>🏷️</span> 我的发布 ({myListings.length})
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 260, overflow: "auto", paddingRight: 4 }}>
              {myListings.map((item) => (
                <div key={item.listing_id} style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0", display: "flex", justifyContent: "space-between" }}>
                    <span>{item.title}</span>
                    <span style={{ color: "#10B981", fontWeight: 600 }}>{item.price_credits} c</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 6, display: "flex", gap: 8 }}>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>{item.category}</span>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>购买 {item.purchase_count}</span>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>浏览 {item.market_view_count}</span>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>营收 {item.revenue_total}</span>
                  </div>
                </div>
              ))}
              {myListings.length === 0 && <div style={{ fontSize: 12, color: "#64748B", textAlign: "center", padding: "20px 0" }}>暂无发布内容</div>}
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <span>🛒</span> 交易市场 ({visibleMarket.length})
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 320, overflow: "auto", paddingRight: 4 }}>
              {visibleMarket.map((item) => (
                <div key={item.listing_id} style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0", display: "flex", justifyContent: "space-between" }}>
                    <span>{item.title}</span>
                    <span style={{ color: "#3B82F6", fontWeight: 600 }}>{item.price_credits} c</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 6, display: "flex", gap: 8 }}>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>{item.category}</span>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>卖家: {item.seller_alias}</span>
                    <span style={{ padding: "2px 6px", background: "rgba(0,0,0,0.2)", borderRadius: 4 }}>已购: {item.purchase_count}</span>
                  </div>
                  <div style={{ fontSize: 12, marginTop: 6, color: "#94A3B8" }}>{item.public_summary}</div>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                    <button 
                      style={{ padding: "6px 12px", fontSize: 12, background: "linear-gradient(135deg, #3B82F6, #2563EB)", color: "white", border: "none", borderRadius: 4, cursor: trading ? "not-allowed" : "pointer", opacity: trading ? 0.7 : 1, fontWeight: 500 }} 
                      onClick={() => void onPurchase(item.listing_id)} 
                      disabled={trading}
                    >
                      购买
                    </button>
                  </div>
                </div>
              ))}
              {visibleMarket.length === 0 && <div style={{ fontSize: 12, color: "#64748B", textAlign: "center", padding: "20px 0" }}>市场目前没有活跃的发布</div>}
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <span>📜</span> 我的订单 ({orders.length})
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 240, overflow: "auto", paddingRight: 4 }}>
              {orders.map((order) => (
                <div key={order.order_id} style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0", display: "flex", justifyContent: "space-between" }}>
                    <span>{order.asset_title}</span>
                    <span style={{ color: "#E2E8F0", fontWeight: 600 }}>{order.price_credits} c</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 4 }}>
                    卖家: {order.seller_alias} | {order.purchased_at}
                  </div>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                    <button 
                      style={{ padding: "6px 12px", fontSize: 12, background: "transparent", color: "#3B82F6", border: "1px solid rgba(59,130,246,0.3)", borderRadius: 4, cursor: "pointer", transition: "all 0.2s" }} 
                      onClick={() => void onOpenDelivery(order.order_id)}
                      onMouseEnter={(e) => Object.assign(e.currentTarget.style, { background: "rgba(59,130,246,0.1)" })}
                      onMouseLeave={(e) => Object.assign(e.currentTarget.style, { background: "transparent" })}
                    >
                      打开交付物
                    </button>
                  </div>
                </div>
              ))}
              {orders.length === 0 && <div style={{ fontSize: 12, color: "#64748B", textAlign: "center", padding: "20px 0" }}>暂无订单</div>}
            </div>
          </div>

          <div style={{ padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.08)", minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#E2E8F0", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <span>📈</span> 收益流水 ({yieldJournal.length})
            </div>
            <div style={{ display: "grid", gap: 8, maxHeight: 220, overflow: "auto", paddingRight: 4 }}>
              {yieldJournal.map((item) => (
                <div key={item.run_id} style={{ border: "1px solid rgba(255,255,255,0.05)", borderRadius: 8, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "#E2E8F0", display: "flex", justifyContent: "space-between" }}>
                    <span>{item.strategy}</span>
                    <span style={{ color: "#10B981", fontWeight: 600 }}>+{item.yield_amount}</span>
                  </div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 4 }}>
                    耗时 {item.elapsed_days} 天 | 年化 {item.annual_rate}
                  </div>
                </div>
              ))}
              {yieldJournal.length === 0 && <div style={{ fontSize: 12, color: "#64748B", textAlign: "center", padding: "20px 0" }}>无收益记录</div>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
