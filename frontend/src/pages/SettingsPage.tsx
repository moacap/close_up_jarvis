import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { Language } from '../i18n';
import {
  Palette,
  Globe,
  Cpu,
  Database,
  Info,
  Check,
  Sun,
  Moon,
  Monitor,
  Download,
  Upload,
  Trash2,
  Mic,
  Key,
  Search,
  Brain,
  RefreshCw,
} from 'lucide-react';
import { useAppStore, type ThemeMode } from '../lib/store';
import { deviceTimeZone, listTimeZones, resolveTimeZone, utcOffsetLabel } from '../lib/timezone';
import {
  checkHealth,
  fetchSpeechHealth,
  fetchTtsHealth,
  synthesizeSpeech,
  getMemoryStats,
  getInferenceSource,
  setInferenceSource,
  getCloudKeyStatus,
  saveCloudKey,
  fetchToolCredentialStatus,
  saveToolCredentials,
  deleteToolCredential,
  isTauri,
  type InferenceSource,
  type MemoryStats,
} from '../lib/api';
import { isAutoUpdateDisabled, setAutoUpdateDisabled } from '../components/Desktop/UpdateChecker';

const CLOUD_KEY_STATUS_CHANGED = 'openjarvis-cloud-key-status-changed';

function OllamaModelList() {
  const { t } = useTranslation();
  const [models, setModels] = useState<Array<{ name: string; size: number }>>([]);
  useEffect(() => {
    fetch('http://localhost:11434/api/tags')
      .then(r => r.json())
      .then(data => setModels((data.models || []).map((m: any) => ({ name: m.name, size: m.size }))))
      .catch(() => setModels([]));
  }, []);
  if (models.length === 0) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{t('settings.models.noModelsLoaded')}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {models.map(m => (
        <span key={m.name} className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px]"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', display: 'inline-block' }} />
          {m.name} ({(m.size / 1e9).toFixed(1)} GB)
        </span>
      ))}
    </div>
  );
}

function ApiKeyInput({
  keyName,
  placeholder,
  toolName,
  isSecret = true,
}: {
  keyName: string;
  placeholder: string;
  toolName?: string;
  isSecret?: boolean;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [error, setError] = useState('');
  const desktopKeyStorage = isTauri();
  const serverToolStorage = !desktopKeyStorage && !!toolName;

  const refresh = useCallback(async () => {
    try {
      const status = serverToolStorage
        ? await fetchToolCredentialStatus(toolName!)
        : await getCloudKeyStatus();
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [keyName, serverToolStorage, toolName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  const save = async (v: string) => {
    const next = v.trim();
    if (!next) return;
    setError('');
    try {
      if (serverToolStorage) {
        await saveToolCredentials(toolName!, { [keyName]: next });
      } else {
        await saveCloudKey(keyName, next);
      }
      setValue('');
      setHasKey(true);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || t('settings.apiKeys.saveFailed'));
    }
  };

  const remove = async () => {
    setError('');
    try {
      if (serverToolStorage) {
        await deleteToolCredential(toolName!, keyName);
      } else {
        await saveCloudKey(keyName, '');
      }
      setValue('');
      setHasKey(false);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || t('settings.apiKeys.removeFailed'));
    }
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type={isSecret ? 'password' : 'text'}
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={() => { if (value.trim()) void save(value); }}
        onKeyDown={e => {
          if (e.key === 'Enter' && value.trim()) {
            e.preventDefault();
            void save(value);
          }
        }}
        placeholder={hasKey ? (desktopKeyStorage ? t('settings.apiKeys.savedInSecureStorage') : t('settings.apiKeys.savedByLocalServer')) : placeholder}
        className="w-48 px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      {hasKey && (
        <button
          onClick={() => void remove()}
          className="px-2 py-1 rounded text-[10px] cursor-pointer"
          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
        >
          {t('settings.apiKeys.remove')}
        </button>
      )}
      {saved && <span className="text-[10px]" style={{ color: 'var(--color-success)' }}>{t('settings.apiKeys.saved')}</span>}
      {error && <span className="text-[10px]" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

function CloudProviderStatus({ label, keyName }: { label: string; keyName: string }) {
  const [hasKey, setHasKey] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const status = await getCloudKeyStatus();
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [keyName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  return (
    <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
        background: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)',
      }} />
      {label}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div className="min-w-0">
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>{label}</div>
        {description && (
          <div className="text-xs mt-0.5 break-words" style={{ color: 'var(--color-text-tertiary)' }}>{description}</div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

type MemoryStatus =
  | { kind: 'loading' }
  | { kind: 'ready'; stats: MemoryStats }
  | { kind: 'error'; message: string };

export function MemoryStatusRow({
  status,
  onRetry,
}: {
  status: MemoryStatus;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const stats = status.kind === 'ready' ? status.stats : null;
  const description = status.kind === 'error'
    ? status.message
    : status.kind === 'loading'
      ? t('settings.memory.status.checkingBackend')
      : stats?.backend === 'none'
        ? t('settings.memory.status.notConfiguredDescription')
        : t('settings.memory.status.backendEntries', { backend: stats?.backend, count: stats?.entries });
  const label = status.kind === 'loading'
    ? t('settings.memory.status.checkingLabel')
    : stats?.backend === 'none'
      ? t('settings.memory.status.notConfiguredLabel')
      : stats
        ? t('settings.memory.status.entriesCount', { count: stats.entries })
        : t('settings.memory.status.unavailable');

  return (
    <SettingRow label={t('settings.memory.status.label')} description={description}>
      <div className="flex items-center gap-2">
        <Brain size={14} style={{ color: stats && stats.backend !== 'none' ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
        <span className="text-xs whitespace-nowrap" style={{ color: 'var(--color-text-secondary)' }}>
          {label}
        </span>
        {status.kind === 'error' && (
          <button
            type="button"
            onClick={onRetry}
            className="text-xs underline cursor-pointer whitespace-nowrap"
            style={{ color: 'var(--color-accent)' }}
          >
            {t('settings.memory.status.retry')}
          </button>
        )}
      </div>
    </SettingRow>
  );
}

const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'settings.appearance.theme.light', icon: Sun },
  { value: 'dark', label: 'settings.appearance.theme.dark', icon: Moon },
  { value: 'system', label: 'settings.appearance.theme.system', icon: Monitor },
];

export function SettingsPage() {
  const { t } = useTranslation();
  const settings = useAppStore((s) => s.settings);
  const timeZones = useMemo(listTimeZones, []);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const conversations = useAppStore((s) => s.conversations);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [speechBackendAvailable, setSpeechBackendAvailable] = useState<boolean | null>(null);
  const [ttsBackend, setTtsBackend] = useState<{ available: boolean; backend?: string; voice_id?: string; voices?: string[] } | null>(null);
  const [testingVoice, setTestingVoice] = useState(false);
  const [saved, setSaved] = useState(false);

  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(() => !isAutoUpdateDisabled());
  const [updateCheckState, setUpdateCheckState] = useState<'idle' | 'checking' | 'available' | 'latest'>('idle');

  const handleAutoUpdateToggle = useCallback((enabled: boolean) => {
    setAutoUpdateEnabled(enabled);
    setAutoUpdateDisabled(!enabled);
  }, []);

  const handleCheckNow = useCallback(async () => {
    if (!(window as any).__TAURI_INTERNALS__) return;
    setUpdateCheckState('checking');
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      setUpdateCheckState(update ? 'available' : 'latest');
      setTimeout(() => setUpdateCheckState('idle'), 4000);
    } catch {
      setUpdateCheckState('idle');
    }
  }, []);

  const [memoryStatus, setMemoryStatus] = useState<MemoryStatus>({ kind: 'loading' });
  const memoryRequestId = useRef(0);
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-enabled') !== 'false'; } catch { return true; }
  });
  const [memoryBackend, setMemoryBackend] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-backend') || 'sqlite'; } catch { return 'sqlite'; }
  });
  const [memoryTopK, setMemoryTopK] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-top-k') || '5'); } catch { return 5; }
  });
  const [memoryMinScore, setMemoryMinScore] = useState(() => {
    try { return parseFloat(localStorage.getItem('openjarvis-memory-min-score') || '0.1'); } catch { return 0.1; }
  });
  const [memoryMaxTokens, setMemoryMaxTokens] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-max-tokens') || '2048'); } catch { return 2048; }
  });

  const [srcKind, setSrcKind] = useState<InferenceSource['kind']>('ollama');
  const [customHost, setCustomHost] = useState('http://localhost:1234/v1');
  const [customModel, setCustomModel] = useState('');
  const [customEngine, setCustomEngine] = useState('lmstudio');
  const [customKey, setCustomKey] = useState('');
  const [srcMsg, setSrcMsg] = useState('');

  useEffect(() => {
    getInferenceSource().then((s) => {
      setSrcKind(s.kind);
      if (s.host) setCustomHost(s.host);
      if (s.model) setCustomModel(s.model);
      if (s.engine) setCustomEngine(s.engine);
    }).catch(() => {});
  }, []);

  const saveSource = useCallback(async () => {
    try {
      if (srcKind === 'custom') {
        await setInferenceSource({ kind: 'custom', host: customHost, model: customModel, engine: customEngine, apiKey: customKey || undefined });
      } else {
        await setInferenceSource({ kind: 'ollama' });
      }
      setSrcMsg(t('settings.inferenceSource.save.success'));
    } catch (e: any) {
      setSrcMsg(e?.message ?? t('settings.inferenceSource.save.failed'));
    }
  }, [srcKind, customHost, customModel, customEngine, customKey, t]);

  const refreshMemoryStatus = useCallback(async () => {
    const requestId = ++memoryRequestId.current;
    setMemoryStatus({ kind: 'loading' });
    try {
      const stats = await getMemoryStats();
      if (requestId === memoryRequestId.current) {
        setMemoryStatus({ kind: 'ready', stats });
      }
    } catch (error) {
      if (requestId === memoryRequestId.current) {
        setMemoryStatus({
          kind: 'error',
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }, []);

  useEffect(() => {
    void refreshMemoryStatus();
    const onFocus = () => { void refreshMemoryStatus(); };
    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      ++memoryRequestId.current;
    };
  }, [refreshMemoryStatus, settings.apiUrl]);

  useEffect(() => {
    checkHealth().then(setHealthy);
    fetchSpeechHealth()
      .then((h) => setSpeechBackendAvailable(h.available))
      .catch(() => setSpeechBackendAvailable(false));
    fetchTtsHealth()
      .then((h) => setTtsBackend(h))
      .catch(() => setTtsBackend({ available: false }));
  }, []);

  const showSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const handleExport = () => {
    const data = localStorage.getItem('openjarvis-conversations') || '{}';
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `openjarvis-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target?.result as string);
          if (data.version === 1) {
            localStorage.setItem('openjarvis-conversations', JSON.stringify(data));
            useAppStore.getState().loadConversations();
            showSaved();
          }
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const [confirmClear, setConfirmClear] = useState(false);
  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    localStorage.removeItem('openjarvis-conversations');
    useAppStore.getState().loadConversations();
    setConfirmClear(false);
    showSaved();
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              {t('settings.page.title')}
            </h1>
            {saved && (
              <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-full" style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-success)',
              }}>
                <Check size={12} /> {t('settings.page.savedBadge')}
              </span>
            )}
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            {t('settings.page.subtitle')}
          </p>
        </header>

        <div className="flex flex-col gap-4">
          {/* Appearance */}
          <Section title={t('settings.appearance.title')}>
            <SettingRow label={t('settings.appearance.theme.label')} description={t('settings.appearance.theme.description')}>
              <div className="flex gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                {themeOptions.map((opt) => {
                  const isActive = settings.theme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => { updateSettings({ theme: opt.value }); showSaved(); }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: isActive ? 'var(--color-surface)' : 'transparent',
                        color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                      }}
                    >
                      <opt.icon size={14} />
                      {t(opt.label)}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
            <SettingRow label={t('settings.appearance.fontSize.label')}>
              <select
                value={settings.fontSize}
                onChange={(e) => { updateSettings({ fontSize: e.target.value as any }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="small">{t('settings.appearance.fontSize.small')}</option>
                <option value="default">{t('settings.appearance.fontSize.default')}</option>
                <option value="large">{t('settings.appearance.fontSize.large')}</option>
              </select>
            </SettingRow>
            <SettingRow label={t('settings.language.label')} description={t('settings.language.description')}>
              <select
                aria-label={t('settings.language.label')}
                value={settings.language}
                onChange={(e) => { updateSettings({ language: e.target.value as Language }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="en">English</option>
                <option value="pt">Português</option>
                <option value="es">Español</option>
              </select>
            </SettingRow>
            <SettingRow
              label={t('settings.appearance.timeZone.label')}
              description={t('settings.appearance.timeZone.description', { zone: resolveTimeZone(settings.timeZone), offset: utcOffsetLabel(resolveTimeZone(settings.timeZone)) })}
            >
              <select
                aria-label={t('settings.appearance.timeZone.label')}
                value={settings.timeZone}
                onChange={(e) => { updateSettings({ timeZone: e.target.value }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer max-w-[14rem]"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="">{t('settings.appearance.timeZone.automatic', { zone: deviceTimeZone() })}</option>
                {timeZones.map((zone) => (
                  <option key={zone} value={zone}>{zone}</option>
                ))}
              </select>
            </SettingRow>
          </Section>

          {/* Connection */}
          <Section title={t('settings.connection.title')}>
            <SettingRow label={t('settings.connection.serverStatus.label')} description={serverInfo ? `${serverInfo.engine} / ${serverInfo.model}` : t('settings.connection.serverStatus.notConnected')}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: healthy === true ? 'var(--color-success)' : healthy === false ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {healthy === true ? t('settings.connection.serverStatus.connected') : healthy === false ? t('settings.connection.serverStatus.disconnected') : t('settings.connection.serverStatus.checking')}
                </span>
              </div>
            </SettingRow>
            <SettingRow label={t('settings.connection.apiUrl.label')} description={t('settings.connection.apiUrl.description')}>
              <input
                type="text"
                value={settings.apiUrl}
                onChange={(e) => { updateSettings({ apiUrl: e.target.value }); showSaved(); }}
                placeholder="http://localhost:8000"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
            <SettingRow label={t('settings.connection.apiKey.label')} description={t('settings.connection.apiKey.description')}>
              <input
                type="password"
                value={settings.apiKey}
                onChange={(e) => { updateSettings({ apiKey: e.target.value }); showSaved(); }}
                placeholder="OPENJARVIS_API_KEY"
                autoComplete="off"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
          </Section>

          {/* Inference source */}
          <Section title={t('settings.inferenceSource.title')}>
            <SettingRow label={t('settings.inferenceSource.source.label')} description={t('settings.inferenceSource.source.description')}>
              <select
                value={srcKind}
                onChange={(e) => { setSrcKind(e.target.value as InferenceSource['kind']); setSrcMsg(''); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              >
                <option value="ollama">{t('settings.inferenceSource.source.ollamaOption')}</option>
                <option value="custom">{t('settings.inferenceSource.source.customOption')}</option>
              </select>
            </SettingRow>
            {srcKind === 'custom' && (
              <>
                <SettingRow label={t('settings.inferenceSource.serverUrl.label')} description={t('settings.inferenceSource.serverUrl.description')}>
                  <input type="text" value={customHost} onChange={(e) => { setCustomHost(e.target.value); setSrcMsg(''); }} placeholder="http://localhost:1234/v1"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label={t('settings.inferenceSource.model.label')} description={t('settings.inferenceSource.model.description')}>
                  <input type="text" value={customModel} onChange={(e) => { setCustomModel(e.target.value); setSrcMsg(''); }} placeholder="qwen2.5-7b-instruct"
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label={t('settings.inferenceSource.serverType.label')} description={t('settings.inferenceSource.serverType.description')}>
                  <select value={customEngine} onChange={(e) => { setCustomEngine(e.target.value); setSrcMsg(''); }}
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                    <option value="lmstudio">LM Studio</option>
                    <option value="vllm">vLLM</option>
                    <option value="sglang">SGLang</option>
                    <option value="llamacpp">llama.cpp</option>
                    <option value="mlx">MLX</option>
                  </select>
                </SettingRow>
                <SettingRow label={t('settings.inferenceSource.apiKeyOptional.label')} description={t('settings.inferenceSource.apiKeyOptional.description')}>
                  <input type="password" value={customKey} onChange={(e) => { setCustomKey(e.target.value); setSrcMsg(''); }} placeholder={t('settings.inferenceSource.apiKeyOptional.placeholder')}
                    className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
              </>
            )}
            <SettingRow label="" description={srcMsg}>
              <button onClick={saveSource}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{ background: 'var(--color-accent, var(--color-bg-tertiary))', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                {t('settings.inferenceSource.save.button')}
              </button>
            </SettingRow>
          </Section>

          {/* Models */}
          <Section title={t('settings.models.title')}>
            <SettingRow label={t('settings.models.localModels.label')} description={t('settings.models.localModels.description')}>
              <OllamaModelList />
            </SettingRow>
            <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('settings.models.ollamaHint.before')} <code className="px-1 py-0.5 rounded text-[11px]" style={{ background: 'var(--color-bg-tertiary)' }}>ollama pull &lt;model-name&gt;</code> {t('settings.models.ollamaHint.after')}
            </div>
            <SettingRow label={t('settings.models.cloudProviders.label')} description={t('settings.models.cloudProviders.description')}>
              <div className="flex flex-wrap gap-3">
                <CloudProviderStatus label="OpenAI" keyName="OPENAI_API_KEY" />
                <CloudProviderStatus label="Anthropic" keyName="ANTHROPIC_API_KEY" />
                <CloudProviderStatus label="Google" keyName="GEMINI_API_KEY" />
                <CloudProviderStatus label="OpenRouter" keyName="OPENROUTER_API_KEY" />
                <CloudProviderStatus label="Atlas Cloud" keyName="ATLASCLOUD_API_KEY" />
                <CloudProviderStatus label="Azure OpenAI" keyName="AZURE_OPENAI_API_KEY" />
              </div>
            </SettingRow>
          </Section>

          {/* API Keys */}
          <Section title={t('settings.apiKeys.title')}>
            <SettingRow label="OpenAI" description={t('settings.apiKeys.openai.description')}>
              <ApiKeyInput keyName="OPENAI_API_KEY" placeholder="sk-..." />
            </SettingRow>
            <SettingRow label="Anthropic" description={t('settings.apiKeys.anthropic.description')}>
              <ApiKeyInput keyName="ANTHROPIC_API_KEY" placeholder="sk-ant-..." />
            </SettingRow>
            <SettingRow label="Google" description={t('settings.apiKeys.google.description')}>
              <ApiKeyInput keyName="GEMINI_API_KEY" placeholder="AI..." />
            </SettingRow>
            <SettingRow label="OpenRouter" description={t('settings.apiKeys.openrouter.description')}>
              <ApiKeyInput keyName="OPENROUTER_API_KEY" placeholder="sk-or-..." />
            </SettingRow>
            <SettingRow label="Atlas Cloud" description={t('settings.apiKeys.atlasCloud.description')}>
              <ApiKeyInput keyName="ATLASCLOUD_API_KEY" placeholder={t('settings.apiKeys.atlasCloud.placeholder')} />
            </SettingRow>
            <SettingRow label="Azure OpenAI (API Key)" description="Chave de API do recurso Azure OpenAI / Azure AI Foundry">
              <ApiKeyInput keyName="AZURE_OPENAI_API_KEY" placeholder="Azure API key..." />
            </SettingRow>
            <SettingRow label="Azure OpenAI (Endpoint)" description="URL do recurso (ex.: https://seu-recurso.openai.azure.com)">
              <ApiKeyInput keyName="AZURE_OPENAI_ENDPOINT" placeholder="https://<resource>.openai.azure.com" isSecret={false} />
            </SettingRow>
            <SettingRow label="Azure OpenAI (Deployment)" description="Nome(s) do(s) deployment(s), separados por vírgula">
              <ApiKeyInput keyName="AZURE_OPENAI_DEPLOYMENT" placeholder="gpt-4o" isSecret={false} />
            </SettingRow>
            <SettingRow label="Azure OpenAI (API Version)" description="Versão da API (padrão: 2024-10-21)">
              <ApiKeyInput keyName="AZURE_OPENAI_API_VERSION" placeholder="2024-10-21" isSecret={false} />
            </SettingRow>
          </Section>

          {/* Tools */}
          <Section title={t('settings.tools.title')}>
            <SettingRow label={t('settings.tools.webSearch.label')} description={t('settings.tools.webSearch.description')}>
              <ApiKeyInput keyName="TAVILY_API_KEY" placeholder="tvly-..." toolName="web_search" />
            </SettingRow>
          </Section>

          {/* Memory */}
          <Section title={t('settings.memory.title')}>
            <MemoryStatusRow status={memoryStatus} onRetry={() => { void refreshMemoryStatus(); }} />
            <SettingRow label={t('settings.memory.useContext.label')} description={t('settings.memory.useContext.description')}>
              <button
                onClick={() => {
                  const next = !memoryEnabled;
                  setMemoryEnabled(next);
                  try { localStorage.setItem('openjarvis-memory-enabled', String(next)); } catch {}
                  showSaved();
                }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: memoryEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: memoryEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.memory.backend.label')} description={t('settings.memory.backend.description')}>
              <select
                value={memoryBackend}
                onChange={(e) => {
                  setMemoryBackend(e.target.value);
                  try { localStorage.setItem('openjarvis-memory-backend', e.target.value); } catch {}
                  showSaved();
                }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="sqlite">sqlite</option>
                <option value="faiss">faiss</option>
                <option value="bm25">bm25</option>
                <option value="colbert">colbert</option>
                <option value="hybrid">hybrid</option>
              </select>
            </SettingRow>
            <SettingRow label={t('settings.memory.topK.label')} description={`${memoryTopK}`}>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={memoryTopK}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryTopK(v);
                  try { localStorage.setItem('openjarvis-memory-top-k', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.memory.minScore.label')} description={`${memoryMinScore}`}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={memoryMinScore}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setMemoryMinScore(v);
                  try { localStorage.setItem('openjarvis-memory-min-score', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.memory.maxTokens.label')} description={`${memoryMaxTokens}`}>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={memoryMaxTokens}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryMaxTokens(v);
                  try { localStorage.setItem('openjarvis-memory-max-tokens', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Model defaults */}
          <Section title={t('settings.modelDefaults.title')}>
            <SettingRow label={t('settings.modelDefaults.temperature.label')} description={`${settings.temperature}`}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => { updateSettings({ temperature: parseFloat(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label={t('settings.modelDefaults.maxTokens.label')} description={`${settings.maxTokens}`}>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                value={settings.maxTokens}
                onChange={(e) => { updateSettings({ maxTokens: parseInt(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Speech */}
          <Section title={t('settings.speech.title')}>
            <SettingRow label={t('settings.speech.stt.label')} description={t('settings.speech.stt.description')}>
              <button
                onClick={() => { updateSettings({ speechEnabled: !settings.speechEnabled }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.speechEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speechEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.speech.tts.label')} description={t('settings.speech.tts.description')}>
              <button
                onClick={() => { updateSettings({ voiceOutputEnabled: !settings.voiceOutputEnabled }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.voiceOutputEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.voiceOutputEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.speech.autoplay.label')} description={t('settings.speech.autoplay.description')}>
              <button
                onClick={() => { updateSettings({ voiceAutoplay: !settings.voiceAutoplay }); showSaved(); }}
                disabled={!settings.voiceOutputEnabled}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.voiceAutoplay && settings.voiceOutputEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                  opacity: settings.voiceOutputEnabled ? 1 : 0.4,
                  cursor: settings.voiceOutputEnabled ? 'pointer' : 'default',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.voiceAutoplay && settings.voiceOutputEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.speech.voice.label')} description={t('settings.speech.voice.description')}>
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: ttsBackend?.available ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                  }}
                />
                {ttsBackend?.available && (ttsBackend.voices?.length ?? 0) > 0 ? (
                  <>
                    <select
                      value={settings.ttsVoice || ttsBackend.voice_id || ''}
                      onChange={(e) => {
                        updateSettings({ ttsVoice: e.target.value });
                        showSaved();
                      }}
                      className="px-2.5 py-1 rounded text-xs cursor-pointer"
                      style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    >
                      {ttsBackend.voices!.map((v) => (
                        <option key={v} value={v}>
                          {v} ({ttsBackend.backend})
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={async () => {
                        if (testingVoice) return;
                        setTestingVoice(true);
                        try {
                          const voiceId = settings.ttsVoice || ttsBackend.voice_id;
                          const language = settings.ttsLanguage || undefined;
                          const sampleText =
                            language?.startsWith('en')
                              ? 'Hello, this is the selected voice in Close-UP.'
                              : language?.startsWith('es')
                              ? 'Hola, esta es la voz seleccionada en Close-UP.'
                              : 'Olá, esta é a voz selecionada no Close-UP.';
                          const blob = await synthesizeSpeech(
                            sampleText,
                            { voiceId, language },
                          );
                          const url = URL.createObjectURL(blob);
                          const audio = new Audio(url);
                          audio.onended = () => URL.revokeObjectURL(url);
                          await audio.play();
                        } catch {
                          // Ignore playback errors in test button
                        } finally {
                          setTestingVoice(false);
                        }
                      }}
                      disabled={testingVoice}
                      className="px-2.5 py-1 rounded text-xs cursor-pointer disabled:opacity-50"
                      style={{
                        background: 'var(--color-bg-tertiary)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    >
                      {testingVoice ? 'Gerando...' : 'Testar voz'}
                    </button>
                  </>
                ) : (
                  <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {ttsBackend === null ? t('settings.speech.voice.checking')
                      : ttsBackend.available ? `${ttsBackend.backend}${ttsBackend.voice_id ? ` / ${ttsBackend.voice_id}` : ''}`
                      : t('settings.speech.voice.notConfigured')}
                  </span>
                )}
              </div>
            </SettingRow>
            <SettingRow label="Idioma do TTS" description="Idioma preferido para síntese de voz (TTS)">
              <select
                value={settings.ttsLanguage || ''}
                onChange={(e) => {
                  updateSettings({ ttsLanguage: e.target.value });
                  showSaved();
                }}
                className="px-2.5 py-1 rounded text-xs cursor-pointer"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              >
                <option value="">Automático (padrão)</option>
                <option value="pt-BR">Português (pt-BR)</option>
                <option value="en-US">English (en-US)</option>
                <option value="es-ES">Español (es-ES)</option>
                <option value="fr-FR">Français (fr-FR)</option>
                <option value="de-DE">Deutsch (de-DE)</option>
                <option value="it-IT">Italiano (it-IT)</option>
              </select>
            </SettingRow>
            <SettingRow label={t('settings.speech.backendStatus.label')} description={t('settings.speech.backendStatus.description')}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: speechBackendAvailable === true ? 'var(--color-success)'
                      : speechBackendAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {speechBackendAvailable === null ? t('settings.speech.backendStatus.checking')
                    : speechBackendAvailable ? t('settings.speech.backendStatus.available')
                    : t('settings.speech.backendStatus.notConfigured')}
                </span>
              </div>
            </SettingRow>
            {!speechBackendAvailable && speechBackendAvailable !== null && (
              <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('settings.speech.setupHint.before')}{' '}
                <a href="https://open-jarvis.github.io/OpenJarvis/user-guide/tools/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)' }}>{t('settings.speech.setupHint.linkText')}</a> {t('settings.speech.setupHint.after')}
              </div>
            )}
          </Section>

          {/* Data */}
          <Section title={t('settings.data.title')}>
            <SettingRow label={t('settings.data.conversations.label')} description={t('settings.data.conversations.description', { count: conversations.length })}>
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Download size={12} /> {t('settings.data.export')}
                </button>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Upload size={12} /> {t('settings.data.import')}
                </button>
              </div>
            </SettingRow>
            <SettingRow label={t('settings.data.clearAll.label')} description={t('settings.data.clearAll.description')}>
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                style={{
                  color: confirmClear ? 'white' : 'var(--color-error)',
                  background: confirmClear ? 'var(--color-error)' : 'transparent',
                  border: '1px solid var(--color-error)',
                }}
                onMouseEnter={(e) => { if (!confirmClear) e.currentTarget.style.background = 'rgba(220,38,38,0.1)'; }}
                onMouseLeave={(e) => { if (!confirmClear) e.currentTarget.style.background = 'transparent'; }}
              >
                <Trash2 size={12} /> {confirmClear ? t('settings.data.clearAll.confirmText') : t('settings.data.clearAll.button')}
              </button>
            </SettingRow>
          </Section>

          {/* Updates */}
          <Section title={t('settings.updates.title')}>
            <SettingRow label={t('settings.updates.autoUpdate.label')} description={t('settings.updates.autoUpdate.description')}>
              <button
                onClick={() => handleAutoUpdateToggle(!autoUpdateEnabled)}
                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                style={{ background: autoUpdateEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              >
                <span
                  className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
                  style={{
                    background: 'white',
                    transform: autoUpdateEnabled ? 'translateX(18px)' : 'translateX(2px)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label={t('settings.updates.checkNow.label')} description={t('settings.updates.checkNow.description')}>
              <button
                onClick={handleCheckNow}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text)', cursor: 'pointer' }}
                disabled={updateCheckState === 'checking'}
              >
                <RefreshCw size={12} className={updateCheckState === 'checking' ? 'animate-spin' : ''} />
                {updateCheckState === 'checking' && t('settings.updates.checkNow.checking')}
                {updateCheckState === 'available' && t('settings.updates.checkNow.available')}
                {updateCheckState === 'latest' && t('settings.updates.checkNow.latest')}
                {updateCheckState === 'idle' && t('settings.updates.checkNow.idle')}
              </button>
            </SettingRow>
          </Section>

          {/* About */}
          <Section title={t('settings.about.title')}>
            <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <p className="mb-2">
                <span className="font-semibold" style={{ color: 'var(--color-text)' }}>Close-UP</span> {'— '}{t('settings.about.tagline')}
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('settings.about.researchNote')}
              </p>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
