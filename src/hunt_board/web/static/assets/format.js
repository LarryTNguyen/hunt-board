const absoluteFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

export function absoluteDate(value, fallback = 'Not recorded') {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? fallback : absoluteFormatter.format(date);
}

export function relativeDate(value, fallback = 'Unknown') {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return fallback;
  const seconds = Math.round((date.valueOf() - Date.now()) / 1000);
  const ranges = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
  const [unit, divisor] = ranges.find(([, size]) => Math.abs(seconds) >= size) || ['second', 1];
  return relativeFormatter.format(Math.round(seconds / divisor), unit);
}

export function score(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : 0;
}

export function durationMs(value) {
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return '0m 0s';
  const totalSeconds = Math.round(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

export function truncate(value, length = 170) {
  const text = String(value || '').trim().replace(/\s+/g, ' ');
  return text.length > length ? `${text.slice(0, length - 1).trim()}…` : text;
}

export function plainText(value) {
  const text = String(value || '');
  if (!/<\/?[a-z][\s\S]*>/i.test(text)) return text;
  const documentFragment = new DOMParser().parseFromString(text, 'text/html');
  return documentFragment.body.textContent?.replace(/\s+/g, ' ').trim() || '';
}

export function descriptionText(descriptionHtml, descriptionTextValue) {
  const html = String(descriptionHtml || '').trim();
  const fallback = String(descriptionTextValue || '').trim();
  let source = html || fallback;
  if (!source) return '';

  for (let pass = 0; pass < 3; pass += 1) {
    const documentFragment = new DOMParser().parseFromString(source, 'text/html');
    documentFragment.body.querySelectorAll('br').forEach((breakElement) => breakElement.replaceWith('\n'));
    documentFragment.body.querySelectorAll('li').forEach((item) => {
      item.prepend('\u2022 ');
      item.append('\n');
    });
    documentFragment.body.querySelectorAll('p, div, section, article, header, h1, h2, h3, h4, h5, h6, ul, ol, blockquote').forEach((block) => block.append('\n\n'));

    const text = (documentFragment.body.textContent || '').trim();
    if (!/<\/?(?:a|blockquote|br|div|em|h[1-6]|li|ol|p|section|span|strong|ul)\b[^>]*>/i.test(text)) {
      return text
        .replace(/\u00a0/g, ' ')
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n[ \t]+/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    }
    source = text;
  }
  return source.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || fallback;
}

export function safeUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function label(value, fallback = 'Not specified') {
  if (!value) return fallback;
  return String(value).replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function initials(value) {
  return String(value || '?').split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
}

export function companyMark(companyName, logoUrl) {
  const logo = safeUrl(logoUrl);
  return `<span class="company-logo"><span class="company-initials">${escapeHtml(initials(companyName))}</span>${logo ? `<img src="${escapeHtml(logo)}" alt="" data-company-logo>` : ''}</span>`;
}

export function activateCompanyLogos(root = document) {
  root.querySelectorAll('[data-company-logo]').forEach((image) => {
    const useFallback = () => image.remove();
    image.addEventListener('error', useFallback, { once: true });
    requestAnimationFrame(() => {
      if (image.isConnected && image.complete && image.naturalWidth === 0) useFallback();
    });
  });
}

export function salary(job, fallback = 'Not disclosed') {
  const minimum = job?.salary_min == null || job.salary_min === '' ? NaN : Number(job.salary_min);
  const maximum = job?.salary_max == null || job.salary_max === '' ? NaN : Number(job.salary_max);
  const hasMinimum = Number.isFinite(minimum);
  const hasMaximum = Number.isFinite(maximum);
  if (!hasMinimum && !hasMaximum) return fallback;
  const currency = String(job?.salary_currency || 'USD').toUpperCase();
  const format = (value) => {
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(value);
    } catch {
      return `${currency} ${Math.round(value).toLocaleString()}`;
    }
  };
  const amount = hasMinimum && hasMaximum
    ? (minimum === maximum ? format(minimum) : `${format(minimum)} – ${format(maximum)}`)
    : hasMinimum ? `From ${format(minimum)}` : `Up to ${format(maximum)}`;
  return `${amount}${job?.salary_interval ? ` / ${label(job.salary_interval)}` : ''}`;
}

export function country(job, fallback = 'Country not resolved') {
  return job?.location_country || job?.location_country_code || fallback;
}

export function locationWithCountry(job, fallback = 'Location not listed') {
  const location = String(job?.location || '').trim();
  const countryName = country(job, '');
  if (!location) return countryName || fallback;
  if (!countryName || location.toLowerCase().includes(countryName.toLowerCase())) return location;
  return `${location} · ${countryName}`;
}

export function roleLevel(title) {
  const normalized = String(title || '').toLowerCase();
  const levels = [
    ['Principal', /\bprincipal\b/], ['Staff', /\bstaff\b/], ['Senior', /\b(senior|sr\.?)\b/],
    ['Lead', /\blead\b/], ['Manager', /\bmanager\b/], ['Director', /\bdirector\b/],
    ['Intern', /\bintern(ship)?\b/], ['Entry level', /\b(entry|junior|jr\.?|new grad|associate)\b/],
  ];
  return levels.find(([, pattern]) => pattern.test(normalized))?.[0] || 'Level not stated';
}

export function humanRankingReason(reason) {
  const value = String(reason || '').trim();
  const freshness = value.match(/freshness age_days=(\d+)/i);
  if (freshness) {
    const days = Number(freshness[1]);
    return days === 0 ? 'Posted today' : `Posted ${days} day${days === 1 ? '' : 's'} ago`;
  }
  const mappings = [
    [/^exact include title match:\s*/i, 'Exact title phrase: '],
    [/^role group title match:\s*/i, 'Flexible role group: '],
    [/^excluded by title keyword:\s*/i, 'Excluded title phrase: '],
    [/^source priority\s*(?::)?\s*/i, 'Source priority: '],
  ];
  for (const [pattern, replacement] of mappings) {
    if (pattern.test(value)) return value.replace(pattern, replacement).replace(/_/g, ' ');
  }
  const labels = {
    'senior-or-lead title': 'Senior or leadership level detected',
    'preferred early-career level': 'Preferred early-career level',
    'mid-level compatible title': 'Compatible mid-level title',
    'level unspecified': 'No level stated in the title',
    'preferred location/work type': 'Preferred location or work arrangement',
    'location/work type not preferred': 'Outside preferred location or work arrangement',
    'no include keyword or role group matched title': 'No preferred title phrase or role group matched',
  };
  return labels[value.toLowerCase()] || value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function rankingSignals(job) {
  const reasons = job.ranking_reasons || [];
  const exact = reasons.find((reason) => /^exact include/i.test(reason));
  const group = reasons.find((reason) => /^role group/i.test(reason));
  const titleValue = exact ? 'Exact phrase match' : group ? 'Flexible role match' : score(job.ranking_score) > 0 ? 'Partial title match' : 'No title match';
  const keywordValue = (exact || group)?.split(':').slice(1).join(':').trim().replace(/_/g, ' ') || 'No matched phrase recorded';
  const freshAt = job.posted_at || job.first_seen_at;
  return [
    { label: 'Title', value: titleValue },
    { label: 'Freshness', value: relativeDate(freshAt) },
    { label: 'Keywords', value: keywordValue },
  ];
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character]);
}
