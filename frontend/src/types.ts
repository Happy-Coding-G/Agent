export type Activity = "explorer" | "search" | "assets" | "kg" | "agent";

export type TabKind = "chat" | "markdown" | "filePreview" | "kg" | "asset";

export type Tab = {
  id: string;
  kind: TabKind;
  title: string;
  payload?: Record<string, unknown>;
};

export type Space = {
  id: number;
  public_id: string;
  name: string;
  owner_user_id: number;
};

export type FileBrief = {
  public_id: string;
  name: string;
  size_bytes: number | null;
  mime: string | null;
};

export type TreeFolder = {
  id: number;
  public_id: string;
  name: string;
  path_cache: string;
  children: TreeFolder[];
  files: FileBrief[];
};

export type UploadInitResponse = {
  upload_id: string;
  object_key: string;
  upload_url?: string;
  presigned_url?: string;
};

export type FileViewResponse = {
  url: string;
  expires_in: number;
};

export type User = {
  id: number;
  user_key: string;
  display_name?: string;
};

export type LoginRequest = {
  identifier: string;
  credential: string;
  identity_type: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
};

export type RegisterRequest = {
  identifier: string;
  credential: string;
  identity_type: string;
  display_name?: string;
};

export type RegisterResponse = {
  status: string;
  user_id: number;
  message: string;
};

export type FolderCreateRequest = {
  name: string;
  parent_id?: number | null;
};

export type FolderRenameRequest = {
  new_name: string;
};

export type FileRenameRequest = {
  new_name: string;
};

export type MarkdownDocSummary = {
  doc_id: string;
  title: string;
  status: string;
  updated_at: string;
  content_hash?: string | null;
  chunk_count: number;
};

export type MarkdownDocDetail = {
  doc_id: string;
  title: string;
  status: string;
  markdown_text: string;
  markdown_object_key?: string | null;
  updated_at: string;
  content_hash?: string | null;
  chunk_count: number;
};

export type GraphNode = {
  doc_id: string;
  label: string;
  description: string;
  tags: string[];
  status: string;
  updated_at: string;
};

export type GraphEdge = {
  edge_id: string;
  source_doc_id: string;
  target_doc_id: string;
  relation_type: string;
  description: string;
  created_at: string;
  updated_at: string;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type AssetSummary = {
  asset_id: string;
  title: string;
  summary: string;
  created_at: string;
};

export type AssetDetail = {
  asset_id: string;
  space_public_id: string;
  title: string;
  summary: string;
  created_at: string;
  updated_at: string;
  prompt: string;
  content_markdown: string;
  graph_snapshot: {
    node_count: number;
    edge_count: number;
  };
};

export type TradePrivacyPolicy = {
  policy_id: string;
  version: string;
  principles: string[];
  buyer_visibility: Record<string, unknown>;
  redaction_rules: string[];
  delivery_terms: string[];
  notes: string[];
};

export type TradeMarketListing = {
  listing_id: string;
  title: string;
  category: string;
  tags: string[];
  price_credits: number;
  public_summary: string;
  preview_excerpt: string;
  seller_alias: string;
  purchase_count: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type TradeMarketListingDetail = TradeMarketListing & {
  buyer_visibility: Record<string, unknown>;
};

export type TradeListingOwnerDetail = TradeMarketListing & {
  asset_id: string;
  space_public_id: string;
  market_view_count: number;
  revenue_total: number;
};

export type TradeOrderSummary = {
  order_id: string;
  listing_id: string;
  asset_title: string;
  seller_alias: string;
  price_credits: number;
  purchased_at: string;
};

export type TradeOrderDetail = TradeOrderSummary & {
  platform_fee: number;
  seller_income: number;
  delivery_scope: string[];
};

export type TradeDeliveryPayload = {
  order_id: string;
  listing_id: string;
  asset_title: string;
  purchased_at: string;
  accessible_fields: string[];
  content_markdown: string;
  graph_snapshot: Record<string, unknown>;
  usage_terms: string[];
};

export type TradeWallet = {
  liquid_credits: number;
  cumulative_sales_earnings: number;
  cumulative_yield_earnings: number;
  total_spent: number;
  auto_yield_enabled: boolean;
  yield_strategy: string;
  last_yield_run_at: string;
  updated_at: string;
};

export type TradeYieldReport = {
  run_id: string;
  strategy: string;
  annual_rate: number;
  elapsed_days: number;
  yield_amount: number;
  wallet_before: Record<string, unknown>;
  wallet_after: Record<string, unknown>;
  listing_adjustments: Array<Record<string, unknown>>;
  generated_at: string;
};

// Agent types
export type AgentType = "file_query" | "data_process" | "review" | "qa" | "asset_organize" | "trade" | "chat";

export type AgentChatRequest = {
  message: string;
  space_id: string;
  context?: Record<string, unknown>;
};

export type AgentChatResponse = {
  agent_type: AgentType;
  result: Record<string, unknown>;
  sources?: string[];
  error?: string;
};

export type AgentTask = {
  task_id: string;
  agent_type: AgentType;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
};

export type FileQueryRequest = {
  query: string;
  space_id: string;
};

export type FileQueryResult = {
  files: Array<{
    path: string;
    name: string;
    size: number;
    modified: string;
    content?: string;
  }>;
  error?: string;
};

export type AssetOrganizeRequest = {
  asset_ids: string[];
  space_id: string;
  generate_report?: boolean;
};

export type AssetCluster = {
  cluster_id: string;
  name: string;
  description?: string;
  summary_report?: string;
  asset_count: number;
  assets: string[];
};

export type ReviewRequest = {
  doc_id: string;
  review_type?: "quality" | "compliance" | "completeness";
};

export type ReviewResponse = {
  doc_id: string;
  review_type: string;
  score: number;
  passed: boolean;
  issues: string[];
  final_status: string;
  rework_count: number;
};
