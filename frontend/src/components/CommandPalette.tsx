import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, Cpu, X, Download, Loader2, Trash2, Check, Cloud, Key, Eye, EyeOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '../lib/store';
import {
  pullModel,
  deleteModel,
  fetchModels,
  preloadModel,
  isTauri,
  getCloudConfigStatus,
  getCloudKeyStatus,
  saveCloudKey,
  saveCloudKeys,
} from '../lib/api';

/** Popular models that users can download from the catalogue. */
const CATALOGUE_MODELS = [
  { id: 'qwen3.5:0.8b', size: '~1 GB', desc: 'Qwen 3.5 0.8B — fast, lightweight' },
  { id: 'qwen3.5:2b', size: '~2.7 GB', desc: 'Qwen 3.5 2B' },
  { id: 'qwen3.5:4b', size: '~3.4 GB', desc: 'Qwen 3.5 4B — recommended default' },
  { id: 'qwen3.5:9b', size: '~6.6 GB', desc: 'Qwen 3.5 9B' },
  { id: 'qwen3.5:27b', size: '~17 GB', desc: 'Qwen 3.5 27B' },
  { id: 'qwen3.5:35b', size: '~24 GB', desc: 'Qwen 3.5 35B' },
  { id: 'qwen3.5:122b', size: '~81 GB', desc: 'Qwen 3.5 122B — largest' },
  { id: 'llama3.3:latest', size: '~4.9 GB', desc: 'Llama 3.3 8B' },
  { id: 'mistral:latest', size: '~4.1 GB', desc: 'Mistral 7B' },
  { id: 'gemma3:latest', size: '~3.3 GB', desc: 'Gemma 3 4B' },
  { id: 'deepseek-r1:7b', size: '~4.7 GB', desc: 'DeepSeek R1 7B' },
  { id: 'phi4:latest', size: '~9.1 GB', desc: 'Phi-4 14B' },
];

/** Cloud provider definitions */
interface CloudProvider {
  name: string;
  envKey: string;
  models: Array<{ id: string; desc: string }>;
}

const CLOUD_PROVIDERS: CloudProvider[] = [
  {
    name: 'OpenAI',
    envKey: 'OPENAI_API_KEY',
    models: [
      { id: 'gpt-4o', desc: 'GPT-4o — fast, multimodal' },
      { id: 'gpt-4o-mini', desc: 'GPT-4o Mini — cheap, fast' },
      { id: 'o3-mini', desc: 'o3-mini — reasoning' },
    ],
  },
  {
    name: 'Anthropic',
    envKey: 'ANTHROPIC_API_KEY',
    models: [
      { id: 'claude-sonnet-4-6', desc: 'Claude Sonnet 4.6 — balanced' },
      { id: 'claude-opus-4-6', desc: 'Claude Opus 4.6 — most capable' },
      { id: 'claude-haiku-4-5', desc: 'Claude Haiku 4.5 — fastest' },
    ],
  },
  {
    name: 'Google',
    envKey: 'GEMINI_API_KEY',
    models: [
      { id: 'gemini-3.8-flash', desc: 'Gemini 3.8 Flash — fast' },
      { id: 'gemini-3.1-pro-preview', desc: 'Gemini 3.1 Pro Preview — reasoning' },
      { id: 'gemini-3.1-flash-lite', desc: 'Gemini 3.1 Flash Lite — lightweight' },
    ],
  },
  {
    name: 'OpenRouter',
    envKey: 'OPENROUTER_API_KEY',
    models: [
      { id: 'openrouter/auto', desc: 'Auto — best model for the task' },
      { id: 'openrouter/anthropic/claude-sonnet-4.5', desc: 'Claude Sonnet 4.5 via OpenRouter' },
      { id: 'openrouter/deepseek/deepseek-r1-0528', desc: 'DeepSeek R1 via OpenRouter' },
    ],
  },
  {
    name: 'Atlas Cloud',
    envKey: 'ATLASCLOUD_API_KEY',
    models: [
      { id: 'atlascloud/openai/gpt-4.1-mini', desc: 'GPT-4.1 Mini via Atlas Cloud' },
      { id: 'atlascloud/deepseek-ai/deepseek-v3.2', desc: 'DeepSeek V3.2 via Atlas Cloud' },
      { id: 'atlascloud/Qwen/Qwen3-235B-A22B-Instruct-2507', desc: 'Qwen3 235B via Atlas Cloud' },
    ],
  },
  {
    name: 'Azure OpenAI',
    envKey: 'AZURE_OPENAI_API_KEY',
    models: [],
  },
];

type Tab = 'installed' | 'catalogue' | 'cloud';

export function CommandPalette() {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [tab, setTab] = useState<Tab>('installed');
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);
  const [pullSuccess, setPullSuccess] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [customModel, setCustomModel] = useState('');
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [cloudKeyStatus, setCloudKeyStatus] = useState<Record<string, boolean>>({});
  const [cloudKeyError, setCloudKeyError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const setModels = useAppStore((s) => s.setModels);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);

  const [azureEndpoint, setAzureEndpoint] = useState('');
  const [azureDeployment, setAzureDeployment] = useState('');
  const [azureApiVersion, setAzureApiVersion] = useState('2024-10-21');
  const [azureDeployments, setAzureDeployments] = useState<string[]>([]);

  const installedIds = new Set(models.map((m) => m.id));
  const desktopKeyStorage = isTauri();

  const refreshCloudKeyStatus = useCallback(async () => {
    try {
      if (desktopKeyStorage) {
        setCloudKeyStatus(await getCloudKeyStatus());
      } else {
        const cfg = await getCloudConfigStatus();
        setCloudKeyStatus(cfg.keys ?? {});
        setAzureDeployments(cfg.azure_deployments ?? []);
        if (cfg.azure_endpoint) setAzureEndpoint(cfg.azure_endpoint);
        if (cfg.azure_deployments?.length) setAzureDeployment(cfg.azure_deployments.join(', '));
        if (cfg.azure_api_version) setAzureApiVersion(cfg.azure_api_version);
      }
      setCloudKeyError(null);
    } catch (e: any) {
      setCloudKeyError(e?.message || t('commandPalette.errors.readCloudKeyStatusFailed'));
    }
  }, [desktopKeyStorage, t]);

  const filtered = tab === 'installed'
    ? (query
        ? models.filter((m) => m.id.toLowerCase().includes(query.toLowerCase()))
        : models)
    : tab === 'catalogue'
    ? CATALOGUE_MODELS.filter((m) =>
        !installedIds.has(m.id) &&
        (!query || m.id.toLowerCase().includes(query.toLowerCase()) || m.desc.toLowerCase().includes(query.toLowerCase()))
      )
    : []; // cloud tab doesn't use filtered

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    void refreshCloudKeyStatus();
  }, [refreshCloudKeyStatus]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query, tab]);

  useEffect(() => {
    if (pullSuccess) {
      const t = setTimeout(() => setPullSuccess(null), 3000);
      return () => clearTimeout(t);
    }
  }, [pullSuccess]);

  const handleSelect = async (modelId: string, owner?: string) => {
    const previousModel = selectedModel;
    setSelectedModel(modelId);
    setCommandPaletteOpen(false);

    if (modelId !== previousModel) {
      const { setModelLoading, addLogEntry } = useAppStore.getState();
      setModelLoading(true);
      addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `Switching to ${modelId}...` });
      try {
        await preloadModel(modelId, owner);
        addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `${modelId} loaded` });
      } catch (e: any) {
        addLogEntry({ timestamp: Date.now(), level: 'error', category: 'model', message: `Failed to load ${modelId}: ${e.message}` });
      } finally {
        setModelLoading(false);
      }
    }
  };

  const refreshModels = async () => {
    try {
      const m = await fetchModels();
      setModels(m);
    } catch {}
  };

  const handlePull = async (modelId: string) => {
    setPulling(modelId);
    setPullError(null);
    try {
      await pullModel(modelId);
      setPullSuccess(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Downloaded ${modelId}`,
      });
      await refreshModels();
      setSelectedModel(modelId);
    } catch (e: any) {
      setPullError(e.message || t('commandPalette.errors.downloadFailed'));
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'error', category: 'model',
        message: `Download failed for ${modelId}: ${e.message}`,
      });
    } finally {
      setPulling(null);
    }
  };

  const handleDelete = async (modelId: string) => {
    setDeleting(modelId);
    try {
      await deleteModel(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Deleted ${modelId}`,
      });
      await refreshModels();
      if (selectedModel === modelId) {
        const remaining = models.filter((m) => m.id !== modelId);
        if (remaining.length > 0) setSelectedModel(remaining[0].id);
      }
    } catch {} finally {
      setDeleting(null);
    }
  };

  const handleCustomPull = async () => {
    const name = customModel.trim();
    if (!name) return;
    await handlePull(name);
    setCustomModel('');
  };

  const handleSaveKey = async (provider: CloudProvider, value: string) => {
    const keyValue = value.trim();
    setSavingKey(provider.envKey);
    setCloudKeyError(null);

    try {
      await saveCloudKey(provider.envKey, keyValue);
      setApiKeys((prev) => ({ ...prev, [provider.envKey]: '' }));
      await refreshCloudKeyStatus();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `${provider.name} API key ${keyValue ? 'saved' : 'removed'}. Refreshing model list...`,
      });
      await refreshModels();
    } catch (e: any) {
      setCloudKeyError(e?.message || t('commandPalette.errors.saveKeyFailed', { provider: provider.name }));
    } finally {
      setSavingKey(null);
    }
  };

  const handleSaveAzureConfig = async () => {
    setSavingKey('AZURE_OPENAI_API_KEY');
    setCloudKeyError(null);
    try {
      const updates: Record<string, string> = {
        AZURE_OPENAI_ENDPOINT: azureEndpoint.trim(),
        AZURE_OPENAI_DEPLOYMENT: azureDeployment.trim(),
        AZURE_OPENAI_API_VERSION: azureApiVersion.trim() || '2024-10-21',
      };
      const typedKey = apiKeys['AZURE_OPENAI_API_KEY']?.trim();
      if (typedKey) {
        updates['AZURE_OPENAI_API_KEY'] = typedKey;
      }
      await saveCloudKeys(updates);
      setApiKeys((prev) => ({ ...prev, AZURE_OPENAI_API_KEY: '' }));
      await refreshCloudKeyStatus();
      await refreshModels();
    } catch (e: any) {
      setCloudKeyError(e?.message || t('commandPalette.errors.saveKeyFailed', { provider: 'Azure OpenAI' }));
    } finally {
      setSavingKey(null);
    }
  };

  const handleKeyBlur = (provider: CloudProvider) => {
    const draft = apiKeys[provider.envKey] || '';
    if (draft.trim()) void handleSaveKey(provider, draft);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setCommandPaletteOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && tab === 'installed' && filtered.length > 0) {
      e.preventDefault();
      const model = filtered[selectedIdx] as (typeof models)[number];
      handleSelect(model.id, model.owned_by);
    }
  };

  const TAB_LABELS: Record<Tab, string> = {
    installed: t('commandPalette.tabs.installed', { count: models.length }),
    catalogue: t('commandPalette.tabs.catalogue'),
    cloud: t('commandPalette.tabs.cloud'),
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      onClick={() => setCommandPaletteOpen(false)}
    >
      <div className="fixed inset-0" style={{ background: 'rgba(0,0,0,0.5)' }} />

      <div
        className="relative w-full max-w-lg rounded-xl overflow-hidden"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Tabs */}
        <div className="flex" style={{ borderBottom: '1px solid var(--color-border)' }}>
          {(['installed', 'catalogue', 'cloud'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex-1 px-3 py-2.5 text-xs font-medium transition-colors cursor-pointer"
              style={{
                color: tab === t ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                borderBottom: tab === t ? '2px solid var(--color-accent)' : '2px solid transparent',
                background: 'transparent',
              }}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {/* Search (not for cloud tab) */}
        {tab !== 'cloud' && (
          <div
            className="flex items-center gap-3 px-4 py-3"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <Search size={18} style={{ color: 'var(--color-text-tertiary)' }} />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={tab === 'installed' ? t('commandPalette.search.installedPlaceholder') : t('commandPalette.search.cataloguePlaceholder')}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
            <button
              onClick={() => setCommandPaletteOpen(false)}
              className="p-1 rounded cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Status messages */}
        {pullError && (
          <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-error)', background: 'rgba(220,38,38,0.05)' }}>
            {pullError}
          </div>
        )}
        {pullSuccess && (
          <div className="px-4 py-2 text-xs flex items-center gap-1.5" style={{ color: 'var(--color-success)', background: 'color-mix(in srgb, var(--color-success) 5%, transparent)' }}>
            <Check size={12} /> {t('commandPalette.status.downloadedSuccessfully', { model: pullSuccess })}
          </div>
        )}
        {tab === 'cloud' && cloudKeyError && (
          <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-error)', background: 'rgba(220,38,38,0.05)' }}>
            {cloudKeyError}
          </div>
        )}

        {/* Results */}
        <div className="max-h-[400px] overflow-y-auto py-2">
          {tab === 'installed' ? (
            filtered.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                {models.length === 0
                  ? t('commandPalette.emptyState.noModelsAvailable')
                  : t('commandPalette.emptyState.noMatchingModels')}
              </div>
            ) : (
              (filtered as typeof models).map((model, idx) => {
                const isActive = model.id === selectedModel;
                const isSelected = idx === selectedIdx;
                const isDeleting = deleting === model.id;
                return (
                  <div
                    key={model.id}
                    className="flex items-center gap-3 w-full px-4 py-2.5 transition-colors"
                    style={{ background: isSelected ? 'var(--color-bg-secondary)' : 'transparent' }}
                    onMouseEnter={() => setSelectedIdx(idx)}
                  >
                    <button
                      onClick={() => handleSelect(model.id, model.owned_by)}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left cursor-pointer"
                      style={{ background: 'none', border: 'none', padding: 0 }}
                    >
                      {model.owned_by === 'litellm' ? (
                        <Cloud size={16} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                      ) : (
                        <Cpu size={16} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate" style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text)', fontWeight: isActive ? 500 : 400 }}>
                          {model.id}
                        </div>
                      </div>
                      {isActive && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
                          {t('commandPalette.badges.active')}
                        </span>
                      )}
                    </button>
                    {model.owned_by !== 'litellm' && (
                      <button
                        onClick={() => handleDelete(model.id)}
                        disabled={isDeleting}
                        className="p-1 rounded transition-colors cursor-pointer"
                        style={{ color: 'var(--color-text-tertiary)', opacity: 0 }}
                        title={t('commandPalette.tooltips.deleteModel')}
                        onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--color-error)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.opacity = '0'; e.currentTarget.style.color = 'var(--color-text-tertiary)'; }}
                      >
                        {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                      </button>
                    )}
                  </div>
                );
              })
            )
          ) : tab === 'catalogue' ? (
            <>
              {(filtered as typeof CATALOGUE_MODELS).map((model) => {
                const isPulling = pulling === model.id;
                const justInstalled = pullSuccess === model.id;
                return (
                  <div key={model.id} className="flex items-center gap-3 w-full px-4 py-2.5">
                    <Download size={16} style={{ color: 'var(--color-text-tertiary)' }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate" style={{ color: 'var(--color-text)' }}>{model.id}</div>
                      <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>{model.desc} &middot; {model.size}</div>
                    </div>
                    <button
                      onClick={() => handlePull(model.id)}
                      disabled={isPulling || !!pulling}
                      className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium cursor-pointer"
                      style={{
                        background: justInstalled ? 'var(--color-accent-subtle)' : 'var(--color-accent)',
                        color: justInstalled ? 'var(--color-accent)' : 'var(--color-on-accent)',
                        opacity: (isPulling || (pulling && !isPulling)) ? 0.5 : 1,
                      }}
                    >
                      {isPulling ? <><Loader2 size={12} className="animate-spin" /> {t('commandPalette.catalogue.downloading')}</> :
                       justInstalled ? <><Check size={12} /> {t('commandPalette.catalogue.installed')}</> :
                       <><Download size={12} /> {t('commandPalette.catalogue.download')}</>}
                    </button>
                  </div>
                );
              })}
              <div className="px-4 py-3 mt-1" style={{ borderTop: '1px solid var(--color-border)' }}>
                <div className="text-[11px] mb-2" style={{ color: 'var(--color-text-tertiary)' }}>{t('commandPalette.catalogue.customModelLabel')}</div>
                <div className="flex gap-2">
                  <input
                    type="text" value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleCustomPull(); } }}
                    placeholder={t('commandPalette.catalogue.customModelPlaceholder')}
                    className="flex-1 text-sm px-3 py-1.5 rounded-lg outline-none"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
                  />
                  <button
                    onClick={handleCustomPull} disabled={!customModel.trim() || !!pulling}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
                    style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', opacity: (!customModel.trim() || pulling) ? 0.5 : 1 }}
                  >
                    <Download size={12} /> {t('commandPalette.catalogue.pull')}
                  </button>
                </div>
              </div>
            </>
          ) : (
            /* ── Cloud Models tab ── */
            <div className="px-4 py-2">
              <div className="text-[11px] mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
                {desktopKeyStorage
                  ? t('commandPalette.cloud.desktopKeyStorageInfo')
                  : t('commandPalette.cloud.serverKeyStorageInfo')}
              </div>

              {CLOUD_PROVIDERS.map((provider) => {
                const key = apiKeys[provider.envKey] || '';
                const hasSavedKey = !!cloudKeyStatus[provider.envKey];
                const hasKey = hasSavedKey || !!key.trim();
                const isVisible = showKeys[provider.envKey];
                const isSaving = savingKey === provider.envKey;

                return (
                  <div key={provider.name} className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Cloud size={14} style={{ color: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)' }} />
                      <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>{provider.name}</span>
                      {hasKey && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: 'color-mix(in srgb, var(--color-success) 10%, transparent)', color: 'var(--color-success)' }}>
                          {t('commandPalette.cloud.connected')}
                        </span>
                      )}
                    </div>

                    {/* API key input */}
                    <div className="flex gap-1.5 mb-2">
                      <div className="flex-1 flex items-center rounded-lg" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                        <Key size={12} className="ml-2.5 shrink-0" style={{ color: 'var(--color-text-tertiary)' }} />
                        <input
                          type={isVisible ? 'text' : 'password'}
                          value={key}
                          onChange={(e) => setApiKeys((prev) => ({ ...prev, [provider.envKey]: e.target.value }))}
                          onBlur={() => handleKeyBlur(provider)}
                          placeholder={hasSavedKey ? t('commandPalette.cloud.savedInSecureStorage') : provider.envKey}
                          disabled={isSaving}
                          className="flex-1 text-xs px-2 py-1.5 bg-transparent outline-none font-mono"
                          style={{ color: 'var(--color-text)' }}
                        />
                        <button
                          onClick={() => setShowKeys((prev) => ({ ...prev, [provider.envKey]: !prev[provider.envKey] }))}
                          className="px-2 cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}
                        >
                          {isVisible ? <EyeOff size={12} /> : <Eye size={12} />}
                        </button>
                      </div>
                      {hasSavedKey && (
                        <button
                          onClick={() => handleSaveKey(provider, '')}
                          disabled={isSaving}
                          className="px-2 py-1 rounded-lg text-[10px] cursor-pointer"
                          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)', opacity: isSaving ? 0.5 : 1 }}
                        >
                          {isSaving ? t('commandPalette.cloud.saving') : t('commandPalette.cloud.remove')}
                        </button>
                      )}
                    </div>

                    {/* Azure OpenAI endpoint / deployment / api-version */}
                    {provider.envKey === 'AZURE_OPENAI_API_KEY' && (
                      <div className="mb-2 flex flex-col gap-1.5">
                        <input
                          type="text"
                          value={azureEndpoint}
                          onChange={(e) => setAzureEndpoint(e.target.value)}
                          placeholder="AZURE_OPENAI_ENDPOINT (https://<resource>.openai.azure.com)"
                          disabled={isSaving}
                          className="w-full text-xs px-2.5 py-1.5 rounded-lg outline-none font-mono"
                          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                        />
                        <div className="flex gap-1.5">
                          <input
                            type="text"
                            value={azureDeployment}
                            onChange={(e) => setAzureDeployment(e.target.value)}
                            placeholder="Deployment(s) (ex: gpt-4o)"
                            disabled={isSaving}
                            className="flex-1 text-xs px-2.5 py-1.5 rounded-lg outline-none font-mono"
                            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                          />
                          <input
                            type="text"
                            value={azureApiVersion}
                            onChange={(e) => setAzureApiVersion(e.target.value)}
                            placeholder="2024-10-21"
                            disabled={isSaving}
                            className="w-28 text-xs px-2.5 py-1.5 rounded-lg outline-none font-mono"
                            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                          />
                          <button
                            onClick={() => void handleSaveAzureConfig()}
                            disabled={isSaving || !azureEndpoint.trim() || !azureDeployment.trim()}
                            className="px-2.5 py-1 rounded-lg text-[11px] font-medium cursor-pointer disabled:opacity-40"
                            style={{ background: 'var(--color-accent)', color: 'white' }}
                          >
                            {isSaving ? t('commandPalette.cloud.saving') : 'Salvar'}
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Models for this provider (only show if key is set) */}
                    {hasKey && (
                      <div className="ml-5 flex flex-col gap-1">
                        {(provider.envKey === 'AZURE_OPENAI_API_KEY'
                          ? azureDeployments.map((dep) => ({
                              id: `azure/${dep}`,
                              desc: `Azure OpenAI deployment (${dep})`,
                            }))
                          : provider.models
                        ).map((model) => {
                          const isActive = model.id === selectedModel;
                          return (
                            <button
                              key={model.id}
                              onClick={() => handleSelect(model.id)}
                              className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left cursor-pointer transition-colors"
                              style={{ background: isActive ? 'var(--color-accent-subtle)' : 'transparent' }}
                              onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
                              onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                            >
                              <Cloud size={12} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                              <div className="flex-1 min-w-0">
                                <div className="text-xs truncate" style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text)', fontWeight: isActive ? 500 : 400 }}>
                                  {model.id}
                                </div>
                                <div className="text-[10px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                                  {model.desc}
                                </div>
                              </div>
                              {isActive && (
                                <span className="text-[9px] px-1.5 py-0.5 rounded-full shrink-0" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
                                  {t('commandPalette.badges.active')}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-4 px-4 py-2 text-[11px]"
          style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          {tab === 'installed' ? (
            <>
              <span><kbd className="font-mono">↑↓</kbd> {t('commandPalette.footer.navigate')}</span>
              <span><kbd className="font-mono">Enter</kbd> {t('commandPalette.footer.select')}</span>
              <span><kbd className="font-mono">Esc</kbd> {t('commandPalette.footer.close')}</span>
            </>
          ) : tab === 'catalogue' ? (
            <span>{t('commandPalette.footer.catalogueHint')}</span>
          ) : (
            <span>{t('commandPalette.footer.cloudHint')}</span>
          )}
        </div>
      </div>
    </div>
  );
}
