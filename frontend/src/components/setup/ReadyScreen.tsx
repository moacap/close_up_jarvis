import { Sparkles, MessageSquare, ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { SOURCE_CATALOG } from '../../types/connectors';

// ---------------------------------------------------------------------------
// Starter queries
// ---------------------------------------------------------------------------

function getStarterQueries(connectedSources: string[], t: TFunction): string[] {
  const queries: string[] = [];
  const has = (id: string) => connectedSources.includes(id);

  if (has('gmail') || has('gmail_imap')) {
    queries.push(t('setup.readyScreen.starters.emails'));
  }
  if (has('gcalendar')) {
    queries.push(t('setup.readyScreen.starters.calendar'));
  }
  if (has('slack')) {
    queries.push(t('setup.readyScreen.starters.slack'));
  }
  if (has('gdrive') || has('notion') || has('obsidian')) {
    queries.push(t('setup.readyScreen.starters.notes'));
  }
  if (has('imessage')) {
    queries.push(t('setup.readyScreen.starters.texting'));
  }
  if (has('gcontacts')) {
    queries.push(t('setup.readyScreen.starters.collaborators'));
  }
  if (has('granola')) {
    queries.push(t('setup.readyScreen.starters.meetingNotes'));
  }

  // Fallback defaults
  if (queries.length === 0) {
    return [
      t('setup.readyScreen.starters.fallback.focus'),
      t('setup.readyScreen.starters.fallback.summarize'),
      t('setup.readyScreen.starters.fallback.draft'),
    ];
  }

  return queries.slice(0, 3);
}

// ---------------------------------------------------------------------------
// StarterCard
// ---------------------------------------------------------------------------

function StarterCard({
  query,
  onSelect,
}: {
  query: string;
  onSelect: (q: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(query)}
      className="flex items-center justify-between gap-3 w-full px-4 py-3 rounded-xl text-left transition-all group"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-3">
        <MessageSquare size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
        <span className="text-sm" style={{ color: 'var(--color-text)' }}>
          {query}
        </span>
      </div>
      <ArrowRight
        size={14}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ color: 'var(--color-text-tertiary)' }}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// ReadyScreen
// ---------------------------------------------------------------------------

export function ReadyScreen({
  connectedSources,
  onStart,
}: {
  connectedSources: string[];
  onStart: (query?: string) => void;
}) {
  const { t } = useTranslation();
  const starters = getStarterQueries(connectedSources, t);

  const connectedCards = connectedSources
    .map((id) => SOURCE_CATALOG.find((c) => c.connector_id === id))
    .filter(Boolean);

  return (
    <div className="flex flex-col items-center text-center h-full justify-center gap-6">
      {/* Icon */}
      <div
        className="w-20 h-20 rounded-2xl flex items-center justify-center"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <Sparkles size={36} />
      </div>

      {/* Headline */}
      <div>
        <h2 className="text-2xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          {t('setup.readyScreen.title')}
        </h2>
        <p className="text-sm max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {connectedCards.length > 0
            ? t('setup.readyScreen.connectedSummary', {
                count: connectedCards.length,
                sources: connectedCards.map((c) => c!.display_name).join(', '),
              })
            : t('setup.readyScreen.readyDefault')}
          {' '}{t('setup.readyScreen.askAnything')}
        </p>
      </div>

      {/* Starter queries */}
      <div className="w-full max-w-sm flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider mb-1 text-left"
          style={{ color: 'var(--color-text-tertiary)' }}>
          {t('setup.readyScreen.tryAsking')}
        </p>
        {starters.map((q) => (
          <StarterCard key={q} query={q} onSelect={onStart} />
        ))}
      </div>

      {/* Open Chat button */}
      <button
        onClick={() => onStart()}
        className="px-8 py-3 rounded-xl font-semibold text-sm transition-all"
        style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
      >
        {t('setup.readyScreen.openChat')}
      </button>
    </div>
  );
}
