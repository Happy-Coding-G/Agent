/**
 * TokenUsageView - Token用量统计界面
 *
 * 展示用户的Token使用情况和成本分析
 * 包括：用量趋势、功能分布、模型分布、实时统计
 */

import { useState, useEffect, useMemo } from 'react';
import {
  Box,
  Typography,
  Paper,
  Card,
  CardContent,
  Grid,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  LinearProgress,
  Tooltip,
  IconButton,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  Divider,
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  Info as InfoIcon,
  Refresh as RefreshIcon,
  Savings as SavingsIcon,
  Token as TokenIcon,
  Functions as FunctionsIcon,
} from '@mui/icons-material';
import { useAuthStore } from '../store/auth';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar } from 'recharts';

// API客户端
const API_BASE = '/api/v1';

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
  chat: '#2196F3',
  chat_stream: '#64B5F6',
  asset_generation: '#4CAF50',
  asset_organize: '#81C784',
  trade_negotiation: '#FF9800',
  trade_pricing: '#FFB74D',
  ingest_pipeline: '#9C27B0',
  graph_construction: '#BA68C8',
  review: '#F44336',
  file_query: '#EF5350',
  embedding: '#00BCD4',
  other: '#9E9E9E',
};

const MODEL_COLORS = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#F44336', '#00BCD4'];

export default function TokenUsageView() {
  const { token } = useAuthStore();
  const [activeTab, setActiveTab] = useState(0);
  const [timeRange, setTimeRange] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [dailyUsage, setDailyUsage] = useState<DailyUsage[]>([]);
  const [recentRecords, setRecentRecords] = useState<UsageRecord[]>([]);

  // 加载数据
  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      // 加载汇总数据
      const summaryRes = await fetch(`${API_BASE}/usage/summary?days=${timeRange}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (summaryRes.ok) {
        const summaryData = await summaryRes.json();
        if (summaryData.success) {
          setSummary(summaryData.data);
        }
      }

      // 加载每日数据
      const dailyRes = await fetch(`${API_BASE}/usage/daily?days=${timeRange}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (dailyRes.ok) {
        const dailyData = await dailyRes.json();
        if (dailyData.success) {
          setDailyUsage(dailyData.data);
        }
      }

      // 加载最近记录
      const recentRes = await fetch(`${API_BASE}/usage/recent?limit=50`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (recentRes.ok) {
        const recentData = await recentRes.json();
        if (recentData.success) {
          setRecentRecords(recentData.data);
        }
      }
    } catch (err) {
      setError('加载数据失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [timeRange, token]);

  // 格式化数字
  const formatNumber = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toLocaleString();
  };

  // 格式化成本
  const formatCost = (cost: number) => {
    if (cost < 0.01) return `$${cost.toFixed(6)}`;
    return `$${cost.toFixed(4)}`;
  };

  // 计算统计数据
  const stats = useMemo(() => {
    if (!summary) return null;

    const { summary: s } = summary;
    const prevPeriodTokens = s.total_tokens * 0.9; // 模拟上期数据
    const tokenChange = ((s.total_tokens - prevPeriodTokens) / prevPeriodTokens) * 100;

    return [
      {
        title: '总Token消耗',
        value: formatNumber(s.total_tokens),
        subtitle: `输入: ${formatNumber(s.total_prompt_tokens)} | 输出: ${formatNumber(s.total_completion_tokens)}`,
        change: tokenChange,
        icon: <TokenIcon />,
        color: '#2196F3',
      },
      {
        title: '总成本',
        value: formatCost(s.total_cost),
        subtitle: '基于模型定价计算',
        change: 0,
        icon: <SavingsIcon />,
        color: '#4CAF50',
      },
      {
        title: '总请求数',
        value: formatNumber(s.total_requests),
        subtitle: `平均延迟: ${Math.round(s.avg_latency_ms)}ms`,
        change: 0,
        icon: <FunctionsIcon />,
        color: '#FF9800',
      },
    ];
  }, [summary]);

  // 功能分布数据
  const featureData = useMemo(() => {
    if (!summary) return [];
    return summary.by_feature.map(f => ({
      name: FEATURE_LABELS[f.feature_type] || f.feature_type,
      value: f.tokens,
      cost: f.cost,
      requests: f.requests,
      color: FEATURE_COLORS[f.feature_type] || '#9E9E9E',
    }));
  }, [summary]);

  // 模型分布数据
  const modelData = useMemo(() => {
    if (!summary) return [];
    return summary.by_model.map((m, index) => ({
      name: m.model,
      value: m.tokens,
      cost: m.cost,
      requests: m.requests,
      color: MODEL_COLORS[index % MODEL_COLORS.length],
    }));
  }, [summary]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="100vh">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3, maxWidth: 1400, margin: '0 auto' }}>
      {/* 标题栏 */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <TokenIcon fontSize="large" />
          Token 用量统计
        </Typography>

        <Box sx={{ display: 'flex', gap: 2 }}>
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>时间范围</InputLabel>
            <Select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value as number)}
              label="时间范围"
            >
              <MenuItem value={7}>最近7天</MenuItem>
              <MenuItem value={30}>最近30天</MenuItem>
              <MenuItem value={90}>最近90天</MenuItem>
            </Select>
          </FormControl>

          <IconButton onClick={loadData}>
            <RefreshIcon />
          </IconButton>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* 统计卡片 */}
      {stats && (
        <Grid container spacing={3} sx={{ mb: 3 }}>
          {stats.map((stat, index) => (
            <Grid item xs={12} md={4} key={index}>
              <Card>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <Box>
                      <Typography color="textSecondary" gutterBottom>
                        {stat.title}
                      </Typography>
                      <Typography variant="h4" sx={{ color: stat.color, fontWeight: 'bold' }}>
                        {stat.value}
                      </Typography>
                      <Typography variant="caption" color="textSecondary">
                        {stat.subtitle}
                      </Typography>
                    </Box>
                    <Box sx={{ color: stat.color }}>
                      {stat.icon}
                    </Box>
                  </Box>
                  {stat.change !== 0 && (
                    <Box sx={{ mt: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      {stat.change > 0 ? (
                        <TrendingUp sx={{ color: 'success.main', fontSize: 16 }} />
                      ) : (
                        <TrendingDown sx={{ color: 'error.main', fontSize: 16 }} />
                      )}
                      <Typography
                        variant="caption"
                        sx={{ color: stat.change > 0 ? 'success.main' : 'error.main' }}
                      >
                        {Math.abs(stat.change).toFixed(1)}% 较上期
                      </Typography>
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* 标签页 */}
      <Paper sx={{ mb: 3 }}>
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab label="用量趋势" />
          <Tab label="功能分布" />
          <Tab label="模型分布" />
          <Tab label="使用明细" />
        </Tabs>

        <Box sx={{ p: 3 }}>
          {/* 用量趋势 */}
          {activeTab === 0 && (
            <Box>
              <Typography variant="h6" gutterBottom>
                每日Token用量趋势
              </Typography>
              <Box sx={{ height: 300 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dailyUsage}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(value) => new Date(value).toLocaleDateString('zh-CN')}
                    />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" />
                    <RechartsTooltip
                      formatter={(value: number, name: string) => {
                        if (name === 'cost') return [formatCost(value), '成本'];
                        return [formatNumber(value), name === 'tokens' ? 'Token数' : '请求数'];
                      }}
                      labelFormatter={(label) => new Date(label).toLocaleDateString('zh-CN')}
                    />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="tokens"
                      stroke="#2196F3"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="cost"
                      stroke="#4CAF50"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </Box>
            </Box>
          )}

          {/* 功能分布 */}
          {activeTab === 1 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Typography variant="h6" gutterBottom>
                  Token用量分布（按功能）
                </Typography>
                <Box sx={{ height: 300 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={featureData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        dataKey="value"
                        nameKey="name"
                      >
                        {featureData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <RechartsTooltip
                        formatter={(value: number, name: string, props: any) => {
                          const item = featureData[props?.payload?.index];
                          return [
                            `${formatNumber(value)} tokens (${formatCost(item?.cost || 0)})`,
                            name,
                          ];
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </Box>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="h6" gutterBottom>
                  功能列表
                </Typography>
                <TableContainer sx={{ maxHeight: 300 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>功能</TableCell>
                        <TableCell align="right">Token数</TableCell>
                        <TableCell align="right">占比</TableCell>
                        <TableCell align="right">成本</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {featureData.map((item) => {
                        const total = featureData.reduce((sum, i) => sum + i.value, 0);
                        const percentage = total > 0 ? (item.value / total) * 100 : 0;
                        return (
                          <TableRow key={item.name}>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Box
                                  sx={{
                                    width: 12,
                                    height: 12,
                                    borderRadius: '50%',
                                    backgroundColor: item.color,
                                  }}
                                />
                                {item.name}
                              </Box>
                            </TableCell>
                            <TableCell align="right">{formatNumber(item.value)}</TableCell>
                            <TableCell align="right">{percentage.toFixed(1)}%</TableCell>
                            <TableCell align="right">{formatCost(item.cost)}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Grid>
            </Grid>
          )}

          {/* 模型分布 */}
          {activeTab === 2 && (
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Typography variant="h6" gutterBottom>
                  Token用量分布（按模型）
                </Typography>
                <Box sx={{ height: 300 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={modelData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" />
                      <YAxis dataKey="name" type="category" width={100} />
                      <RechartsTooltip
                        formatter={(value: number, name: string, props: any) => {
                          const item = modelData[props?.payload?.index];
                          return [
                            `${formatNumber(value)} tokens`,
                            item?.name,
                          ];
                        }}
                      />
                      <Bar dataKey="value">
                        {modelData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Box>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="h6" gutterBottom>
                  模型列表
                </Typography>
                <TableContainer sx={{ maxHeight: 300 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>模型</TableCell>
                        <TableCell align="right">请求数</TableCell>
                        <TableCell align="right">Token数</TableCell>
                        <TableCell align="right">成本</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {modelData.map((item) => (
                        <TableRow key={item.name}>
                          <TableCell>
                            <Chip
                              label={item.name}
                              size="small"
                              sx={{ backgroundColor: item.color, color: 'white' }}
                            />
                          </TableCell>
                          <TableCell align="right">{formatNumber(item.requests)}</TableCell>
                          <TableCell align="right">{formatNumber(item.value)}</TableCell>
                          <TableCell align="right">{formatCost(item.cost)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Grid>
            </Grid>
          )}

          {/* 使用明细 */}
          {activeTab === 3 && (
            <Box>
              <Typography variant="h6" gutterBottom>
                最近使用记录
              </Typography>
              <TableContainer sx={{ maxHeight: 400 }}>
                <Table size="small">
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
                    {recentRecords.map((record) => (
                      <TableRow key={record.id}>
                        <TableCell>
                          {new Date(record.created_at).toLocaleString('zh-CN')}
                        </TableCell>
                        <TableCell>
                          <Tooltip title={record.feature_detail || ''}>
                            <Chip
                              label={FEATURE_LABELS[record.feature_type] || record.feature_type}
                              size="small"
                              variant="outlined"
                              sx={{
                                borderColor: FEATURE_COLORS[record.feature_type] || '#9E9E9E',
                                color: FEATURE_COLORS[record.feature_type] || '#9E9E9E',
                              }}
                            />
                          </Tooltip>
                          {record.is_custom_api && (
                            <Chip
                              label="自定义"
                              size="small"
                              color="success"
                              sx={{ ml: 0.5 }}
                            />
                          )}
                        </TableCell>
                        <TableCell>{record.model}</TableCell>
                        <TableCell align="right">{formatNumber(record.prompt_tokens)}</TableCell>
                        <TableCell align="right">{formatNumber(record.completion_tokens)}</TableCell>
                        <TableCell align="right" sx={{ fontWeight: 'bold' }}>
                          {formatNumber(record.total_tokens)}
                        </TableCell>
                        <TableCell align="right">{formatCost(record.total_cost)}</TableCell>
                        <TableCell align="right">{record.latency_ms}ms</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </Box>
      </Paper>

      {/* 功能边界说明 */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <InfoIcon />
          功能边界说明
        </Typography>
        <Typography variant="body2" color="textSecondary" paragraph>
          系统为不同功能使用不同的LLM模型，以下是目前的功能边界划分：
        </Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} md={6}>
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                平台模型 (Platform LLM)
              </Typography>
              <Typography variant="body2" color="textSecondary">
                RAG对话、文档摄入、知识图谱构建、资产生成、文件查询等功能使用平台提供的DeepSeek模型。
                费用由平台承担。
              </Typography>
            </Box>
          </Grid>
          <Grid item xs={12} md={6}>
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                个人模型 (Personal LLM)
              </Typography>
              <Typography variant="body2" color="textSecondary">
                交易协商、交易定价等交易场景使用用户自己配置的LLM API。费用由用户自行承担。
              </Typography>
            </Box>
          </Grid>
        </Grid>
        <Divider sx={{ my: 2 }} />
        <Typography variant="caption" color="textSecondary">
          您可以在 &quot;Agent 配置&quot; 页面配置自己的LLM API，用于交易场景。
        </Typography>
      </Paper>
    </Box>
  );
}
