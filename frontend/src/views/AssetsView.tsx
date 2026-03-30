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
    <div className="col" style={{ gap: 12, minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
        <span style={{ fontSize: 11, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.5px", fontWeight: 600 }}>
          Assets
        </span>
        <button className="btn btn-ghost" onClick={() => { void loadAssets(); void loadTradeData(); }} disabled={loading || tradeLoading}>
          {loading || tradeLoading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {!space && <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Select a space first.</div>}

      {space && (
        <>
          <div className="card" style={{ padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Generate Personal Asset (LangGraph)</div>
            <textarea
              className="input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              style={{ minHeight: 90, resize: "vertical" }}
            />
            <div className="row" style={{ marginTop: 8, justifyContent: "flex-end" }}>
              <button className="btn btn-primary" onClick={() => void onGenerate()} disabled={generating}>
                {generating ? "Generating..." : "Generate"}
              </button>
            </div>
          </div>

          <div className="card" style={{ padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
              Trading Privacy + Wallet {tradeLoading ? "(loading...)" : ""}
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              <div style={{ fontSize: 12 }}>
                Wallet: {wallet ? `${wallet.liquid_credits.toFixed(2)} credits` : "-"}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Strategy: {wallet?.yield_strategy ?? "balanced"} | Sales earnings: {wallet?.cumulative_sales_earnings ?? 0} | Yield earnings: {wallet?.cumulative_yield_earnings ?? 0}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Pre-purchase visibility: {prePurchaseFields.length > 0 ? prePurchaseFields.join(", ") : "-"}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                Never exposed: {neverExposedFields.length > 0 ? neverExposedFields.join(", ") : "-"}
              </div>
              <div className="row" style={{ gap: 8 }}>
                <select className="input" value={yieldStrategy} onChange={(e) => setYieldStrategy(e.target.value)} style={{ maxWidth: 220 }}>
                  <option value="">Use wallet strategy</option>
                  <option value="conservative">conservative</option>
                  <option value="balanced">balanced</option>
                  <option value="aggressive">aggressive</option>
                </select>
                <button className="btn btn-ghost" onClick={() => void onRunYield()} disabled={trading}>
                  Run Auto Yield
                </button>
              </div>
              {lastYieldReport && (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Last yield: +{lastYieldReport.yield_amount} ({lastYieldReport.strategy}, annual {lastYieldReport.annual_rate})
                </div>
              )}
            </div>
          </div>

          <div className="card" style={{ padding: 10 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Create Trade Listing</div>
            <div className="col" style={{ gap: 8 }}>
              <select className="input" value={selectedAssetId} onChange={(e) => setSelectedAssetId(e.target.value)}>
                <option value="">Select an asset</option>
                {assets.map((asset) => (
                  <option key={asset.asset_id} value={asset.asset_id}>
                    {asset.title}
                  </option>
                ))}
              </select>
              <input
                className="input"
                value={listingPrice}
                onChange={(e) => setListingPrice(e.target.value)}
                placeholder="Price credits (optional, auto if empty)"
              />
              <input className="input" value={listingCategory} onChange={(e) => setListingCategory(e.target.value)} placeholder="Category" />
              <input className="input" value={listingTags} onChange={(e) => setListingTags(e.target.value)} placeholder="Tags (comma separated)" />
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn btn-primary" onClick={() => void onCreateListing()} disabled={trading || !selectedAssetId}>
                  {trading ? "Working..." : "Create Listing"}
                </button>
              </div>
            </div>
          </div>

          <div className="card" style={{ padding: 10, minHeight: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Generated Assets ({assets.length})</div>
            <div style={{ display: "grid", gap: 8, maxHeight: 260, overflow: "auto" }}>
              {assets.map((asset) => (
                <div
                  key={asset.asset_id}
                  style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-2)", cursor: "pointer" }}
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
                >
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{asset.title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{asset.created_at}</div>
                  <div style={{ fontSize: 11, marginTop: 4, color: "var(--text-muted)" }}>{asset.summary}</div>
                </div>
              ))}
              {assets.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No generated assets yet.</div>}
            </div>
          </div>

          <div className="card" style={{ padding: 10, minHeight: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>My Listings ({myListings.length})</div>
            <div style={{ display: "grid", gap: 8, maxHeight: 260, overflow: "auto" }}>
              {myListings.map((item) => (
                <div key={item.listing_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-2)" }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{item.title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {item.category} | {item.price_credits} credits | buys {item.purchase_count} | views {item.market_view_count} | revenue {item.revenue_total}
                  </div>
                </div>
              ))}
              {myListings.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No listings yet.</div>}
            </div>
          </div>

          <div className="card" style={{ padding: 10, minHeight: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Trade Market ({visibleMarket.length})</div>
            <div style={{ display: "grid", gap: 8, maxHeight: 320, overflow: "auto" }}>
              {visibleMarket.map((item) => (
                <div key={item.listing_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-2)" }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{item.title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {item.category} | {item.price_credits} credits | seller {item.seller_alias} | buys {item.purchase_count}
                  </div>
                  <div style={{ fontSize: 11, marginTop: 4, color: "var(--text-muted)" }}>{item.public_summary}</div>
                  <div className="row" style={{ marginTop: 6, justifyContent: "flex-end" }}>
                    <button className="btn btn-ghost" onClick={() => void onPurchase(item.listing_id)} disabled={trading}>
                      Buy
                    </button>
                  </div>
                </div>
              ))}
              {visibleMarket.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Market is empty.</div>}
            </div>
          </div>

          <div className="card" style={{ padding: 10, minHeight: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>My Orders ({orders.length})</div>
            <div style={{ display: "grid", gap: 8, maxHeight: 240, overflow: "auto" }}>
              {orders.map((order) => (
                <div key={order.order_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-2)" }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{order.asset_title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {order.price_credits} credits | {order.seller_alias} | {order.purchased_at}
                  </div>
                  <div className="row" style={{ marginTop: 6, justifyContent: "flex-end" }}>
                    <button className="btn btn-ghost" onClick={() => void onOpenDelivery(order.order_id)}>
                      Open Delivery
                    </button>
                  </div>
                </div>
              ))}
              {orders.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No orders yet.</div>}
            </div>
          </div>

          <div className="card" style={{ padding: 10, minHeight: 0 }}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Yield Journal ({yieldJournal.length})</div>
            <div style={{ display: "grid", gap: 8, maxHeight: 220, overflow: "auto" }}>
              {yieldJournal.map((item) => (
                <div key={item.run_id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-2)" }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{item.strategy}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    gain {item.yield_amount} | days {item.elapsed_days} | annual {item.annual_rate}
                  </div>
                </div>
              ))}
              {yieldJournal.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No yield runs yet.</div>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
