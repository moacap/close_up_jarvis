import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from '../locales/en.json';
import pt from '../locales/pt.json';
import es from '../locales/es.json';

export type Language = 'en' | 'pt' | 'es';
export const LANGUAGES: Language[] = ['en', 'pt', 'es'];

const SETTINGS_KEY = 'openjarvis-settings';

function isLanguage(value: unknown): value is Language {
  return value === 'en' || value === 'pt' || value === 'es';
}

function detectInitialLanguage(): Language {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (isLanguage(parsed.language)) return parsed.language;
    }
  } catch {
    // fall through to browser detection
  }
  const browserLang = navigator.language.slice(0, 2).toLowerCase();
  if (browserLang === 'pt' || browserLang === 'es') return browserLang;
  return 'en';
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    pt: { translation: pt },
    es: { translation: es },
  },
  lng: detectInitialLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  returnEmptyString: false,
});

export default i18n;
