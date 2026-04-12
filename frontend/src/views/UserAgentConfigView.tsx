/**
 * UserAgentConfigView - 用户Agent配置界面
 *
 * 配置个人LLM API和交易协商策略
 */

import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Switch,
  FormControlLabel,
  Button,
  Divider,
  Alert,
  Chip,
  Slider,
  InputAdornment,
  IconButton,
  Tooltip,
  CircularProgress,
  Card,
  CardContent,
  Grid
} from '@mui/material';
import {
  Visibility,
  VisibilityOff,
  Save as SaveIcon,
  Test as TestIcon,
  SmartToy as AgentIcon,
  Settings as SettingsIcon
} from '@mui/icons-material';
import { useAuthStore } from '../store/auth';

// API客户端
const API_BASE = '/api/v1';

interface LLMConfig {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
}

interface TradeConfig {
  auto_negotiate: boolean;
  max_rounds: number;
  min_profit_margin: number;
  max_budget_ratio: number;
}

interface UserConfig {
  llm: LLMConfig;
  trade: TradeConfig;
  has_custom_api_key: boolean;
}

const defaultConfig: UserConfig = {
  llm: {
    provider: 'deepseek',
    model: 'deepseek-chat',
    api_key: '',
    base_url: '',
    temperature: 0.2,
    max_tokens: 2048,
    system_prompt: '',
  },
  trade: {
    auto_negotiate: false,
    max_rounds: 10,
    min_profit_margin: 0.1,
    max_budget_ratio: 0.9,
  },
  has_custom_api_key: false,
};

const providers = [
  { value: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-coder'] },
  { value: 'openai', label: 'OpenAI', models: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'] },
  { value: 'qwen', label: '通义千问', models: ['qwen-turbo', 'qwen-plus', 'qwen-max'] },
  { value: 'custom', label: '自定义', models: ['custom'] },
];

export default function UserAgentConfigView() {
  const { token } = useAuthStore();
  const [config, setConfig] = useState<UserConfig>(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [showApiKey, setShowApiKey] = useState(false);
  const [activeTab, setActiveTab] = useState<'llm' | 'trade'>('llm');

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const response = await fetch(`${API_BASE}/user/agent/config`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        const data = await response.json();
        setConfig({
          llm: {
            provider: data.provider || 'deepseek',
            model: data.model || 'deepseek-chat',
            api_key: '', // API Key不返回，保持为空
            base_url: data.base_url || '',
            temperature: data.temperature || 0.2,
            max_tokens: data.max_tokens || 2048,
            system_prompt: data.system_prompt || '',
          },
          trade: {
            auto_negotiate: data.trade_auto_negotiate || false,
            max_rounds: data.trade_max_rounds || 10,
            min_profit_margin: data.trade_min_profit_margin || 0.1,
            max_budget_ratio: data.trade_max_budget_ratio || 0.9,
          },
          has_custom_api_key: data.has_custom_api_key || false,
        });
      }
    } catch (error) {
      console.error('Failed to load config:', error);
      setMessage({ type: 'error', text: '加载配置失败' });
    } finally {
      setLoading(false);
    }
  };

  // 保存LLM配置
  const saveLLMConfig = async () => {
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/user/agent/config/llm`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          provider: config.llm.provider,
          model: config.llm.model,
          api_key: config.llm.api_key || undefined,
          base_url: config.llm.base_url || undefined,
          temperature: config.llm.temperature,
          max_tokens: config.llm.max_tokens,
          system_prompt: config.llm.system_prompt || undefined,
        }),
      });

      if (response.ok) {
        setMessage({ type: 'success', text: 'LLM配置保存成功' });
        setConfig(prev => ({ ...prev, has_custom_api_key: !!config.llm.api_key }));
      } else {
        throw new Error('Save failed');
      }
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败，请检查输入' });
    } finally {
      setSaving(false);
    }
  };

  // 保存交易配置
  const saveTradeConfig = async () => {
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/user/agent/config/trade`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          auto_negotiate: config.trade.auto_negotiate,
          max_rounds: config.trade.max_rounds,
          min_profit_margin: config.trade.min_profit_margin,
          max_budget_ratio: config.trade.max_budget_ratio,
        }),
      });

      if (response.ok) {
        setMessage({ type: 'success', text: '交易配置保存成功' });
      } else {
        throw new Error('Save failed');
      }
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败' });
    } finally {
      setSaving(false);
    }
  };

  // 测试LLM连接
  const testConnection = async () => {
    setTesting(true);
    try {
      const response = await fetch(`${API_BASE}/user/agent/test-llm`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });

      const data = await response.json();

      if (data.success) {
        setMessage({
          type: 'success',
          text: `连接成功！延迟: ${data.latency_ms?.toFixed(0) || 'N/A'}ms`
        });
      } else {
        setMessage({ type: 'error', text: `连接失败: ${data.message}` });
      }
    } catch (error) {
      setMessage({ type: 'error', text: '测试连接失败' });
    } finally {
      setTesting(false);
    }
  };

  // 获取当前提供商支持的模型
  const availableModels = providers.find(p => p.value === config.llm.provider)?.models || [];

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="100vh">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3, maxWidth: 900, margin: '0 auto' }}>
      <Typography variant="h4" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <AgentIcon fontSize="large" />
        Agent 配置
      </Typography>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        配置您的个人 LLM API 和交易协商策略。这些设置将用于您的专属 Agent 进行自动化交易协商。
      </Typography>

      {message && (
        <Alert
          severity={message.type}
          sx={{ mb: 2 }}
          onClose={() => setMessage(null)}
        >
          {message.text}
        </Alert>
      )}

      {/* 标签切换 */}
      <Box sx={{ mb: 3, display: 'flex', gap: 1 }}>
        <Button
          variant={activeTab === 'llm' ? 'contained' : 'outlined'}
          onClick={() => setActiveTab('llm')}
          startIcon={<SettingsIcon />}
        >
          LLM 配置
        </Button>
        <Button
          variant={activeTab === 'trade' ? 'contained' : 'outlined'}
          onClick={() => setActiveTab('trade')}
          startIcon={<AgentIcon />}
        >
          交易策略
        </Button>
      </Box>

      {activeTab === 'llm' ? (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            LLM 配置
          </Typography>

          {config.has_custom_api_key && (
            <Chip
              label="已配置自定义 API Key"
              color="success"
              size="small"
              sx={{ mb: 2 }}
            />
          )}

          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>提供商</InputLabel>
                <Select
                  value={config.llm.provider}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, provider: e.target.value, model: '' }
                  })}
                >
                  {providers.map(p => (
                    <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>模型</InputLabel>
                <Select
                  value={config.llm.model}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, model: e.target.value }
                  })}
                >
                  {availableModels.map(m => (
                    <MenuItem key={m} value={m}>{m}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12}>
              <TextField
                fullWidth
                label="API Key"
                type={showApiKey ? 'text' : 'password'}
                value={config.llm.api_key}
                onChange={(e) => setConfig({
                  ...config,
                  llm: { ...config.llm, api_key: e.target.value }
                })}
                placeholder={config.has_custom_api_key ? "•••••••• (已配置，留空保持不变)" : "输入您的 API Key"}
                helperText="您的 API Key 将被加密存储"
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton onClick={() => setShowApiKey(!showApiKey)}>
                        {showApiKey ? <VisibilityOff /> : <Visibility />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
            </Grid>

            {config.llm.provider === 'custom' && (
              <Grid item xs={12}>
                <TextField
                  fullWidth
                  label="Base URL"
                  value={config.llm.base_url}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, base_url: e.target.value }
                  })}
                  placeholder="https://api.example.com/v1"
                />
              </Grid>
            )}

            <Grid item xs={12} md={6}>
              <Typography gutterBottom>
                Temperature: {config.llm.temperature}
              </Typography>
              <Slider
                value={config.llm.temperature}
                onChange={(_, v) => setConfig({
                  ...config,
                  llm: { ...config.llm, temperature: v as number }
                })}
                min={0}
                max={2}
                step={0.1}
                marks={[
                  { value: 0, label: '确定' },
                  { value: 1, label: '平衡' },
                  { value: 2, label: '创意' },
                ]}
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                label="Max Tokens"
                type="number"
                value={config.llm.max_tokens}
                onChange={(e) => setConfig({
                  ...config,
                  llm: { ...config.llm, max_tokens: parseInt(e.target.value) }
                })}
                inputProps={{ min: 100, max: 8192 }}
              />
            </Grid>

            <Grid item xs={12}>
              <TextField
                fullWidth
                multiline
                rows={3}
                label="系统提示词 (可选)"
                value={config.llm.system_prompt}
                onChange={(e) => setConfig({
                  ...config,
                  llm: { ...config.llm, system_prompt: e.target.value }
                })}
                placeholder="自定义 Agent 的行为和风格..."
              />
            </Grid>
          </Grid>

          <Divider sx={{ my: 3 }} />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              onClick={saveLLMConfig}
              disabled={saving}
              startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
            >
              保存配置
            </Button>
            <Button
              variant="outlined"
              onClick={testConnection}
              disabled={testing}
              startIcon={testing ? <CircularProgress size={20} /> : <TestIcon />}
            >
              测试连接
            </Button>
          </Box>
        </Paper>
      ) : (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            交易协商策略
          </Typography>

          <Grid container spacing={3}>
            <Grid item xs={12}>
              <FormControlLabel
                control={
                  <Switch
                    checked={config.trade.auto_negotiate}
                    onChange={(e) => setConfig({
                      ...config,
                      trade: { ...config.trade, auto_negotiate: e.target.checked }
                    })}
                  />
                }
                label="启用自动协商"
              />
              <Typography variant="caption" color="text.secondary" display="block">
                开启后，Agent 将根据您的策略自动与对方进行价格协商
              </Typography>
            </Grid>

            <Grid item xs={12}>
              <Typography gutterBottom>
                最大协商轮数: {config.trade.max_rounds}
              </Typography>
              <Slider
                value={config.trade.max_rounds}
                onChange={(_, v) => setConfig({
                  ...config,
                  trade: { ...config.trade, max_rounds: v as number }
                })}
                min={1}
                max={50}
                step={1}
                marks={[
                  { value: 5, label: '5' },
                  { value: 10, label: '10' },
                  { value: 20, label: '20' },
                  { value: 50, label: '50' },
                ]}
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom color="primary">
                    卖方策略
                  </Typography>
                  <Typography gutterBottom>
                    最小利润率: {(config.trade.min_profit_margin * 100).toFixed(0)}%
                  </Typography>
                  <Slider
                    value={config.trade.min_profit_margin}
                    onChange={(_, v) => setConfig({
                      ...config,
                      trade: { ...config.trade, min_profit_margin: v as number }
                    })}
                    min={0}
                    max={1}
                    step={0.05}
                    valueLabelDisplay="auto"
                    valueLabelFormat={(v) => `${(v * 100).toFixed(0)}%`}
                  />
                  <Typography variant="caption" color="text.secondary">
                    低于此利润率的报价将被自动拒绝
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={6}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom color="secondary">
                    买方策略
                  </Typography>
                  <Typography gutterBottom>
                    最大预算比例: {(config.trade.max_budget_ratio * 100).toFixed(0)}%
                  </Typography>
                  <Slider
                    value={config.trade.max_budget_ratio}
                    onChange={(_, v) => setConfig({
                      ...config,
                      trade: { ...config.trade, max_budget_ratio: v as number }
                    })}
                    min={0}
                    max={1}
                    step={0.05}
                    valueLabelDisplay="auto"
                    valueLabelFormat={(v) => `${(v * 100).toFixed(0)}%`}
                  />
                  <Typography variant="caption" color="text.secondary">
                    高于此预算比例的报价将被自动拒绝
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Divider sx={{ my: 3 }} />

          <Button
            variant="contained"
            onClick={saveTradeConfig}
            disabled={saving}
            startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
          >
            保存策略
          </Button>
        </Paper>
      )}
    </Box>
  );
}
