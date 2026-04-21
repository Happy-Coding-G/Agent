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
  Grid,
  Tabs,
  Tab
} from '@mui/material';
import {
  Visibility,
  VisibilityOff,
  Save as SaveIcon,
  Science as TestIcon,
  SmartToy as AgentIcon,
  Settings as SettingsIcon
} from '@mui/icons-material';
import { useAuth } from '../store/auth';

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
  const token = useAuth(s => s.token);
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
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 900, margin: '0 auto', color: '#E2E8F0' }}>
      <Typography variant="h4" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1.5, fontWeight: 'bold', mb: 2 }}>
        <AgentIcon sx={{ fontSize: 36, color: '#3B82F6' }} />
        Agent 配置
      </Typography>

      <Typography variant="body2" sx={{ mb: 4, color: '#94A3B8', fontSize: '14px', lineHeight: 1.6 }}>
        配置您的个人 LLM API 和交易协商策略。这些设置将用于您的专属 Agent 进行自动化交易协商。
      </Typography>

      {message && (
        <Alert
          severity={message.type}
          sx={{ mb: 3, borderRadius: 2 }}
          onClose={() => setMessage(null)}
        >
          {message.text}
        </Alert>
      )}

      {/* 标签切换 */}
      <Box sx={{ mb: 4, borderBottom: 1, borderColor: 'rgba(255,255,255,0.08)' }}>
        <Tabs 
          value={activeTab} 
          onChange={(_, v) => setActiveTab(v)}
          sx={{ 
            '& .MuiTab-root': { textTransform: 'none', fontSize: '15px', fontWeight: 500, color: '#94A3B8' },
            '& .Mui-selected': { color: '#3B82F6 !important' },
            '& .MuiTabs-indicator': { backgroundColor: '#3B82F6', height: 3 }
          }}
        >
          <Tab value="llm" label="LLM 配置" icon={<SettingsIcon sx={{ mb: 0, mr: 1 }}/>} iconPosition="start" />
          <Tab value="trade" label="交易策略" icon={<AgentIcon sx={{ mb: 0, mr: 1 }}/>} iconPosition="start" />
        </Tabs>
      </Box>

      {activeTab === 'llm' ? (
        <Paper sx={{ 
          p: { xs: 3, md: 4 }, 
          bgcolor: '#1E1E2D', 
          border: '1px solid rgba(255,255,255,0.08)', 
          borderRadius: 3,
          boxShadow: '0 8px 32px rgba(0,0,0,0.2), inset 0 1px 1px rgba(255,255,255,0.05)',
          backdropFilter: 'blur(10px)'
        }}>
          <Typography variant="h6" gutterBottom sx={{ fontWeight: 600, mb: 3 }}>
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

          <Grid container spacing={4}>
            <Grid item xs={12} md={6}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>提供商</Typography>
                <FormControl fullWidth size="small">
                  <Select
                    value={config.llm.provider}
                    onChange={(e) => setConfig({
                      ...config,
                      llm: { ...config.llm, provider: e.target.value, model: '' }
                    })}
                    sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                  >
                    {providers.map(p => (
                      <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>模型</Typography>
                <FormControl fullWidth size="small">
                  <Select
                    value={config.llm.model}
                    onChange={(e) => setConfig({
                      ...config,
                      llm: { ...config.llm, model: e.target.value }
                    })}
                    sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                  >
                    {availableModels.map(m => (
                      <MenuItem key={m} value={m}>{m}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>
            </Grid>

            <Grid item xs={12}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>API Key</Typography>
                <TextField
                  fullWidth
                  size="small"
                  type={showApiKey ? 'text' : 'password'}
                  value={config.llm.api_key}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, api_key: e.target.value }
                  })}
                  placeholder={config.has_custom_api_key ? "•••••••• (已配置，留空保持不变)" : "输入您的 API Key"}
                  sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowApiKey(!showApiKey)} sx={{ color: '#94A3B8' }}>
                          {showApiKey ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
                <Typography variant="caption" sx={{ display: 'block', mt: 1, color: '#64748B', fontSize: '12px' }}>
                  您的 API Key 将被加密存储，仅供您的专属 Agent 交易协商时使用。
                </Typography>
              </Box>
            </Grid>

            {config.llm.provider === 'custom' && (
              <Grid item xs={12}>
                <Box>
                  <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>Base URL</Typography>
                  <TextField
                    fullWidth
                    size="small"
                    value={config.llm.base_url}
                    onChange={(e) => setConfig({
                      ...config,
                      llm: { ...config.llm, base_url: e.target.value }
                    })}
                    placeholder="https://api.example.com/v1"
                    sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                  />
                </Box>
              </Grid>
            )}

            <Grid item xs={12} md={6}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1.5, color: '#94A3B8', fontSize: '13px' }}>
                  Temperature <span style={{ color: '#E2E8F0', fontWeight: 'bold', marginLeft: 8 }}>{config.llm.temperature}</span>
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
                    { value: 0, label: <span style={{ color: '#64748B', fontSize: '12px' }}>确定</span> },
                    { value: 1, label: <span style={{ color: '#64748B', fontSize: '12px' }}>平衡</span> },
                    { value: 2, label: <span style={{ color: '#64748B', fontSize: '12px' }}>创意</span> },
                  ]}
                  sx={{ color: '#3B82F6', '& .MuiSlider-markLabel': { mt: 0.5 } }}
                />
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>Max Tokens</Typography>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  value={config.llm.max_tokens}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, max_tokens: parseInt(e.target.value) }
                  })}
                  inputProps={{ min: 100, max: 8192 }}
                  sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                />
              </Box>
            </Grid>

            <Grid item xs={12}>
              <Box>
                <Typography variant="body2" sx={{ mb: 1, color: '#94A3B8', fontSize: '13px' }}>系统提示词 (可选)</Typography>
                <TextField
                  fullWidth
                  multiline
                  rows={3}
                  value={config.llm.system_prompt}
                  onChange={(e) => setConfig({
                    ...config,
                    llm: { ...config.llm, system_prompt: e.target.value }
                  })}
                  placeholder="自定义 Agent 的行为和风格..."
                  sx={{ bgcolor: '#2A2A3A', borderRadius: 1.5, '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' } }}
                />
              </Box>
            </Grid>
          </Grid>

          <Divider sx={{ my: 3 }} />

          <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
            <Button
              variant="contained"
              onClick={saveLLMConfig}
              disabled={saving}
              startIcon={saving ? <CircularProgress size={20} color="inherit" /> : <SaveIcon />}
              sx={{ 
                bgcolor: '#3B82F6', 
                color: '#fff', 
                fontWeight: 'bold', 
                textTransform: 'none', 
                borderRadius: 2, 
                px: 3, 
                py: 1,
                boxShadow: '0 4px 14px rgba(59, 130, 246, 0.4)',
                '&:hover': { bgcolor: '#2563EB' } 
              }}
            >
              保存配置
            </Button>
            <Button
              variant="outlined"
              onClick={testConnection}
              disabled={testing}
              startIcon={testing ? <CircularProgress size={20} color="inherit" /> : <TestIcon />}
              sx={{ 
                color: '#E2E8F0', 
                borderColor: 'rgba(255,255,255,0.2)', 
                textTransform: 'none', 
                borderRadius: 2, 
                px: 3, 
                py: 1,
                bgcolor: 'rgba(255,255,255,0.05)',
                '&:hover': { borderColor: 'rgba(255,255,255,0.3)', bgcolor: 'rgba(255,255,255,0.1)' } 
              }}
            >
              测试连接
            </Button>
          </Box>
        </Paper>
      ) : (
        <Paper sx={{ 
          p: { xs: 3, md: 4 }, 
          bgcolor: '#1E1E2D', 
          border: '1px solid rgba(255,255,255,0.08)', 
          borderRadius: 3,
          boxShadow: '0 8px 32px rgba(0,0,0,0.2), inset 0 1px 1px rgba(255,255,255,0.05)',
          backdropFilter: 'blur(10px)'
        }}>
          <Typography variant="h6" gutterBottom sx={{ fontWeight: 600, mb: 3 }}>
            交易协商策略
          </Typography>

          <Grid container spacing={4}>
            <Grid item xs={12}>
              <Box sx={{ bgcolor: '#2A2A3A', p: 3, borderRadius: 2, border: '1px solid rgba(255,255,255,0.08)' }}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={config.trade.auto_negotiate}
                      onChange={(e) => setConfig({
                        ...config,
                        trade: { ...config.trade, auto_negotiate: e.target.checked }
                      })}
                      color="primary"
                    />
                  }
                  label={<Typography sx={{ fontWeight: 'medium' }}>启用自动协商</Typography>}
                  sx={{ color: '#E2E8F0' }}
                />
                <Typography variant="body2" sx={{ color: '#94A3B8', mt: 1, ml: 4 }}>
                  开启后，Agent 将根据您的策略自动与对方进行价格协商
                </Typography>
              </Box>
            </Grid>

            <Grid item xs={12}>
              <Box sx={{ px: 1 }}>
                <Typography variant="body2" sx={{ mb: 1.5, color: '#94A3B8', fontSize: '13px' }}>
                  最大协商轮数 <span style={{ color: '#E2E8F0', fontWeight: 'bold', marginLeft: 8 }}>{config.trade.max_rounds}</span>
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
                    { value: 5, label: <span style={{ color: '#64748B', fontSize: '12px' }}>5</span> },
                    { value: 10, label: <span style={{ color: '#64748B', fontSize: '12px' }}>10</span> },
                    { value: 20, label: <span style={{ color: '#64748B', fontSize: '12px' }}>20</span> },
                    { value: 50, label: <span style={{ color: '#64748B', fontSize: '12px' }}>50</span> },
                  ]}
                  sx={{ color: '#3B82F6', '& .MuiSlider-markLabel': { mt: 0.5 } }}
                />
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Card sx={{ bgcolor: '#2A2A3A', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 2 }}>
                <CardContent sx={{ p: 3 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ color: '#3B82F6', fontWeight: 600, mb: 2 }}>
                    卖方策略
                  </Typography>
                  <Typography variant="body2" sx={{ mb: 1, color: '#E2E8F0' }}>
                    最小利润率 <span style={{ fontWeight: 'bold', marginLeft: 8 }}>{(config.trade.min_profit_margin * 100).toFixed(0)}%</span>
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
                    sx={{ color: '#3B82F6' }}
                  />
                  <Typography variant="caption" sx={{ color: '#94A3B8', display: 'block', mt: 1 }}>
                    低于此利润率的报价将被自动拒绝
                  </Typography>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={6}>
              <Card sx={{ bgcolor: '#2A2A3A', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 2 }}>
                <CardContent sx={{ p: 3 }}>
                  <Typography variant="subtitle1" gutterBottom sx={{ color: '#8B5CF6', fontWeight: 600, mb: 2 }}>
                    买方策略
                  </Typography>
                  <Typography variant="body2" sx={{ mb: 1, color: '#E2E8F0' }}>
                    最大预算比例 <span style={{ fontWeight: 'bold', marginLeft: 8 }}>{(config.trade.max_budget_ratio * 100).toFixed(0)}%</span>
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
                    sx={{ color: '#8B5CF6' }}
                  />
                  <Typography variant="caption" sx={{ color: '#94A3B8', display: 'block', mt: 1 }}>
                    高于此预算比例的报价将被自动拒绝
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Divider sx={{ my: 4, borderColor: 'rgba(255,255,255,0.05)' }} />

          <Box sx={{ mt: 1 }}>
            <Button
              variant="contained"
              onClick={saveTradeConfig}
              disabled={saving}
              startIcon={saving ? <CircularProgress size={20} color="inherit" /> : <SaveIcon />}
              sx={{ 
                bgcolor: '#3B82F6', 
                color: '#fff', 
                fontWeight: 'bold', 
                textTransform: 'none', 
                borderRadius: 2, 
                px: 3, 
                py: 1,
                boxShadow: '0 4px 14px rgba(59, 130, 246, 0.4)',
                '&:hover': { bgcolor: '#2563EB' } 
              }}
            >
              保存策略
            </Button>
          </Box>

        </Paper>
      )}
    </Box>
  );
}
