/**
 * TokenUsageView - Token用量统计界面
 *
 * 展示用户的Token使用情况和成本分析
 * 包括：用量趋势、功能分布、模型分布、实时统计
 */

import { ReactNode, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  Functions as FunctionsIcon,
  Info as InfoIcon,
  Refresh as RefreshIcon,
  Savings as SavingsIcon,
  Token as TokenIcon,
  TrendingDown,
  TrendingUp,
} from '@mui/icons-material';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useAuth } from '../store/auth';

const API_BASE = '/api/v1/token-usage';

interface UsageSummary {
  period: {
    start: string;
    end: string;
  };
  summary: {
    total_requests: number;
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    total_cost: number;
    avg_latency_ms: number;
  };
  by_feature: Array<{
    feature_type: string;
    requests: number;
    tokens: number;
    cost: number;
  }>;
  by_model: Array<{
    model: string;
    requests: number;
    tokens: number;
    cost: number;
  }>;
}

interface DailyUsage {
  date: string;
  requests: number;
  tokens: number;
  cost: number;
}

interface UsageRecord {
  id: number;
  provider: string;
  model: string;
  is_custom_api: boolean;
  feature_type: string;
  feature_detail: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost: number;
  latency_ms: number;
  status: string;
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  message?: string;
  data: T;
}

interface StatCardData {
  title: string;
  value: string;
  subtitle: string;
  icon: ReactNode;
  color: string;
  change?: number | null;
}

const FEATURE_LABELS: Record<string, string> = {
  chat: 'RAG对话',
  chat_stream: '流式对话',
  asset_generation: '资产生成',
  asset_organize: '资产整理',
  trade_negotiation: '交易协商',
  trade_pricing: '交易定价',
  ingest_pipeline: '文档摄入',
  graph_construction: '图谱构建',
  review: '文档审核',
  file_query: '文件查询',
  embedding: '文本嵌入',
  other: '其他',
};

const FEATURE_COLORS: Record<string, string> = {
  chat: '#38BDF8',
  chat_stream: '#60A5FA',
  asset_generation: '#34D399',
  asset_organize: '#6EE7B7',
  trade_negotiation: '#F59E0B',
  trade_pricing: '#FB923C',
  ingest_pipeline: '#A78BFA',
  graph_construction: '#C084FC',
  review: '#F87171',
  file_query: '#FB7185',
  embedding: '#22D3EE',
  other: '#94A3B8',
};

const MODEL_COLORS = ['#38BDF8', '#34D399', '#F59E0B', '#A78BFA', '#FB7185', '#22D3EE'];

const panelSx = {
  p: { xs: 2, md: 3 },
  borderRadius: 4,
  border: '1px solid rgba(148, 163, 184, 0.18)',
  background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.98) 100%)',
  boxShadow: '0 18px 40px rgba(15, 23, 42, 0.08)',
};

const heroChipSx = {
  color: 'rgba(255,255,255,0.92)',
  backgroundColor: 'rgba(255,255,255,0.08)',
  border: '1px solid rgba(255,255,255,0.14)',
  backdropFilter: 'blur(8px)',
};

const chartTooltipStyle = {
  borderRadius: 16,
  border: '1px solid rgba(148, 163, 184, 0.18)',
  boxShadow: '0 18px 40px rgba(15, 23, 42, 0.16)',
};

function formatNumber(num: number) {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toLocaleString('zh-CN');
}

function formatCost(cost: number) {
  if (cost === 0) return '$0.0000';
  if (cost < 0.01) return `$${cost.toFixed(6)}`;
  return `$${cost.toFixed(4)}`;
}

function formatAxisCost(cost: number) {
  if (cost === 0) return '$0';
  if (cost < 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

function formatDateLabel(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
  });
}

function toLocalIsoDate(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  return '加载数据失败';
}

async function requestUsage<T>(url: string, token: string): Promise<T> {
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });

  const raw = await response.text();
  let payload: ApiResponse<T> | null = null;

  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(payload?.message || `请求失败 (${response.status})`);
  }

  if (!payload?.success) {
    throw new Error(payload?.message || '接口返回异常');
  }

  return payload.data;
}

function StatCard({ title, value, subtitle, icon, color, change }: StatCardData) {
  const showChange = typeof change === 'number' && Number.isFinite(change) && Math.abs(change) >= 0.1;

  return (
    <Card
      sx={{
        height: '100%',
        borderRadius: 4,
        border: '1px solid rgba(148, 163, 184, 0.18)',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.98) 100%)',
        boxShadow: '0 18px 40px rgba(15, 23, 42, 0.08)',
        overflow: 'hidden',
      }}
    >
      <Box sx={{ height: 4, background: `linear-gradient(90deg, ${color} 0%, rgba(255,255,255,0) 100%)` }} />
      <CardContent sx={{ p: 2.75 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.75 }}>
              {title}
            </Typography>
            <Typography variant="h4" sx={{ color, fontWeight: 700, lineHeight: 1.15 }}>
              {value}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1.25, color: 'text.secondary' }}>
              {subtitle}
            </Typography>
          </Box>
          <Box
            sx={{
              display: 'grid',
              placeItems: 'center',
              width: 48,
              height: 48,
              borderRadius: 3,
              color,
              backgroundColor: `${color}14`,
              flexShrink: 0,
            }}
          >
            {icon}
          </Box>
        </Box>
        {showChange && (
          <Box sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 0.75 }}>
            {change > 0 ? (
              <TrendingUp sx={{ color: 'success.main', fontSize: 16 }} />
            ) : (
              <TrendingDown sx={{ color: 'error.main', fontSize: 16 }} />
            )}
            <Typography
              variant="caption"
              sx={{ color: change > 0 ? 'success.main' : 'error.main', fontWeight: 600 }}
            >
              {change > 0 ? '+' : ''}
              {change.toFixed(1)}% 对比前一时间窗
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyStatePanel({
  title,
  description,
  minHeight = 320,
}: {
  title: string;
  description: string;
  minHeight?: number;
}) {
  return (
    <Box
      sx={{
        minHeight,
        borderRadius: 3,
        border: '1px dashed rgba(148, 163, 184, 0.45)',
        background: 'linear-gradient(180deg, rgba(248,250,252,0.95) 0%, rgba(241,245,249,0.95) 100%)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        px: 3,
      }}
    >
      <Box sx={{ maxWidth: 360 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
      </Box>
    </Box>
  );
}

export default function TokenUsageView() {
  const token = useAuth(s => s.token);
  const [activeTab, setActiveTab] = useState(0);
  const [timeRange, setTimeRange] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [dailyUsage, setDailyUsage] = useState<DailyUsage[]>([]);
  const [recentRecords, setRecentRecords] = useState<UsageRecord[]>([]);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = async () => {
    if (!token) {
      setSummary(null);
      setDailyUsage([]);
      setRecentRecords([]);
      setError('当前未登录，无法加载 Token 统计数据');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const [summaryResult, dailyResult, recentResult] = await Promise.allSettled([
        requestUsage<UsageSummary>(`${API_BASE}/summary?days=${timeRange}`, token),
        requestUsage<DailyUsage[]>(`${API_BASE}/daily?days=${timeRange}`, token),
        requestUsage<UsageRecord[]>(`${API_BASE}/recent?limit=50`, token),
      ]);

      let hasSuccess = false;
      let firstError: string | null = null;

      if (summaryResult.status === 'fulfilled') {
        setSummary(summaryResult.value);
        hasSuccess = true;
      } else {
        setSummary(null);
        firstError = getErrorMessage(summaryResult.reason);
      }

      if (dailyResult.status === 'fulfilled') {
        setDailyUsage(dailyResult.value);
        hasSuccess = true;
      } else {
        setDailyUsage([]);
        firstError = firstError || getErrorMessage(dailyResult.reason);
      }

      if (recentResult.status === 'fulfilled') {
        setRecentRecords(recentResult.value);
        hasSuccess = true;
      } else {
        setRecentRecords([]);
        firstError = firstError || getErrorMessage(recentResult.reason);
      }

      if (hasSuccess) {
        setLastUpdated(new Date().toISOString());
      }

      if (!hasSuccess) {
        setError(firstError || '加载数据失败');
      } else if (firstError) {
        setError(`部分数据加载失败：${firstError}`);
      }
    } catch (err) {
      setSummary(null);
      setDailyUsage([]);
      setRecentRecords([]);
      setError(getErrorMessage(err));
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [timeRange, token]);

  const trendData = useMemo(() => {
    const usageMap = new Map(
      dailyUsage
        .filter(item => item.date)
        .map(item => [item.date.slice(0, 10), item])
    );
    const normalized: DailyUsage[] = [];
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    for (let offset = timeRange - 1; offset >= 0; offset -= 1) {
      const current = new Date(today);
      current.setDate(today.getDate() - offset);
      const key = toLocalIsoDate(current);
      const usage = usageMap.get(key);
      normalized.push({
        date: key,
        requests: usage?.requests ?? 0,
        tokens: usage?.tokens ?? 0,
        cost: usage?.cost ?? 0,
      });
    }

    return normalized;
  }, [dailyUsage, timeRange]);

  const trendSummary = useMemo(() => {
    if (!trendData.length) return null;

    const totalTokens = summary?.summary.total_tokens ?? trendData.reduce((acc, day) => acc + day.tokens, 0);
    const activeDays = trendData.filter(day => day.tokens > 0).length;
    const peakDay = trendData.reduce((best, day) => (day.tokens > best.tokens ? day : best), trendData[0]);
    const averageDailyTokens = totalTokens / Math.max(timeRange, 1);
    const recentWindow = Math.min(7, Math.max(1, Math.floor(trendData.length / 2)));
    const recentTokens = trendData.slice(-recentWindow).reduce((acc, day) => acc + day.tokens, 0);
    const previousTokens = trendData
      .slice(Math.max(0, trendData.length - recentWindow * 2), trendData.length - recentWindow)
      .reduce((acc, day) => acc + day.tokens, 0);

    return {
      activeDays,
      peakDay,
      averageDailyTokens,
      recentWindow,
      trendChange: previousTokens > 0 ? ((recentTokens - previousTokens) / previousTokens) * 100 : null,
    };
  }, [summary, timeRange, trendData]);

  const stats = useMemo<StatCardData[] | null>(() => {
    if (!summary || !trendSummary) return null;

    const totals = summary.summary;
    const peakSubtitle = trendSummary.peakDay.tokens > 0
      ? `峰值 ${formatDateLabel(trendSummary.peakDay.date)} · ${formatNumber(trendSummary.peakDay.tokens)}`
      : `活跃 ${trendSummary.activeDays}/${timeRange} 天`;

    return [
      {
        title: '总 Token 消耗',
        value: formatNumber(totals.total_tokens),
        subtitle: `输入 ${formatNumber(totals.total_prompt_tokens)} · 输出 ${formatNumber(totals.total_completion_tokens)}`,
        icon: <TokenIcon />,
        color: '#38BDF8',
        change: trendSummary.trendChange,
      },
      {
        title: '总成本',
        value: formatCost(totals.total_cost),
        subtitle: `${summary.by_model.length} 个模型参与计费`,
        icon: <SavingsIcon />,
        color: '#34D399',
      },
      {
        title: '总请求数',
        value: formatNumber(totals.total_requests),
        subtitle: `平均延迟 ${Math.round(totals.avg_latency_ms)}ms`,
        icon: <FunctionsIcon />,
        color: '#F59E0B',
      },
      {
        title: '日均 Token',
        value: formatNumber(Math.round(trendSummary.averageDailyTokens)),
        subtitle: peakSubtitle,
        icon: <TrendingUp />,
        color: '#A78BFA',
      },
    ];
  }, [summary, timeRange, trendSummary]);

  const featureData = useMemo(() => {
    if (!summary) return [];

    return [...summary.by_feature]
      .sort((left, right) => right.tokens - left.tokens)
      .map(feature => ({
        name: FEATURE_LABELS[feature.feature_type] || feature.feature_type,
        value: feature.tokens,
        cost: feature.cost,
        requests: feature.requests,
        color: FEATURE_COLORS[feature.feature_type] || '#94A3B8',
      }));
  }, [summary]);

  const modelData = useMemo(() => {
    if (!summary) return [];

    return [...summary.by_model]
      .sort((left, right) => right.tokens - left.tokens)
      .map((model, index) => ({
        name: model.model,
        value: model.tokens,
        cost: model.cost,
        requests: model.requests,
        color: MODEL_COLORS[index % MODEL_COLORS.length],
      }));
  }, [summary]);

  const totalFeatureTokens = useMemo(
    () => featureData.reduce((sum, item) => sum + item.value, 0),
    [featureData]
  );

  const totalModelTokens = useMemo(
    () => modelData.reduce((sum, item) => sum + item.value, 0),
    [modelData]
  );

  const hasTrendData = trendData.some(day => day.tokens > 0 || day.requests > 0 || day.cost > 0);
  const partialDataLoaded = Boolean(summary || dailyUsage.length || recentRecords.length);
  const customApiRecords = recentRecords.filter(record => record.is_custom_api).length;

  if (loading && !summary && dailyUsage.length === 0 && recentRecords.length === 0) {
    return (
      <Box
        sx={{
          minHeight: '60vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 2,
        }}
      >
        <CircularProgress />
        <Typography variant="body2" color="text.secondary">
          正在加载 Token 统计数据...
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1480, mx: 'auto' }}>
      <Paper
        sx={{
          position: 'relative',
          overflow: 'hidden',
          p: { xs: 2.5, md: 3.5 },
          mb: 3,
          borderRadius: 4,
          color: 'common.white',
          background: 'linear-gradient(135deg, #0F172A 0%, #1E293B 48%, #111827 100%)',
          boxShadow: '0 24px 48px rgba(15, 23, 42, 0.24)',
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            top: -80,
            right: -40,
            width: 280,
            height: 280,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(56, 189, 248, 0.32) 0%, rgba(56, 189, 248, 0) 72%)',
            pointerEvents: 'none',
          }}
        />
        <Grid container spacing={3} alignItems="center" sx={{ position: 'relative', zIndex: 1 }}>
          <Grid item xs={12} lg={8}>
            <Typography variant="overline" sx={{ letterSpacing: 1.6, color: 'rgba(226,232,240,0.72)' }}>
              Usage Observatory
            </Typography>
            <Typography variant="h3" sx={{ fontWeight: 700, lineHeight: 1.1 }}>
              Token 用量统计
            </Typography>
            <Typography sx={{ mt: 1.5, maxWidth: 720, color: 'rgba(226,232,240,0.82)' }}>
              按时间、功能与模型三个维度查看 Token 消耗，快速识别高成本链路，并区分平台模型与个人模型的费用边界。
            </Typography>
            <Box sx={{ mt: 2.5, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              <Chip label={`统计范围：最近 ${timeRange} 天`} sx={heroChipSx} />
              <Chip
                label={lastUpdated ? `上次刷新：${new Date(lastUpdated).toLocaleString('zh-CN')}` : '等待首次刷新'}
                sx={heroChipSx}
              />
              {trendSummary && <Chip label={`活跃天数：${trendSummary.activeDays}/${timeRange}`} sx={heroChipSx} />}
            </Box>
          </Grid>

          <Grid item xs={12} lg={4}>
            <Box
              sx={{
                display: 'flex',
                justifyContent: { xs: 'flex-start', lg: 'flex-end' },
                gap: 1.5,
                flexWrap: 'wrap',
              }}
            >
              <FormControl
                size="small"
                sx={{
                  minWidth: 148,
                  '& .MuiInputLabel-root': { color: 'rgba(226,232,240,0.72)' },
                  '& .MuiOutlinedInput-root': {
                    color: 'common.white',
                    borderRadius: 999,
                    backgroundColor: 'rgba(15,23,42,0.25)',
                    '& fieldset': { borderColor: 'rgba(255,255,255,0.16)' },
                    '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.28)' },
                    '&.Mui-focused fieldset': { borderColor: '#7DD3FC' },
                  },
                  '& .MuiSvgIcon-root': { color: 'rgba(226,232,240,0.82)' },
                }}
              >
                <InputLabel>时间范围</InputLabel>
                <Select
                  value={timeRange}
                  onChange={(event) => setTimeRange(Number(event.target.value))}
                  label="时间范围"
                >
                  <MenuItem value={7}>最近7天</MenuItem>
                  <MenuItem value={30}>最近30天</MenuItem>
                  <MenuItem value={90}>最近90天</MenuItem>
                </Select>
              </FormControl>

              <Button
                variant="contained"
                startIcon={<RefreshIcon />}
                onClick={loadData}
                disabled={loading}
                sx={{
                  px: 2.25,
                  borderRadius: 999,
                  backgroundColor: '#2563EB',
                  boxShadow: 'none',
                  '&:hover': { backgroundColor: '#1D4ED8', boxShadow: 'none' },
                }}
              >
                刷新数据
              </Button>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      {loading && (
        <LinearProgress
          sx={{
            mb: 3,
            height: 6,
            borderRadius: 999,
            backgroundColor: 'rgba(148, 163, 184, 0.16)',
            '& .MuiLinearProgress-bar': { borderRadius: 999 },
          }}
        />
      )}

      {error && (
        <Alert severity={partialDataLoaded ? 'warning' : 'error'} sx={{ mb: 3, borderRadius: 3 }}>
          {error}
        </Alert>
      )}

      {stats && (
        <Grid container spacing={2.5} sx={{ mb: 3 }}>
          {stats.map(stat => (
            <Grid item xs={12} sm={6} xl={3} key={stat.title}>
              <StatCard {...stat} />
            </Grid>
          ))}
        </Grid>
      )}

      <Paper
        sx={{
          mb: 3,
          borderRadius: 4,
          overflow: 'hidden',
          border: '1px solid rgba(148, 163, 184, 0.18)',
          boxShadow: '0 18px 40px rgba(15, 23, 42, 0.08)',
        }}
      >
        <Tabs
          value={activeTab}
          onChange={(_, value) => setActiveTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{
            px: { xs: 1, md: 2 },
            backgroundColor: 'rgba(248,250,252,0.96)',
            borderBottom: '1px solid rgba(148, 163, 184, 0.14)',
            '& .MuiTabs-indicator': { height: 3, borderRadius: 999, backgroundColor: '#2563EB' },
            '& .MuiTab-root': { minHeight: 64, textTransform: 'none', fontWeight: 600 },
          }}
        >
          <Tab label="用量趋势" />
          <Tab label="功能分布" />
          <Tab label="模型分布" />
          <Tab label="使用明细" />
        </Tabs>

        <Box sx={{ p: { xs: 2, md: 3 } }}>
          {activeTab === 0 && (
            <Box sx={panelSx}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap', mb: 3 }}>
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    每日 Token 用量趋势
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                    补齐了完整日期区间，即使某天没有调用记录，也能保持时间轴连续，不再出现空白图框。
                  </Typography>
                </Box>
                {trendSummary && (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    <Chip label={`日均 ${formatNumber(Math.round(trendSummary.averageDailyTokens))} Token`} size="small" />
                    <Chip label={`活跃 ${trendSummary.activeDays}/${timeRange} 天`} size="small" />
                    {trendSummary.peakDay.tokens > 0 && (
                      <Chip label={`峰值 ${formatDateLabel(trendSummary.peakDay.date)}`} size="small" />
                    )}
                  </Box>
                )}
              </Box>

              {hasTrendData ? (
                <Box sx={{ height: 380 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trendData} margin={{ top: 8, right: 20, left: -10, bottom: 0 }}>
                      <defs>
                        <linearGradient id="tokenArea" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#38BDF8" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#38BDF8" stopOpacity={0.03} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.22)" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={formatDateLabel}
                        tick={{ fill: '#64748B', fontSize: 12 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        yAxisId="left"
                        tickFormatter={(value) => formatNumber(Number(value))}
                        tick={{ fill: '#64748B', fontSize: 12 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        width={76}
                        tickFormatter={(value) => formatAxisCost(Number(value))}
                        tick={{ fill: '#64748B', fontSize: 12 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <RechartsTooltip
                        contentStyle={chartTooltipStyle}
                        formatter={(value, name) => {
                          const numericValue = Number(value || 0);
                          const seriesName = String(name);

                          if (seriesName === 'tokens') return [formatNumber(numericValue), 'Token数'];
                          if (seriesName === 'requests') return [formatNumber(numericValue), '请求数'];
                          return [formatCost(numericValue), '成本'];
                        }}
                        labelFormatter={(label) => new Date(label).toLocaleDateString('zh-CN')}
                      />
                      <Area
                        yAxisId="left"
                        type="monotone"
                        dataKey="tokens"
                        stroke="#38BDF8"
                        fill="url(#tokenArea)"
                        strokeWidth={3}
                        activeDot={{ r: 5 }}
                      />
                      <Line
                        yAxisId="left"
                        type="monotone"
                        dataKey="requests"
                        stroke="#818CF8"
                        strokeWidth={2}
                        dot={false}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="cost"
                        stroke="#34D399"
                        strokeWidth={2}
                        dot={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </Box>
              ) : (
                <EmptyStatePanel
                  title="当前时间范围内还没有 Token 使用记录"
                  description="发起一次对话、文档摄入或交易协商后，这里会按天展示 Token、请求数和成本变化。"
                  minHeight={380}
                />
              )}
            </Box>
          )}

          {activeTab === 1 && (
            <Grid container spacing={3}>
              <Grid item xs={12} xl={5}>
                <Box sx={panelSx}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    Token 用量分布（按功能）
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, mb: 3 }}>
                    观察哪些产品能力正在持续消耗 Token，便于做预算和策略拆分。
                  </Typography>

                  {featureData.length > 0 ? (
                    <Box sx={{ height: 340 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={featureData}
                            cx="50%"
                            cy="50%"
                            innerRadius={72}
                            outerRadius={110}
                            paddingAngle={2}
                            dataKey="value"
                            nameKey="name"
                          >
                            {featureData.map((entry) => (
                              <Cell key={entry.name} fill={entry.color} />
                            ))}
                          </Pie>
                          <RechartsTooltip
                            contentStyle={chartTooltipStyle}
                            formatter={(value, name, props) => {
                              const numericValue = Number(value || 0);
                              const cost = Number(props?.payload?.cost || 0);
                              return [`${formatNumber(numericValue)} Token · ${formatCost(cost)}`, String(name)];
                            }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </Box>
                  ) : (
                    <EmptyStatePanel
                      title="暂无功能分布数据"
                      description="功能维度会在系统记录到 Token 消耗后自动聚合。"
                      minHeight={340}
                    />
                  )}
                </Box>
              </Grid>

              <Grid item xs={12} xl={7}>
                <Box sx={panelSx}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    高频功能清单
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, mb: 3 }}>
                    结合占比、请求数和成本一起看，能更快识别高消耗功能而不是只盯着 Token 总量。
                  </Typography>

                  {featureData.length > 0 ? (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {featureData.map(item => {
                        const percentage = totalFeatureTokens > 0 ? (item.value / totalFeatureTokens) * 100 : 0;

                        return (
                          <Box
                            key={item.name}
                            sx={{
                              p: 2,
                              borderRadius: 3,
                              border: '1px solid rgba(148, 163, 184, 0.18)',
                              backgroundColor: 'rgba(248,250,252,0.9)',
                            }}
                          >
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center', mb: 1.25 }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2, minWidth: 0 }}>
                                <Box
                                  sx={{
                                    width: 12,
                                    height: 12,
                                    borderRadius: '50%',
                                    backgroundColor: item.color,
                                    flexShrink: 0,
                                  }}
                                />
                                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                  {item.name}
                                </Typography>
                              </Box>
                              <Chip label={`${percentage.toFixed(1)}%`} size="small" />
                            </Box>

                            <LinearProgress
                              variant="determinate"
                              value={Math.max(percentage, percentage > 0 ? 3 : 0)}
                              sx={{
                                height: 8,
                                borderRadius: 999,
                                backgroundColor: 'rgba(226,232,240,0.9)',
                                '& .MuiLinearProgress-bar': {
                                  borderRadius: 999,
                                  backgroundColor: item.color,
                                },
                              }}
                            />

                            <Box
                              sx={{
                                mt: 1.5,
                                display: 'grid',
                                gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(3, minmax(0, 1fr))' },
                                gap: 1.5,
                              }}
                            >
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  Token
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatNumber(item.value)}
                                </Typography>
                              </Box>
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  请求数
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatNumber(item.requests)}
                                </Typography>
                              </Box>
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  成本
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatCost(item.cost)}
                                </Typography>
                              </Box>
                            </Box>
                          </Box>
                        );
                      })}
                    </Box>
                  ) : (
                    <EmptyStatePanel
                      title="暂无功能明细"
                      description="等待功能维度的统计写入后，这里会自动展开占比清单。"
                      minHeight={340}
                    />
                  )}
                </Box>
              </Grid>
            </Grid>
          )}

          {activeTab === 2 && (
            <Grid container spacing={3}>
              <Grid item xs={12} xl={5}>
                <Box sx={panelSx}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    Token 用量分布（按模型）
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, mb: 3 }}>
                    从模型维度观察调用结构，适合识别成本集中在平台模型还是个人 API。
                  </Typography>

                  {modelData.length > 0 ? (
                    <Box sx={{ height: 340 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={modelData} layout="vertical" margin={{ top: 8, right: 12, left: 12, bottom: 8 }}>
                          <CartesianGrid horizontal strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.22)" />
                          <XAxis type="number" tickFormatter={(value) => formatNumber(Number(value))} axisLine={false} tickLine={false} />
                          <YAxis
                            type="category"
                            dataKey="name"
                            width={120}
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: '#475569', fontSize: 12 }}
                          />
                          <RechartsTooltip
                            contentStyle={chartTooltipStyle}
                            formatter={(value, _name, props) => {
                              const numericValue = Number(value || 0);
                              const cost = Number(props?.payload?.cost || 0);
                              const requests = Number(props?.payload?.requests || 0);
                              return [`${formatNumber(numericValue)} Token · ${formatCost(cost)}`, `请求 ${formatNumber(requests)}`];
                            }}
                          />
                          <Bar dataKey="value" radius={[0, 10, 10, 0]}>
                            {modelData.map(item => (
                              <Cell key={item.name} fill={item.color} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </Box>
                  ) : (
                    <EmptyStatePanel
                      title="暂无模型分布数据"
                      description="一旦有模型调用被记录，这里会按模型汇总 Token 与成本。"
                      minHeight={340}
                    />
                  )}
                </Box>
              </Grid>

              <Grid item xs={12} xl={7}>
                <Box sx={panelSx}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    模型清单
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, mb: 3 }}>
                    更适合排查某个模型是否占用了过多预算，或者查看个人模型与平台模型的使用比例。
                  </Typography>

                  {modelData.length > 0 ? (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {modelData.map(item => {
                        const percentage = totalModelTokens > 0 ? (item.value / totalModelTokens) * 100 : 0;

                        return (
                          <Box
                            key={item.name}
                            sx={{
                              p: 2,
                              borderRadius: 3,
                              border: '1px solid rgba(148, 163, 184, 0.18)',
                              backgroundColor: 'rgba(248,250,252,0.9)',
                            }}
                          >
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center', mb: 1.25 }}>
                              <Chip
                                label={item.name}
                                size="small"
                                sx={{ backgroundColor: item.color, color: 'common.white', fontWeight: 700 }}
                              />
                              <Chip label={`${percentage.toFixed(1)}%`} size="small" variant="outlined" />
                            </Box>

                            <LinearProgress
                              variant="determinate"
                              value={Math.max(percentage, percentage > 0 ? 3 : 0)}
                              sx={{
                                height: 8,
                                borderRadius: 999,
                                backgroundColor: 'rgba(226,232,240,0.9)',
                                '& .MuiLinearProgress-bar': {
                                  borderRadius: 999,
                                  backgroundColor: item.color,
                                },
                              }}
                            />

                            <Box
                              sx={{
                                mt: 1.5,
                                display: 'grid',
                                gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(3, minmax(0, 1fr))' },
                                gap: 1.5,
                              }}
                            >
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  Token
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatNumber(item.value)}
                                </Typography>
                              </Box>
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  请求数
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatNumber(item.requests)}
                                </Typography>
                              </Box>
                              <Box>
                                <Typography variant="caption" color="text.secondary">
                                  成本
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {formatCost(item.cost)}
                                </Typography>
                              </Box>
                            </Box>
                          </Box>
                        );
                      })}
                    </Box>
                  ) : (
                    <EmptyStatePanel
                      title="暂无模型明细"
                      description="如果当前时间范围内没有模型调用记录，这里会保持为空。"
                      minHeight={340}
                    />
                  )}
                </Box>
              </Grid>
            </Grid>
          )}

          {activeTab === 3 && (
            <Box sx={panelSx}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap', mb: 3 }}>
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    最近使用记录
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                    最近 50 条调用明细，可直接看到功能、模型、成本和延迟，方便定位异常调用。
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  <Chip label={`记录数 ${recentRecords.length}`} size="small" />
                  <Chip label={`自定义模型 ${customApiRecords}`} size="small" color="success" variant="outlined" />
                </Box>
              </Box>

              {recentRecords.length > 0 ? (
                <TableContainer
                  sx={{
                    maxHeight: 480,
                    borderRadius: 3,
                    border: '1px solid rgba(148, 163, 184, 0.18)',
                  }}
                >
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>时间</TableCell>
                        <TableCell>功能</TableCell>
                        <TableCell>模型</TableCell>
                        <TableCell align="right">输入</TableCell>
                        <TableCell align="right">输出</TableCell>
                        <TableCell align="right">总计</TableCell>
                        <TableCell align="right">成本</TableCell>
                        <TableCell align="right">延迟</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {recentRecords.map(record => (
                        <TableRow
                          key={record.id}
                          sx={{
                            '&:hover': { backgroundColor: 'rgba(248,250,252,0.85)' },
                            '& .MuiTableCell-root': { verticalAlign: 'top' },
                          }}
                        >
                          <TableCell sx={{ whiteSpace: 'nowrap' }}>
                            {new Date(record.created_at).toLocaleString('zh-CN')}
                          </TableCell>
                          <TableCell>
                            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
                              <Tooltip title={record.feature_detail || '无附加说明'}>
                                <Chip
                                  label={FEATURE_LABELS[record.feature_type] || record.feature_type}
                                  size="small"
                                  variant="outlined"
                                  sx={{
                                    borderColor: FEATURE_COLORS[record.feature_type] || '#94A3B8',
                                    color: FEATURE_COLORS[record.feature_type] || '#94A3B8',
                                  }}
                                />
                              </Tooltip>
                              {record.is_custom_api && (
                                <Chip label="自定义" size="small" color="success" variant="outlined" />
                              )}
                            </Box>
                          </TableCell>
                          <TableCell>
                            <Typography
                              variant="body2"
                              sx={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                            >
                              {record.model}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {record.provider}
                            </Typography>
                          </TableCell>
                          <TableCell align="right">{formatNumber(record.prompt_tokens)}</TableCell>
                          <TableCell align="right">{formatNumber(record.completion_tokens)}</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>
                            {formatNumber(record.total_tokens)}
                          </TableCell>
                          <TableCell align="right">{formatCost(record.total_cost)}</TableCell>
                          <TableCell align="right">{Math.round(record.latency_ms)}ms</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              ) : (
                <EmptyStatePanel
                  title="暂无最近调用明细"
                  description="还没有记录到调用明细，或者当前账号尚未产生 Token 消耗。"
                  minHeight={360}
                />
              )}
            </Box>
          )}
        </Box>
      </Paper>

      <Paper sx={{ ...panelSx, p: { xs: 2.5, md: 3 } }}>
        <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 700 }}>
          <InfoIcon fontSize="small" />
          功能边界说明
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 3 }}>
          系统会根据业务场景自动切换模型来源，因此统计页同时承担“成本看板”和“边界说明”两类职责。
        </Typography>

        <Grid container spacing={2.5}>
          <Grid item xs={12} md={6}>
            <Box
              sx={{
                p: 3,
                height: '100%',
                borderRadius: 3,
                border: '1px solid rgba(56, 189, 248, 0.28)',
                background: 'linear-gradient(135deg, rgba(14,165,233,0.12) 0%, rgba(37,99,235,0.04) 100%)',
              }}
            >
              <Chip label="Platform LLM" size="small" sx={{ mb: 1.5 }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                平台模型
              </Typography>
              <Typography variant="body2" color="text.secondary">
                RAG 对话、文档摄入、知识图谱构建、资产生成、文件查询等功能默认使用平台提供的 DeepSeek 模型，费用由平台承担。
              </Typography>
            </Box>
          </Grid>

          <Grid item xs={12} md={6}>
            <Box
              sx={{
                p: 3,
                height: '100%',
                borderRadius: 3,
                border: '1px solid rgba(52, 211, 153, 0.28)',
                background: 'linear-gradient(135deg, rgba(52,211,153,0.12) 0%, rgba(16,185,129,0.04) 100%)',
              }}
            >
              <Chip label="Personal LLM" size="small" color="success" sx={{ mb: 1.5 }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                个人模型
              </Typography>
              <Typography variant="body2" color="text.secondary">
                交易协商、交易定价等交易场景可以使用用户自行配置的 LLM API，相关费用由用户自行承担。
              </Typography>
            </Box>
          </Grid>
        </Grid>

        <Divider sx={{ my: 3 }} />
        <Typography variant="caption" color="text.secondary">
          您可以在 “Agent 配置” 页面配置自己的 LLM API，用于交易相关场景。
        </Typography>
      </Paper>
    </Box>
  );
}
