import { Volume2, Square } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTts } from '../../hooks/useTts';
import { useAppStore } from '../../lib/store';

interface Props {
  messageId: string;
  content: string;
}

/** Reads one assistant message aloud through the server's TTS backend. */
export function SpeakMessageButton({ messageId, content }: Props) {
  const { t } = useTranslation();
  const voiceOutputEnabled = useAppStore((s) => s.settings.voiceOutputEnabled);
  const { speak, stop, speakingId, available, state, error, errorId } = useTts();

  if (!voiceOutputEnabled || !available) return null;

  // Playback is global, so this button reflects the shared utterance only when
  // that utterance is this message.
  const isMine = speakingId === messageId;
  const busy = isMine && (state === 'loading' || state === 'speaking');
  const messageError = errorId === messageId ? error : null;

  return (
    <>
      <button
        onClick={() => (busy ? stop() : speak(messageId, content))}
        className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        style={{
          color: busy ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
          opacity: busy ? 1 : undefined,
        }}
        title={
          messageError ||
          (isMine && state === 'loading'
            ? t('chat.speakMessageButton.synthesizing')
            : isMine && state === 'speaking'
              ? t('chat.speakMessageButton.stop')
              : t('chat.speakMessageButton.readAloud'))
        }
        aria-label={busy ? t('chat.speakMessageButton.stopReadingAriaLabel') : t('chat.speakMessageButton.readAloudAriaLabel')}
      >
        {busy ? <Square size={14} /> : <Volume2 size={14} />}
      </button>
      {messageError && (
        <span role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>
          {messageError}
        </span>
      )}
    </>
  );
}
