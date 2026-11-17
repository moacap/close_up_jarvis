import { useState, useEffect } from 'react';
import type React from 'react';
import { useTranslation } from 'react-i18next';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Settings {
  apiUrl: string;
  refreshInterval: number; // seconds
  theme: 'dark' | 'light';
}

const DEFAULT_SETTINGS: Settings = {
  apiUrl: 'http://localhost:8000',
  refreshInterval: 5,
  theme: 'dark',
};

const STORAGE_KEY = 'openjarvis-settings';

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    }
  } catch {
    // ignore corrupt data
  }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(settings: Settings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#1e1e2e',
    color: '#cdd6f4',
    padding: 24,
    maxWidth: 600,
  },
  heading: {
    fontSize: 20,
    fontWeight: 600,
    marginBottom: 24,
    color: '#89b4fa',
  },
  fieldGroup: {
    marginBottom: 20,
  },
  label: {
    display: 'block',
    fontSize: 13,
    fontWeight: 500,
    color: '#a6adc8',
    marginBottom: 6,
  },
  input: {
    width: '100%',
    padding: '8px 12px',
    borderRadius: 6,
    border: '1px solid #313244',
    backgroundColor: '#181825',
    color: '#cdd6f4',
    fontSize: 14,
    outline: 'none',
    boxSizing: 'border-box' as const,
  },
  select: {
    padding: '8px 12px',
    borderRadius: 6,
    border: '1px solid #313244',
    backgroundColor: '#181825',
    color: '#cdd6f4',
    fontSize: 14,
    outline: 'none',
    cursor: 'pointer',
  },
  toggleRow: {
    display: 'flex',
    gap: 8,
  },
  toggleButton: {
    padding: '8px 16px',
    borderRadius: 6,
    border: '1px solid #313244',
    backgroundColor: 'transparent',
    color: '#a6adc8',
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: 500,
    transition: 'all 0.15s ease',
  },
  toggleActive: {
    backgroundColor: '#313244',
    color: '#cdd6f4',
    borderColor: '#89b4fa',
  },
  savedNotice: {
    marginTop: 16,
    padding: '8px 12px',
    borderRadius: 6,
    backgroundColor: '#1e3a2f',
    color: '#a6e3a1',
    fontSize: 13,
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SettingsPanelProps {
  onSettingsChange?: (settings: Settings) => void;
}

export function SettingsPanel({ onSettingsChange }: SettingsPanelProps) {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    saveSettings(settings);
    onSettingsChange?.(settings);
    setSaved(true);
    const timer = setTimeout(() => setSaved(false), 2000);
    return () => clearTimeout(timer);
  }, [settings, onSettingsChange]);

  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>{t('desktop.settingsPanel.title')}</h2>

      <div style={styles.fieldGroup}>
        <label style={styles.label}>{t('desktop.settingsPanel.apiUrlLabel')}</label>
        <input
          style={styles.input}
          type="text"
          value={settings.apiUrl}
          onChange={(e) =>
            setSettings((s) => ({ ...s, apiUrl: e.target.value }))
          }
          placeholder="http://localhost:8000"
        />
      </div>

      <div style={styles.fieldGroup}>
        <label style={styles.label}>{t('desktop.settingsPanel.refreshIntervalLabel')}</label>
        <select
          style={styles.select}
          value={settings.refreshInterval}
          onChange={(e) =>
            setSettings((s) => ({
              ...s,
              refreshInterval: Number(e.target.value),
            }))
          }
        >
          <option value={1}>{t('desktop.settingsPanel.secondsOption', { count: 1 })}</option>
          <option value={2}>{t('desktop.settingsPanel.secondsOption', { count: 2 })}</option>
          <option value={5}>{t('desktop.settingsPanel.secondsOption', { count: 5 })}</option>
          <option value={10}>{t('desktop.settingsPanel.secondsOption', { count: 10 })}</option>
          <option value={30}>{t('desktop.settingsPanel.secondsOption', { count: 30 })}</option>
          <option value={60}>{t('desktop.settingsPanel.secondsOption', { count: 60 })}</option>
        </select>
      </div>

      <div style={styles.fieldGroup}>
        <label style={styles.label}>{t('desktop.settingsPanel.themeLabel')}</label>
        <div style={styles.toggleRow}>
          <button
            type="button"
            style={{
              ...styles.toggleButton,
              ...(settings.theme === 'dark' ? styles.toggleActive : {}),
            }}
            onClick={() => setSettings((s) => ({ ...s, theme: 'dark' }))}
          >
            {t('desktop.settingsPanel.themeDark')}
          </button>
          <button
            type="button"
            style={{
              ...styles.toggleButton,
              ...(settings.theme === 'light' ? styles.toggleActive : {}),
            }}
            onClick={() => setSettings((s) => ({ ...s, theme: 'light' }))}
          >
            {t('desktop.settingsPanel.themeLight')}
          </button>
        </div>
      </div>

      {saved && <div style={styles.savedNotice}>{t('desktop.settingsPanel.savedNotice')}</div>}
    </div>
  );
}

export type { Settings };
