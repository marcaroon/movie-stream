'use strict';

const view = document.getElementById('view');
const overlayRoot = document.getElementById('overlay-root');
const desktop = () => window.pywebview && window.pywebview.api; // present only in the app window
const FINISHED = ['Completed', 'Failed', 'Cancelled'];

// ------------------------------------------------------------
// DOM helpers
// ------------------------------------------------------------

/** Build an element. Text is always set as text, never parsed as HTML. */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') el.style.cssText = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Replace an element's content, skipping empty parts (replaceChildren would print "null"). */
function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter(child => child !== null && child !== undefined && child !== false));
}

// SF Symbols–style line icons (static markup, never built from data).
const ICONS = {
  play: '<path d="M7.5 4.8v14.4a.8.8 0 0 0 1.2.7l11.3-7.2a.8.8 0 0 0 0-1.4L8.7 4.1a.8.8 0 0 0-1.2.7z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  download: '<path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19.5h14"/>',
  bell: '<path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
  bellFill: '<path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15z" fill="currentColor"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/>',
  left: '<path d="M15 5l-7 7 7 7"/>',
  right: '<path d="M9 5l7 7-7 7"/>',
  down: '<path d="M5.5 9l6.5 6.5L18.5 9"/>',
  more: '<circle cx="5.5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.6" fill="currentColor" stroke="none"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  back10: '<path d="M4.5 12a7.5 7.5 0 1 0 2.3-5.4"/><path d="M4.5 4.5v3.8h3.8"/><text x="12.4" y="15.2" font-size="6.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Inter, sans-serif">10</text>',
  fwd10: '<path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.5 4.5v3.8h-3.8"/><text x="11.6" y="15.2" font-size="6.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Inter, sans-serif">10</text>',
  captions: '<rect x="3" y="5.5" width="18" height="13" rx="3"/><path d="M10.5 10.2a2.2 2.2 0 1 0 0 3.6M17 10.2a2.2 2.2 0 1 0 0 3.6"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  collapse: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  volume: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  mute: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
  next: '<path d="M5.5 5.5v13l9-6.5z" fill="currentColor"/><path d="M18 5.5v13"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l1 12.2h9L17.5 7"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  power: '<path d="M12 3.5V12"/><path d="M6.7 7.2a7.5 7.5 0 1 0 10.6 0"/>',
  refresh: '<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M19 4.5v4h-4"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  sliders: '<path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9"/><circle cx="15" cy="7.5" r="2.2"/><circle cx="9" cy="16.5" r="2.2"/>',
  pip: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><rect x="12" y="11.5" width="6.5" height="5" rx="1.2" fill="currentColor" stroke="none"/>',
  episodes: '<rect x="3.5" y="5" width="6.5" height="5" rx="1.2"/><rect x="3.5" y="14" width="6.5" height="5" rx="1.2"/><path d="M13.5 6.5h7M13.5 9h4.5M13.5 15.5h7M13.5 18h4.5"/>',
  stats: '<path d="M5 19.5v-7M10 19.5v-15M15 19.5v-9M20 19.5v-12"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14.5h8"/>',
};

function icon(name, className) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.9');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  if (className) svg.setAttribute('class', className);
  svg.innerHTML = ICONS[name];
  return svg;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

const imageUrl = (path, size) => (path ? `/img/${size}${path}` : null);

/** Artwork that fades in once loaded, over a titled placeholder. */
function artImage(path, size, fallbackText) {
  const parts = [h('div', {class: 'fallback', text: fallbackText || ''})];
  if (path) {
    const img = h('img', {src: imageUrl(path, size), alt: '', loading: 'lazy', decoding: 'async'});
    const shown = () => img.classList.add('loaded');
    img.addEventListener('load', shown);
    img.addEventListener('error', () => img.remove());
    if (img.complete && img.naturalWidth) shown();
    parts.push(img);
  }
  return parts;
}

function clock(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(seconds / 3600);
  const mm = String(Math.floor((seconds % 3600) / 60)).padStart(hours ? 2 : 1, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Apple-style short durations: "54m", "1h 3m". */
function shortDuration(seconds) {
  const total = Math.max(1, Math.round((seconds || 0) / 60));
  return total >= 60 ? `${Math.floor(total / 60)}h${total % 60 ? ` ${total % 60}m` : ''}` : `${total}m`;
}

function bytes(count) {
  if (!count) return '0 MB';
  const gb = count / 2 ** 30;
  return gb >= 1 ? `${gb.toFixed(gb >= 10 ? 0 : 1)} GB` : `${Math.max(1, Math.round(count / 2 ** 20))} MB`;
}

function shortDate(iso) {
  if (!iso) return '';
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return isNaN(date) ? '' : date.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
}

const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
const episodeCode = (season, number) => (season ? `S${season}, E${number}` : '');
const watchHref = url => `#/watch?url=${encodeURIComponent(url)}`;
const titleHref = (kind, slug, season) => `#/title/${kind}/${slug}${season ? `?season=${season}` : ''}`;
const loading = text => h('div', {class: 'loading'}, h('div', {class: 'spinner'}), text || '');

function storageGet(key, fallback) {
  try { const value = localStorage.getItem(key); return value === null ? fallback : JSON.parse(value); } catch { return fallback; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

// ------------------------------------------------------------
// Toast, dialogs and menus
// ------------------------------------------------------------

let toastTimer;
function toast(text, actionLabel, action) {
  document.querySelector('.toast')?.remove();
  const box = h('div', {class: 'toast glass dark', role: 'status'}, h('span', {text}),
    actionLabel ? h('button', {text: actionLabel, onclick: () => { box.remove(); action(); }}) : null);
  overlayRoot.append(box);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.remove(), actionLabel ? 7000 : 3500);
}

/** A glass alert. Resolves true/false, or the typed text when `input` is given (null if cancelled). */
function dialog({title, message, confirm = 'OK', cancel = 'Cancel', destructive = false, input}) {
  return new Promise(resolve => {
    const field = input !== undefined ? h('input', {class: 'field', value: input, spellcheck: 'false'}) : null;
    const finish = result => { scrim.remove(); document.removeEventListener('keydown', onKey); resolve(result); };
    const ok = () => finish(field ? field.value.trim() || null : true);
    const no = () => finish(field ? null : false);
    const onKey = event => {
      if (event.key === 'Escape') no();
      if (event.key === 'Enter' && (field || document.activeElement !== cancelButton)) ok();
    };
    const cancelButton = h('button', {class: 'btn btn-glass glass', onclick: no}, cancel);
    const confirmButton = h('button', {class: `btn ${destructive ? 'btn-glass glass btn-destructive' : 'btn-primary'}`, onclick: ok}, confirm);
    const scrim = h('div', {class: 'scrim', onclick: event => { if (event.target === scrim) no(); }},
      h('div', {class: 'dialog glass dark', role: 'dialog', 'aria-modal': 'true'},
        h('h2', {class: 'title-3', text: title}),
        message ? h('p', {text: message}) : null,
        field,
        h('div', {class: 'btn-row'}, cancelButton, confirmButton)));
    overlayRoot.append(scrim);
    document.addEventListener('keydown', onKey);
    (field || confirmButton).focus();
  });
}

let closeOpenMenu = null;
/** A glass pop-up menu under (or above) `anchor`. Items: {label, icon, action, disabled, checked, destructive} or '-'. */
function openMenu(anchor, items) {
  if (closeOpenMenu) closeOpenMenu();
  const menu = h('div', {class: 'menu glass dark', role: 'menu'}, items.map(item => (item === '-' ? h('hr') :
    h('button', {role: 'menuitem', disabled: item.disabled, class: item.destructive ? 'btn-destructive' : '',
      onclick: () => { close(); item.action && item.action(); }},
    item.icon ? icon(item.icon) : null, item.label, item.checked ? icon('check', 'check') : null))));
  overlayRoot.append(menu);
  const box = anchor.getBoundingClientRect();
  const width = menu.offsetWidth, height = menu.offsetHeight;
  menu.style.left = `${Math.max(12, Math.min(box.right - width, innerWidth - width - 12))}px`;
  menu.style.top = `${box.bottom + 8 + height > innerHeight ? box.top - height - 8 : box.bottom + 8}px`;
  const outside = event => { if (!menu.contains(event.target) && !anchor.contains(event.target)) close(); };
  const onKey = event => { if (event.key === 'Escape') close(); };
  // Only a page scroll closes it: a click can nudge a snapping shelf by a pixel.
  const onScroll = event => { if (event.target === document) close(); };
  function close() {
    menu.remove();
    document.removeEventListener('pointerdown', outside, true);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('scroll', onScroll, true);
    closeOpenMenu = null;
  }
  setTimeout(() => {
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('scroll', onScroll, true);
  });
  document.addEventListener('keydown', onKey);
  closeOpenMenu = close;
  menu.querySelector('button:not(:disabled)')?.focus();
}

// ------------------------------------------------------------
// Lockups (cards) and shelves
// ------------------------------------------------------------

/** A portrait poster with its caption inside the artwork, and an optional chart rank. */
function posterTile(item, rank) {
  const kind = item.type === 'movie' ? 'movie' : 'series';
  return h('a', {class: 'tile poster', href: titleHref(kind, item.slug), 'aria-label': item.title, title: item.title},
    h('div', {class: 'art'}, artImage(item.poster_path, 'w342', item.title),
      h('div', {class: 'shade'}),
      rank ? h('div', {class: 'rank', text: rank}) : null,
      h('div', {class: 'poster-caption', text: [kind === 'series' ? 'TV Show' : 'Movie', item.year].filter(Boolean).join(' · ')})));
}

/**
 * A 16:9 card with its text over the artwork. `foot` holds the bottom row (duration, progress,
 * buttons); `actions` are interactive and sit above the card's own link.
 */
function lockup({href, image, size = 'w780', fallback, eyebrow, title, sub, foot, badges, className = '', label}) {
  const link = href ? h('a', {class: 'tile-link', href, 'aria-label': label || title, style: 'position:absolute;inset:0;z-index:3;border-radius:inherit'}) : null;
  // The card already prints its title, so the placeholder behind the artwork stays blank.
  return h('div', {class: `tile wide ${className}`},
    h('div', {class: 'art'}, artImage(image, size, fallback || ''),
      image ? h('div', {class: 'material', style: `background-image:url('${imageUrl(image, size)}')`}) : null,
      h('div', {class: 'shade'}),
      badges || null, link,
      h('div', {class: 'lockup-text', style: 'pointer-events:none'},
        eyebrow ? h('div', {class: 'eyebrow', text: eyebrow}) : null,
        h('div', {class: 'lockup-title', text: title}),
        sub ? h('div', {class: 'lockup-sub clamp-2', text: sub}) : null,
        foot ? h('div', {class: 'lockup-foot', style: 'pointer-events:auto'}, foot) : null)));
}

function miniProgress(position, duration) {
  if (!position || !duration) return null;
  return h('div', {class: 'mini-progress'}, h('span', {style: `width:${Math.min(100, (position / duration) * 100)}%`}));
}

function playFoot(text, position, duration) {
  return [h('span', {style: 'display:inline-flex;align-items:center;gap:5px'}, icon('play'), text), miniProgress(position, duration)];
}

/** A just-released episode listed in the catalog. */
function catalogEpisodeTile(item) {
  return lockup({href: titleHref('series', item.slug, item.season), image: item.still_path, size: 'w500',
    eyebrow: `Season ${item.season}, Episode ${item.number}`, title: item.title.replace(/ S\d+E\d+$/, ''),
    sub: item.episode_name});
}

/** Something watched or saved: Up Next, Watch Later or a download. */
function libraryTile(item) {
  const href = item.url ? watchHref(item.url) : `#/watch?media=${item.media_id ?? item.id}`;
  const left = item.duration && item.position ? `${shortDuration(item.duration - item.position)} left` : 'Play';
  const downloaded = item.media_id || item.file_path;
  return lockup({href, image: item.still_path || item.backdrop_path, size: item.still_path ? 'w500' : 'w780',
    eyebrow: item.season ? `Season ${item.season}, Episode ${item.number}` : (item.kind === 'movie' ? 'Movie' : null),
    title: item.title || item.display_title, sub: item.episode_name,
    foot: playFoot(left, item.position, item.duration),
    badges: downloaded ? h('span', {class: 'badge glass'}, icon('check'), 'Downloaded') : null});
}

function newEpisodeTile(item) {
  return lockup({href: watchHref(item.url), image: item.still_path || item.backdrop_path, size: item.still_path ? 'w500' : 'w780',
    eyebrow: `New · Season ${item.season}, Episode ${item.number}`, title: item.title, sub: item.episode_name,
    foot: playFoot('Play'),
    badges: [h('span', {class: 'badge new', text: 'NEW'}),
      item.media_id ? h('span', {class: 'badge glass right'}, icon('check'), 'Downloaded') : null]});
}

/** A horizontally paged row. Exactly N cards fit the width (CSS), and the arrows page by one screen. */
function shelf(title, tiles, kind, link) {
  if (!tiles.length) return null;
  const track = h('div', {class: `shelf-track ${kind}`}, tiles);
  const page = direction => {
    const style = getComputedStyle(track);
    const width = track.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) + parseFloat(style.columnGap);
    track.scrollBy({left: direction * width, behavior: 'smooth'});
  };
  const prev = h('button', {class: 'shelf-arrow prev', 'aria-label': 'Previous', onclick: () => page(-1)}, icon('left'));
  const next = h('button', {class: 'shelf-arrow next', 'aria-label': 'Next', onclick: () => page(1)}, icon('right'));
  const update = () => {
    prev.disabled = track.scrollLeft < 4;
    next.disabled = track.scrollLeft + track.clientWidth >= track.scrollWidth - 4;
  };
  track.addEventListener('scroll', update, {passive: true});
  new ResizeObserver(update).observe(track);
  const heading = link
    ? h('a', {class: 'title-2 title-link', href: link}, title, icon('right'))
    : h('h2', {class: 'title-2', text: title});
  return h('section', {class: 'shelf'}, h('div', {class: 'shelf-head'}, heading),
    h('div', {class: 'shelf-body'}, prev, track, next));
}

function emptyState(title, text) {
  return h('div', {class: 'empty'}, h('div', {class: 'title-3', text: title}), h('div', {text}));
}

function skeletonShelves(count = 3) {
  return Array.from({length: count}, () => h('section', {class: 'shelf'},
    h('div', {class: 'shelf-head'}, h('div', {class: 'skeleton', style: 'width:180px;height:22px'})),
    h('div', {class: 'shelf-track posters'}, Array.from({length: 8}, () => h('div', {class: 'skeleton', style: 'aspect-ratio:2/3'})))));
}

// ------------------------------------------------------------
// Router
// ------------------------------------------------------------

let renderToken = 0;
let cleanups = [];
const onLeave = fn => cleanups.push(fn);
const current = token => token === renderToken; // false once the user navigated elsewhere

const routes = [
  [/^#?\/?$/, renderHome, 'home'],
  [/^#\/search(?:\?(.*))?$/, renderSearch, null],
  [/^#\/title\/(movie|series)\/([\w-]+)(?:\?(.*))?$/, renderTitle, null],
  [/^#\/library(?:\?(.*))?$/, renderLibrary, 'library'],
  [/^#\/downloads$/, renderDownloads, 'downloads'],
  [/^#\/watch\?(.*)$/, renderPlayer, null],
];

async function route() {
  if (closeOpenMenu) closeOpenMenu();
  cleanups.forEach(fn => { try { fn(); } catch (error) { console.error(error); } });
  cleanups = [];
  const token = ++renderToken;
  const hash = location.hash || '#/';
  for (const [pattern, render, nav] of routes) {
    const match = hash.match(pattern);
    if (!match) continue;
    document.querySelectorAll('[data-nav]').forEach(link => link.classList.toggle('active', link.dataset.nav === nav));
    window.scrollTo(0, 0);
    try {
      await render(match, token);
    } catch (error) {
      if (current(token)) view.replaceChildren(h('div', {class: 'page'}, emptyState('Something Went Wrong', error.message)));
    }
    return;
  }
  location.hash = '#/';
}

window.addEventListener('hashchange', route);
const navSearch = document.getElementById('nav-search');
navSearch.addEventListener('submit', event => {
  event.preventDefault();
  const input = navSearch.querySelector('input');
  const text = input.value.trim();
  location.hash = text ? `#/search?q=${encodeURIComponent(text)}` : '#/search';
  input.blur();
});

// ------------------------------------------------------------
// Hero (Home carousel and title pages)
// ------------------------------------------------------------

function heroTitle(item, href) {
  const title = h('h1', {class: 'large-title hero-title', text: item.title, hidden: Boolean(item.logo_path)});
  const parts = [title];
  if (item.logo_path) {
    const logo = h('img', {class: 'hero-logo', src: imageUrl(item.logo_path, 'w500'), alt: item.title});
    logo.addEventListener('error', () => { logo.remove(); title.hidden = false; });
    parts.unshift(logo);
  }
  return href ? h('a', {href, 'aria-label': `${item.title} details`}, parts) : parts;
}

function heroArt(path) {
  return h('div', {class: 'hero-art', style: path ? `background-image:url('${imageUrl(path, 'w1280')}')` : ''});
}

function genreLine(parts) {
  return h('div', {class: 'genre-line'}, parts.filter(Boolean).flatMap((part, i) =>
    [i ? h('span', {class: 'sep'}) : null, typeof part === 'string' ? h('span', {text: part}) : part]));
}

/** An overview clamped to two lines, with Apple's small MORE button when it is longer. */
function expandableText(text) {
  const body = h('p', {class: 'overview clamp-2', text});
  const more = h('button', {class: 'more', text: 'MORE', hidden: true, onclick: () => {
    body.classList.toggle('clamp-2');
    more.textContent = body.classList.contains('clamp-2') ? 'MORE' : 'LESS';
  }});
  requestAnimationFrame(() => { more.hidden = body.scrollHeight <= body.clientHeight + 2; });
  return [body, more];
}

const circleButton = (iconName, label, onclick) =>
  h('button', {class: 'btn btn-icon btn-glass glass', 'aria-label': label, title: label, onclick}, icon(iconName));

function carousel(items) {
  const slides = items.filter(item => item.backdrop_path && item.type !== 'episode').slice(0, 7);
  if (!slides.length) return null;
  const body = h('div', {class: 'hero-body'});
  const dots = h('div', {class: 'hero-dots glass'});
  const section = h('section', {class: 'hero'}, body, dots);
  let index = -1, timer = null;

  function show(next) {
    index = (next + slides.length) % slides.length;
    const item = slides[index];
    const kind = item.type === 'movie' ? 'movie' : 'series';
    const details = titleHref(kind, item.slug);
    const art = heroArt(item.backdrop_path);
    section.prepend(art);
    section.querySelectorAll('.hero-art').forEach(old => {
      if (old !== art) { old.classList.add('leaving'); setTimeout(() => old.remove(), 900); }
    });
    fill(body,
      h('div', {class: 'pill glass', text: kind === 'series' ? 'Featured Series' : 'Featured Film'}),
      heroTitle(item, details),
      genreLine([kind === 'series' ? 'TV Show' : 'Movie', item.year]),
      item.overview ? h('p', {class: 'overview clamp-2', text: item.overview}) : null,
      h('div', {class: 'btn-row'},
        kind === 'movie'
          ? h('a', {class: 'btn btn-primary', href: watchHref(item.url)}, icon('play'), 'Play')
          : h('a', {class: 'btn btn-primary', href: details}, icon('play'), 'Watch Now'),
        kind === 'movie'
          ? circleButton('plus', 'Add to Watch Later', () => api('/api/watch-later', {url: item.url, add: true})
            .then(() => toast('Added to Watch Later')).catch(error => toast(error.message)))
          : circleButton('bell', 'Follow', () => api(`/api/follow/${item.slug}`, {follow: true})
            .then(() => toast('Following · new episodes appear in Library')).catch(error => toast(error.message))),
        h('a', {class: 'btn btn-icon btn-glass glass', href: details, 'aria-label': 'Details', title: 'Details'}, icon('info'))));
    body.style.animation = 'none';
    void body.offsetWidth; // restart the entrance animation
    body.style.animation = '';
    [...dots.children].forEach((dot, i) => dot.classList.toggle('active', i === index));
  }

  const restart = () => { clearInterval(timer); timer = setInterval(() => show(index + 1), 9000); };
  slides.forEach((_, i) => dots.append(h('button', {'aria-label': `Show item ${i + 1}`, onclick: () => { show(i); restart(); }})));
  section.addEventListener('mouseenter', () => clearInterval(timer));
  section.addEventListener('mouseleave', restart);
  onLeave(() => clearInterval(timer));
  show(0);
  restart();
  return section;
}

// ------------------------------------------------------------
// Home
// ------------------------------------------------------------

async function renderHome(match, token) {
  view.replaceChildren(h('div', {class: 'hero skeleton', style: 'border-radius:0'}), ...skeletonShelves());
  const data = await api('/api/home');
  if (!current(token)) return;
  const featured = data.rows.find(r => r.title === 'Featured') || data.rows[0];
  const parts = [
    featured ? carousel(featured.items) : null,
    data.error ? h('div', {class: 'notice', text: `The catalog couldn’t be loaded (${data.error}). Your downloads still play.`}) : null,
    shelf('Up Next', data.continue.map(libraryTile), 'wide', '#/library'),
    shelf('New Episodes', data.new_episodes.map(newEpisodeTile), 'wide', '#/library'),
    shelf('Watch Later', data.watch_later.map(libraryTile), 'wide', '#/library?tab=watch-later'),
    shelf('Downloaded', data.downloaded.map(libraryTile), 'wide', '#/library?tab=storage'),
  ];
  for (const row of data.rows) {
    if (row === featured) continue;
    if (row.items.every(item => item.type === 'episode')) {
      parts.push(shelf(row.title, row.items.map(catalogEpisodeTile), 'wide'));
    } else {
      // Charts get Apple TV's big rank numerals.
      const ranked = /trending|top/i.test(row.title);
      const posters = row.items.filter(item => item.type !== 'episode');
      parts.push(shelf(ranked ? `Top 10: ${row.title}` : row.title,
        (ranked ? posters.slice(0, 10) : posters).map((item, i) => posterTile(item, ranked ? i + 1 : null)), 'posters'));
    }
  }
  view.replaceChildren(...parts.filter(Boolean));
}

// ------------------------------------------------------------
// Search
// ------------------------------------------------------------

async function renderSearch(match, token) {
  const query = new URLSearchParams(match[1] || '').get('q') || '';
  navSearch.querySelector('input').value = query;
  const input = h('input', {type: 'search', value: query, placeholder: 'Movies and TV Shows', 'aria-label': 'Search', autocomplete: 'off'});
  const form = h('form', {class: 'search-big', role: 'search'}, icon('search'), input);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const text = input.value.trim();
    if (text) location.hash = `#/search?q=${encodeURIComponent(text)}`;
  });
  const results = h('div');
  view.replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'page-head'}, h('h1', {class: 'large-title', text: 'Search'})), form, results));
  onLeave(() => { navSearch.querySelector('input').value = ''; });
  if (!query) input.focus();

  if (!query) {
    const recent = storageGet('martube.recentSearches', []);
    if (recent.length) {
      results.append(h('div', {class: 'chips'},
        h('span', {class: 'footnote', text: 'Recent', style: 'margin-right:4px'}),
        recent.map(text => h('a', {class: 'chip', href: `#/search?q=${encodeURIComponent(text)}`}, text)),
        h('button', {class: 'btn btn-plain', onclick: () => { storageSet('martube.recentSearches', []); route(); }}, 'Clear')));
    }
    const holder = h('div', {}, loading());
    results.append(holder);
    const home = await api('/api/home').catch(() => ({rows: []}));
    if (!current(token)) return;
    const popular = home.rows.find(row => /trending/i.test(row.title) && row.items.some(i => i.type !== 'episode'));
    holder.replaceChildren(...(popular ? [h('h2', {class: 'title-2', text: 'Popular Right Now', style: 'margin:36px 0 18px'}),
      h('div', {class: 'grid'}, popular.items.filter(i => i.type !== 'episode').map(item => posterTile(item)))] : []));
    return;
  }

  storageSet('martube.recentSearches', [query, ...storageGet('martube.recentSearches', []).filter(q => q !== query)].slice(0, 8));
  const status = h('p', {class: 'footnote', style: 'margin:18px 0 20px'});
  const grid = h('div', {class: 'grid'});
  const sentinel = h('div', {style: 'height:1px'});
  results.append(status, grid, sentinel);
  let page = 0, shown = 0, total = 0, busy = false, done = false;

  async function load() {
    if (busy || done) return;
    busy = true;
    if (!page) status.textContent = 'Searching…';
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(query)}&page=${page + 1}`);
      if (!current(token)) return;
      page += 1;
      total = data.total;
      shown += data.results.length;
      grid.append(...data.results.map(item => posterTile(item)));
      done = !data.results.length || shown >= total;
      status.textContent = shown ? `${plural(total, 'result')} for “${query}”` : '';
      if (!shown) results.replaceChildren(h('div', {style: 'margin-top:28px'},
        emptyState('No Results', `Nothing matched “${query}”. Check the spelling or try another title.`)));
    } catch (error) {
      if (current(token)) status.textContent = `Search failed: ${error.message}`;
    } finally {
      busy = false;
    }
  }

  const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) load(); }, {rootMargin: '600px'});
  observer.observe(sentinel);
  onLeave(() => observer.disconnect());
  await load();
}

// ------------------------------------------------------------
// Title page (movie or series)
// ------------------------------------------------------------

function playLabel(state, code) {
  const resume = state && state.position > 30 && !state.finished;
  return `${resume ? 'Resume' : 'Play'}${code ? ` ${code}` : ''}`;
}

/** Download status for a movie or episode: a ring while downloading, a check once saved. */
function downloadState(state, tiny) {
  if (state && state.media_id) {
    return h('span', {class: tiny ? 'icon-tiny ok' : 'btn btn-icon btn-glass glass on', title: 'Downloaded', role: 'img', 'aria-label': 'Downloaded'}, icon('check'));
  }
  if (state && state.job) {
    const pct = Math.round((state.job.fraction || 0) * 100);
    const ring = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    ring.setAttribute('viewBox', '0 0 36 36');
    ring.innerHTML = `<circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,.22)" stroke-width="3.5"/>
      <circle cx="18" cy="18" r="15" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-dasharray="${(pct / 100) * 94.2} 94.2"/>`;
    return h('a', {class: tiny ? 'ring' : 'btn btn-icon btn-glass glass', href: '#/downloads', title: `${state.job.status} ${pct}%`, 'aria-label': `Downloading ${pct}%`},
      tiny ? ring : h('span', {class: 'ring'}, ring));
  }
  return null;
}

async function queueDownload(item) {
  await api('/api/downloads', {items: [{url: item.url, title: item.title}]});
  toast('Added to Downloads', 'View', () => { location.hash = '#/downloads'; });
}

async function setWatchLater(url, add) {
  await api('/api/watch-later', {url, add});
  toast(add ? 'Added to Watch Later' : 'Removed from Watch Later');
}

async function renderTitle(match, token) {
  const [, kind, slug, query] = match;
  const wantedSeason = Number(new URLSearchParams(query || '').get('season')) || null;
  view.replaceChildren(h('div', {class: 'hero skeleton title-hero', style: 'border-radius:0'}));
  const title = await api(`/api/title/${kind}/${slug}`);
  if (!current(token)) return;

  const rating = Number(title.rating);
  const seasons = title.seasons || [];
  const actions = h('div', {class: 'btn-row'});
  view.replaceChildren(h('section', {class: 'hero title-hero'}, heroArt(title.backdrop_path),
    h('div', {class: 'hero-body'},
      kind === 'series' && seasons.length ? h('div', {class: 'pill glass', text: plural(seasons.length, 'Season')}) : null,
      heroTitle(title),
      genreLine([kind === 'series' ? 'TV Show' : 'Movie', ...(title.genres || []).slice(0, 2),
        rating ? h('span', {class: 'tag', text: `★ ${rating.toFixed(1)}`}) : null]),
      title.overview ? h('div', {class: 'overview-wrap'}, expandableText(title.overview)) : null,
      h('div', {class: 'tech-line'}, [title.year, title.runtime ? shortDuration(title.runtime * 60) : null,
        kind === 'series' && seasons.length ? plural(seasons.reduce((n, [, c]) => n + c, 0), 'Episode') : null]
        .filter(Boolean).map((text, i) => [i ? h('span', {text: '·'}) : null, h('span', {text})])),
      actions)));

  if (kind === 'movie') {
    let timer;
    const draw = state => {
      const status = downloadState(state);
      fill(actions,
        title.has_video ? h('a', {class: 'btn btn-primary', href: watchHref(title.url)}, icon('play'), playLabel(state))
          : h('button', {class: 'btn btn-glass glass', disabled: true}, 'Coming Soon'),
        title.has_video ? (status || circleButton('download', 'Download', async () => { await queueDownload(title); refresh(); })) : null,
        title.has_video ? circleButton(state && state.watch_later ? 'check' : 'plus',
          state && state.watch_later ? 'Remove from Watch Later' : 'Add to Watch Later',
          async () => { await setWatchLater(title.url, !(state && state.watch_later)); refresh(); }) : null);
      clearInterval(timer);
      if (state && state.job) timer = setInterval(refresh, 2000);
    };
    const refresh = async () => {
      const latest = await api(`/api/title/movie/${slug}`).catch(() => null);
      if (latest && current(token)) draw(latest.state);
    };
    onLeave(() => clearInterval(timer));
    draw(title.state);
    view.append(aboutSection(title, kind));
    return;
  }

  // Series: follow, season menu, episode shelf, About.
  let following = title.following;
  const autoSwitch = h('input', {type: 'checkbox', class: 'switch', checked: title.auto_download, 'aria-label': 'Download new episodes automatically'});
  autoSwitch.addEventListener('change', () => api(`/api/follow/${slug}/auto`, {auto: autoSwitch.checked})
    .then(() => toast(autoSwitch.checked ? 'New episodes will download automatically' : 'Automatic downloads off'))
    .catch(error => toast(error.message)));
  const autoRow = h('label', {class: 'inline-switch', hidden: !following}, 'Auto-download new episodes', autoSwitch);
  const followButton = h('button', {class: 'btn btn-icon btn-glass glass'});
  const drawFollow = () => {
    followButton.replaceChildren(icon(following ? 'bellFill' : 'bell'));
    followButton.classList.toggle('on', following);
    followButton.title = following ? 'Following' : 'Follow';
    followButton.setAttribute('aria-label', followButton.title);
    autoRow.hidden = !following;
  };
  followButton.addEventListener('click', async () => {
    try {
      await api(`/api/follow/${slug}`, {follow: !following});
      following = !following;
      drawFollow();
      toast(following ? 'Following · new episodes appear in Library' : 'Unfollowed');
    } catch (error) { toast(error.message); }
  });
  drawFollow();

  const seasonButton = h('button', {class: 'season-button', 'aria-haspopup': 'menu'});
  const downloadSeason = h('button', {class: 'btn btn-glass glass small'}, icon('download'), 'Download Season');
  const episodesHolder = h('div', {}, h('div', {class: 'shelf-track wide'}, Array.from({length: 4}, () => h('div', {class: 'skeleton', style: 'aspect-ratio:16/9'}))));
  view.append(
    h('div', {class: 'section-head'}, seasonButton, h('span', {class: 'spacer'}), autoRow, downloadSeason),
    episodesHolder, aboutSection(title, kind));
  actions.replaceChildren(h('span'), followButton);
  if (!seasons.length) {
    seasonButton.textContent = 'Episodes';
    episodesHolder.replaceChildren(h('div', {class: 'section'}, emptyState('No Episodes Yet', 'This show has no seasons available.')));
    downloadSeason.hidden = true;
    return;
  }

  let selected = seasons.some(([n]) => n === wantedSeason) ? wantedSeason : title.default;
  let episodes = [], timer = null, scrollKept = 0;
  onLeave(() => clearInterval(timer));
  seasonButton.addEventListener('click', () => openMenu(seasonButton, seasons.map(([n, count]) => ({
    label: `Season ${n} · ${plural(count, 'episode')}`, checked: n === selected, action: () => loadSeason(n),
  }))));
  downloadSeason.addEventListener('click', async () => {
    const wanted = episodes.filter(e => e.has_video && !e.state.media_id && !e.state.job);
    if (!wanted.length) return toast('Every available episode is already downloaded or downloading');
    const ok = await dialog({title: `Download ${plural(wanted.length, 'Episode')}?`,
      message: `Season ${selected} will be saved for offline viewing.`, confirm: 'Download'});
    if (!ok) return;
    const result = await api('/api/downloads', {items: wanted.map(e => ({url: e.url, title: e.title}))});
    toast(`${plural(result.added, 'episode')} added to Downloads`, 'View', () => { location.hash = '#/downloads'; });
    loadSeason(selected, true);
  });

  async function loadSeason(number, quiet) {
    if (number !== selected) scrollKept = 0;
    selected = number;
    seasonButton.replaceChildren(`Season ${number}`, icon('down'));
    const data = await api(`/api/season/${slug}/${number}`);
    if (!current(token) || selected !== number) return;
    episodes = data.episodes;
    const oldTrack = episodesHolder.querySelector('.shelf-track');
    if (quiet && oldTrack) scrollKept = oldTrack.scrollLeft;
    const refresh = () => loadSeason(number, true);
    const row = shelf('', episodes.map(e => episodeCard(e, refresh)), 'wide');
    if (row) {
      row.querySelector('.shelf-head').remove();
      row.style.marginTop = '4px';
      episodesHolder.replaceChildren(row);
      row.querySelector('.shelf-track').scrollLeft = scrollKept;
    } else {
      episodesHolder.replaceChildren(h('div', {class: 'section'}, emptyState('No Episodes Yet', 'Check back soon.')));
    }
    const next = episodes.find(e => e.state.position > 30 && !e.state.finished)
      || episodes.find(e => e.has_video && !e.state.finished) || episodes.find(e => e.has_video);
    actions.firstChild.replaceWith(next
      ? h('a', {class: 'btn btn-primary', href: watchHref(next.url)}, icon('play'), playLabel(next.state, `S${number}, E${next.number}`))
      : h('span'));
    clearInterval(timer);
    if (episodes.some(e => e.state.job)) timer = setInterval(refresh, 2000);
  }
  await loadSeason(selected);
}

function episodeCard(episode, refresh) {
  const state = episode.state || {};
  const playable = episode.has_video || state.media_id;
  const duration = state.duration || (episode.runtime ? episode.runtime * 60 : 0);
  const timeText = state.position > 30 && !state.finished && duration ? `${shortDuration(duration - state.position)} left`
    : episode.runtime ? `${episode.runtime}m` : 'Play';
  const moreButton = h('button', {class: 'icon-tiny', 'aria-label': 'More', title: 'More'}, icon('more'));
  moreButton.addEventListener('click', event => {
    event.preventDefault();
    openMenu(moreButton, [
      {label: 'Play', icon: 'play', disabled: !playable, action: () => { location.hash = watchHref(episode.url); }},
      state.media_id ? {label: 'Downloaded', icon: 'check', disabled: true}
        : state.job ? {label: 'Downloading…', icon: 'download', action: () => { location.hash = '#/downloads'; }}
          : {label: 'Download Episode', icon: 'download', disabled: !episode.has_video,
            action: () => queueDownload(episode).then(refresh).catch(error => toast(error.message))},
      {label: state.watch_later ? 'Remove from Watch Later' : 'Add to Watch Later', icon: state.watch_later ? 'check' : 'plus',
        disabled: !episode.has_video, action: () => setWatchLater(episode.url, !state.watch_later).then(refresh).catch(error => toast(error.message))},
    ]);
  });
  return lockup({
    href: playable ? watchHref(episode.url) : null, image: episode.still_path, size: 'w500',
    className: `episode${playable ? '' : ' unavailable'}`, label: `Play episode ${episode.number}, ${episode.name}`,
    eyebrow: playable ? `Episode ${episode.number}` : `Episode ${episode.number} · Coming ${shortDate(episode.air_date) || 'soon'}`,
    title: episode.name, sub: episode.overview,
    foot: [
      h('span', {style: 'display:inline-flex;align-items:center;gap:5px'}, playable ? icon('play') : null, state.finished ? 'Watched' : timeText),
      state.finished ? null : miniProgress(state.position, state.duration),
      h('span', {class: 'grow'}),
      downloadState(state, true),
      moreButton,
    ],
  });
}

function aboutSection(title, kind) {
  const genres = (title.genres || []).join(', ');
  const info = [
    ['Released', title.year],
    ['Genre', genres],
    ['Rating', Number(title.rating) ? `${Number(title.rating).toFixed(1)} / 10` : null],
    kind === 'movie' ? ['Runtime', title.runtime ? shortDuration(title.runtime * 60) : null]
      : ['Seasons', title.seasons && title.seasons.length ? plural(title.seasons.length, 'season') : null],
  ].filter(([, value]) => value);
  return h('section', {class: 'section', style: 'margin-top:40px'},
    h('h2', {class: 'title-2', text: 'About', style: 'margin-bottom:16px'}),
    h('div', {class: 'about'}, h('div', {class: 'about-card'},
      h('div', {class: 'title-3', text: title.title}),
      genres ? h('div', {class: 'eyebrow', text: (title.genres || []).slice(0, 2).join(' · ')}) : null,
      title.tagline ? h('div', {class: 'headline', text: title.tagline, style: 'margin-bottom:6px'}) : null,
      h('p', {class: 'footnote', style: 'margin:0', text: title.overview || 'No description available.'}))),
    info.length ? h('div', {}, h('h2', {class: 'title-3', text: 'Information', style: 'margin-top:32px'}),
      h('dl', {class: 'info-grid', style: 'margin-top:14px'}, info.map(([label, value]) =>
        h('div', {}, h('dt', {text: label}), h('dd', {text: value}))))) : null);
}

// ------------------------------------------------------------
// Library: Up Next, Watch Later, Following, Storage
// ------------------------------------------------------------

const LIBRARY_TABS = [['up-next', 'Up Next'], ['watch-later', 'Watch Later'], ['following', 'Following'], ['storage', 'Storage']];

async function renderLibrary(match, token) {
  const tab = new URLSearchParams(match[1] || '').get('tab') || 'up-next';
  const tabs = h('div', {class: 'segmented', role: 'tablist'}, LIBRARY_TABS.map(([id, label]) =>
    h('button', {role: 'tab', class: id === tab ? 'active' : '', 'aria-selected': String(id === tab),
      onclick: () => { location.hash = `#/library?tab=${id}`; }}, label)));
  const body = h('div', {}, loading());
  view.replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'page-head'}, h('h1', {class: 'large-title', text: 'Library'}), tabs), body));
  const data = await api('/api/library');
  if (!current(token)) return;
  const sections = {'up-next': upNextTab, 'watch-later': watchLaterTab, following: followingTab, storage: storageTab};
  body.replaceChildren(...(await sections[tab](data, token)).filter(Boolean));
}

async function upNextTab(data) {
  const home = await api('/api/home').catch(() => ({continue: []}));
  const parts = [];
  if (data.new_episodes.length) {
    parts.push(h('div', {class: 'page-head', style: 'margin:0 0 16px'}, h('h2', {class: 'title-2', text: 'New Episodes'}),
      h('button', {class: 'btn btn-plain', onclick: async () => {
        await api('/api/new-episodes/seen', {});
        updateBadges();
        route();
      }}, 'Mark All as Seen')),
    h('div', {class: 'grid wide', style: 'margin-bottom:40px'}, data.new_episodes.map(newEpisodeTile)));
  }
  parts.push(h('h2', {class: 'title-2', text: 'Continue Watching', style: 'margin:0 0 16px'}),
    home.continue.length ? h('div', {class: 'grid wide'}, home.continue.map(libraryTile))
      : emptyState('Nothing in Progress', 'Movies and episodes you start watching appear here.'));
  return parts;
}

async function watchLaterTab(data) {
  return [data.watch_later.length ? h('div', {class: 'grid wide'}, data.watch_later.map(libraryTile))
    : emptyState('Watch Later Is Empty', 'Use + on any movie or episode to save it here. It leaves this list once you finish watching.')];
}

async function followingTab(data) {
  const check = h('button', {class: 'btn btn-glass glass small'}, icon('refresh'), 'Check for New Episodes');
  check.addEventListener('click', async () => {
    check.disabled = true;
    check.replaceChildren(icon('refresh'), 'Checking…');
    try {
      const result = await api('/api/follows/check', {});
      toast(result.found ? `${plural(result.found, 'new episode')} found` : 'No new episodes yet');
      updateBadges();
      if (result.found) route();
    } catch (error) { toast(error.message); }
    check.disabled = false;
    check.replaceChildren(icon('refresh'), 'Check for New Episodes');
  });
  const cards = data.follows.map(follow => {
    const auto = h('input', {type: 'checkbox', class: 'switch', checked: Boolean(follow.auto_download), 'aria-label': `Auto-download ${follow.title}`});
    auto.addEventListener('change', () => api(`/api/follow/${follow.slug}/auto`, {auto: auto.checked}));
    return h('div', {},
      h('a', {class: 'tile poster', href: titleHref('series', follow.slug), 'aria-label': follow.title},
        h('div', {class: 'art'}, artImage(follow.poster_path, 'w342', follow.title), h('div', {class: 'shade'}),
          follow.unseen ? h('span', {class: 'badge new', text: `${follow.unseen} NEW`}) : null,
          h('div', {class: 'poster-caption', text: follow.title}))),
      h('label', {class: 'inline-switch', style: 'display:flex;justify-content:space-between;margin-top:12px'}, 'Auto-download', auto));
  });
  return [
    h('div', {class: 'page-head', style: 'margin:0 0 20px'},
      h('p', {class: 'subhead', style: 'margin:0', text: 'MarTube checks the shows you follow when it starts and every few hours.'}), check),
    cards.length ? h('div', {class: 'grid'}, cards)
      : emptyState('Not Following Anything', 'Open a TV show and choose the bell to hear about new episodes.'),
  ];
}

async function storageTab(data) {
  const storage = data.storage;
  const share = storage.used + storage.free ? (storage.used / (storage.used + storage.free)) * 100 : 0;
  const autoNext = h('input', {type: 'checkbox', class: 'switch', checked: data.prefs.auto_next_download, 'aria-label': 'Download next episode'});
  autoNext.addEventListener('change', () => api('/api/prefs', {auto_next_download: autoNext.checked})
    .then(() => toast(autoNext.checked ? 'The next episode will download when you finish one' : 'Smart downloads off')));
  const deleteAfter = h('select', {class: 'select', 'aria-label': 'Remove watched downloads'},
    data.delete_choices.map(days => h('option', {value: days, text: days ? `After ${plural(days, 'day')}` : 'Never'})));
  deleteAfter.value = String(data.prefs.delete_watched_after_days);
  deleteAfter.addEventListener('change', async () => {
    const days = Number(deleteAfter.value);
    if (days && !await dialog({title: 'Remove Watched Downloads?',
      message: `Downloads you finish watching will be deleted from this computer ${plural(days, 'day')} later.`,
      confirm: 'Turn On', destructive: true})) {
      deleteAfter.value = String(data.prefs.delete_watched_after_days);
      return;
    }
    data.prefs = await api('/api/prefs', {delete_watched_after_days: days});
    toast(days ? `Watched downloads are removed after ${plural(days, 'day')}` : 'Automatic removal off');
  });

  const remove = async item => {
    if (!await dialog({title: 'Delete Download?', message: `“${item.display_title}” (${bytes(item.size_bytes)}) will be removed from this computer.`,
      confirm: 'Delete', destructive: true})) return;
    try {
      const result = await api(`/api/media/${item.id}/delete`, {});
      toast(`Deleted · ${bytes(result.freed)} freed`);
      route();
    } catch (error) { toast(error.message); }
  };
  const removeWatched = async () => {
    if (!await dialog({title: 'Delete Watched Downloads?', message: `${bytes(storage.watched)} of downloads you have finished will be removed.`,
      confirm: 'Delete', destructive: true})) return;
    const result = await api('/api/storage/delete-watched', {});
    toast(`${plural(result.deleted, 'download')} deleted · ${bytes(result.freed)} freed`);
    route();
  };

  // Downloads grouped by show or movie, biggest first.
  const groups = new Map();
  for (const item of storage.items) {
    const key = item.title || item.display_title;
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  const total = items => items.reduce((n, i) => n + (i.size_bytes || 0), 0);
  const files = [...groups.entries()].sort((a, b) => total(b[1]) - total(a[1])).map(([name, items]) =>
    h('div', {class: 'file-group'},
      h('div', {class: 'page-head', style: 'margin:0 0 4px'}, h('div', {class: 'headline', text: name}),
        h('div', {class: 'footnote', text: `${plural(items.length, 'item')} · ${bytes(total(items))}`})),
      items.sort((a, b) => (a.season || 0) - (b.season || 0) || (a.number || 0) - (b.number || 0)).map(item =>
        h('div', {class: 'file-row'},
          h('div', {class: 'name', text: item.season ? `${episodeCode(item.season, item.number)} · ${item.episode_name || ''}` : item.display_title}),
          h('div', {class: 'footnote', text: item.finished ? 'Watched' : item.position ? `${clock(item.position)} watched` : 'Not started'}),
          h('div', {class: 'footnote', text: bytes(item.size_bytes), style: 'min-width:56px;text-align:right'}),
          h('div', {class: 'row-actions'},
            h('a', {class: 'btn btn-icon small btn-glass glass', href: item.url ? watchHref(item.url) : `#/watch?media=${item.id}`, title: 'Play', 'aria-label': 'Play'}, icon('play')),
            h('button', {class: 'btn btn-icon small btn-glass glass btn-destructive', title: 'Delete', 'aria-label': 'Delete', onclick: () => remove(item)}, icon('trash')))))));

  return [
    h('div', {class: 'panel'},
      h('div', {class: 'page-head', style: 'margin:0 0 14px'}, h('h2', {class: 'title-3', text: 'Storage'}),
        h('div', {class: 'footnote', text: storage.folder, style: 'overflow-wrap:anywhere'})),
      h('div', {class: 'meter'}, h('span', {style: `width:${share}%`})),
      h('div', {class: 'meter-legend'},
        h('span', {}, h('strong', {text: bytes(storage.used)}), ' used by MarTube'),
        h('span', {}, h('strong', {text: bytes(storage.free)}), ' available'))),
    h('div', {class: 'panel'},
      h('h2', {class: 'title-3 panel-title', text: 'Smart Downloads'}),
      h('label', {class: 'list-row', style: 'cursor:pointer'},
        h('div', {}, h('div', {class: 'headline', text: 'Download Next Episode'}),
          h('div', {class: 'footnote', text: 'When you finish an episode, the next one downloads automatically.'})), autoNext),
      h('div', {class: 'list-row'},
        h('div', {}, h('div', {class: 'headline', text: 'Remove Watched Downloads'}),
          h('div', {class: 'footnote', text: 'Free up space by deleting downloads you have finished.'})), deleteAfter),
      storage.watched ? h('div', {class: 'list-row'},
        h('div', {class: 'footnote', text: `${bytes(storage.watched)} of watched downloads`}),
        h('button', {class: 'btn btn-glass glass small btn-destructive', onclick: removeWatched}, icon('trash'), 'Delete Watched')) : null),
    h('div', {class: 'panel'},
      h('h2', {class: 'title-3 panel-title', text: 'Downloaded'}),
      files.length ? files : emptyState('No Downloads', 'Movies and episodes you download appear here.')),
  ];
}

// ------------------------------------------------------------
// Downloads
// ------------------------------------------------------------

async function renderDownloads(match, token) {
  view.replaceChildren(loading());
  let data = await api('/api/downloads');
  const server = await api('/api/server').catch(() => ({can_quit: false}));
  await refreshAccount();
  if (!current(token)) return;

  const folder = h('div', {class: 'footnote', style: 'overflow-wrap:anywhere', text: data.folder});
  const parallel = h('select', {class: 'select', 'aria-label': 'Simultaneous downloads'},
    [1, 2, 3, 4, 5].map(n => h('option', {value: n, text: String(n)})));
  parallel.value = String(data.parallel);
  parallel.addEventListener('change', () => api('/api/settings', {parallel: Number(parallel.value)}));
  const changeFolder = async () => {
    try {
      let result;
      if (desktop()) result = await api('/api/folder/choose', {});
      else {
        const typed = await dialog({title: 'Download Location', message: 'Enter the full path of the folder for new downloads.',
          input: folder.textContent, confirm: 'Save'});
        if (!typed) return;
        result = await api('/api/folder/set', {folder: typed});
      }
      folder.textContent = result.folder;
      toast('New downloads will be saved there');
    } catch (error) { toast(error.message); }
  };
  const stopServer = async () => {
    const active = data.jobs.filter(job => !FINISHED.includes(job.status)).length;
    const ok = await dialog({title: 'Quit MarTube?',
      message: (active ? `${plural(active, 'unfinished download')} will stop and restart next time.\n` : '')
        + 'Open MarTube again from its shortcut.', confirm: 'Quit', destructive: true});
    if (!ok) return;
    await api('/api/quit', {});
    clearInterval(timer);
    view.replaceChildren(h('div', {class: 'page'}, emptyState('MarTube Has Quit', 'Open it again from the MarTube shortcut on your Desktop or Start menu.')));
  };
  const links = h('textarea', {class: 'field', rows: 3, placeholder: 'Paste movie or episode links, one per line'});
  const addLinks = async () => {
    const items = links.value.split(/\s+/).filter(Boolean).map(url => ({url}));
    if (!items.length) return;
    const result = await api('/api/downloads', {items});
    links.value = '';
    toast(`${result.added} added${result.skipped ? ` · ${result.skipped} already in the queue` : ''}`);
    refresh();
  };
  const queue = h('div');

  view.replaceChildren(h('div', {class: 'page'},
    h('div', {class: 'page-head'}, h('h1', {class: 'large-title', text: 'Downloads'}),
      h('div', {class: 'row-actions'},
        h('button', {class: 'btn btn-glass glass small', onclick: async () => { await api('/api/downloads/clear', {}); refresh(); }}, 'Clear Finished'),
        h('a', {class: 'btn btn-glass glass small', href: '#/library?tab=storage'}, 'Manage Storage'))),
    h('div', {class: 'panel'}, queue),
    h('div', {class: 'panel'},
      h('h2', {class: 'title-3 panel-title', text: 'Add from Links'}), links,
      h('div', {class: 'btn-row', style: 'margin-top:14px'}, h('button', {class: 'btn btn-primary small', onclick: addLinks}, icon('link'), 'Add to Downloads'))),
    h('div', {class: 'panel'},
      h('h2', {class: 'title-3 panel-title', text: 'Settings'}),
      h('div', {class: 'list-row'}, h('div', {style: 'min-width:0'}, h('div', {class: 'headline', text: 'Download Location'}), folder),
        h('div', {class: 'row-actions'},
          h('button', {class: 'btn btn-glass glass small', onclick: changeFolder}, 'Change…'),
          h('button', {class: 'btn btn-glass glass small', onclick: () => api('/api/folder/open', {})}, icon('folder'), 'Show'))),
      account.available ? h('div', {class: 'list-row'}, h('div', {},
        h('div', {class: 'headline', text: 'IDLIX Account'}),
        h('div', {class: 'footnote', text: account.signed_in
          ? `Signed in as ${accountName(account.user)} · downloads in up to Full HD (1080p)`
          : 'Not signed in · downloads and streams are limited to 720p'})),
      h('button', {class: `btn small ${account.signed_in ? 'btn-glass glass' : 'btn-primary'}`,
        onclick: async () => { if (await accountSheet()) route(); }}, account.signed_in ? 'Manage' : 'Sign In')) : null,
      h('div', {class: 'list-row'}, h('div', {}, h('div', {class: 'headline', text: 'Simultaneous Downloads'}),
        h('div', {class: 'footnote', text: 'More at once can be faster, but each one gets less bandwidth.'})), parallel),
      server.can_quit ? h('div', {class: 'list-row'}, h('div', {},
        h('div', {class: 'headline', text: 'MarTube Server'}),
        h('div', {class: 'footnote', text: `Running at ${location.host}. Downloads continue when you close this tab.`})),
      h('button', {class: 'btn btn-glass glass small btn-destructive', onclick: stopServer}, icon('power'), 'Quit')) : null)));

  function draw() {
    if (!data.jobs.length) {
      queue.replaceChildren(emptyState('No Downloads', 'Download a movie or episode, or paste links below.'));
      return;
    }
    queue.replaceChildren(...data.jobs.slice().reverse().map(job => {
      const active = !FINISHED.includes(job.status);
      const indeterminate = job.status === 'Downloading' && job.fraction === null;
      return h('div', {class: 'job'},
        h('div', {class: 'job-title', text: job.title, title: job.url}),
        h('div', {class: 'row-actions'},
          h('span', {class: `status ${job.status}`, text: job.status === 'Downloading' && job.fraction ? `${Math.round(job.fraction * 100)}%` : job.status}),
          active ? h('button', {class: 'btn btn-plain', onclick: () => api(`/api/downloads/${job.id}/cancel`, {}).then(refresh)}, 'Cancel') : null,
          ['Failed', 'Cancelled'].includes(job.status)
            ? h('button', {class: 'btn btn-plain', onclick: () => api(`/api/downloads/${job.id}/retry`, {}).then(refresh)}, 'Retry') : null),
        active || job.status === 'Completed' ? h('div', {class: `bar${indeterminate ? ' indeterminate' : ''}${job.status === 'Completed' ? ' done' : ''}`},
          h('span', {style: `width:${Math.round((job.status === 'Completed' ? 1 : job.fraction || 0) * 100)}%`})) : null,
        job.detail ? h('div', {class: 'job-detail', text: job.detail}) : null);
    }));
  }

  async function refresh() {
    try {
      data = await api('/api/downloads');
      if (current(token)) draw();
    } catch { /* keep the last view; the next poll retries */ }
  }

  draw();
  const timer = setInterval(refresh, 1000);
  onLeave(() => clearInterval(timer));
}

// ------------------------------------------------------------
// Player
// ------------------------------------------------------------

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
const CAPTION_SIZES = [['s', 'S'], ['m', 'M'], ['l', 'L'], ['xl', 'XL']];
const SHORTCUTS = [
  ['Space · K', 'Play or pause'], ['← · J', 'Back 10 seconds'], ['→ · L', 'Forward 10 seconds'],
  ['Shift ← →', 'Back or forward 30 seconds'], [', .', 'Previous or next frame (paused)'],
  ['0 – 9', 'Jump to 0% – 90%'], ['↑ ↓', 'Volume up or down'], ['M', 'Mute'],
  ['< >', 'Slower or faster'], ['C', 'Subtitles on or off'], ['[ ]', 'Subtitles earlier or later'],
  ['F', 'Full screen'], ['P', 'Picture in picture'], ['N', 'Next episode'], ['E', 'Episodes'],
  ['I', 'Details'], ['S', 'Playback stats'], ['?', 'Keyboard shortcuts'], ['Esc', 'Close a panel, or leave'],
];
const clockTime = date => date.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
const speedLabel = rate => (rate === 1 ? 'Normal' : `${rate}×`);
const signedSeconds = value => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2).replace(/0$/, '')} s`;

async function renderPlayer(match, token) {
  const params = new URLSearchParams(match[1]);
  const request = params.get('media') ? {media_id: Number(params.get('media'))} : {url: params.get('url')};
  document.body.classList.add('watching');

  const video = h('video', {playsinline: true, preload: 'auto', autoplay: true});
  const back = () => (history.length > 1 ? history.back() : (location.hash = '#/'));

  // Heading: show or movie, episode, and badges for source, quality and subtitles.
  const eyebrow = h('div', {class: 'eyebrow', hidden: true});
  const titleText = h('div', {class: 't', text: 'Loading…'});
  const metaLine = h('div', {class: 'player-meta'});
  const infoButton = h('button', {class: 'btn btn-icon btn-glass glass', 'aria-label': 'Details', title: 'Details (I)', hidden: true}, icon('info'));
  const centre = h('div', {class: 'player-center'},
    h('div', {class: 'player-message glass dark'}, h('div', {class: 'spinner', style: 'margin:0 auto'}),
      h('p', {text: 'Preparing your video… streams can take about 15 seconds to start.'})));
  const osd = h('div', {class: 'player-osd glass dark', hidden: true, 'aria-live': 'polite'});

  // Transport
  const played = h('div', {class: 'played'});
  const buffered = h('div', {class: 'buffered'});
  const hoverFill = h('div', {class: 'hover-fill'});
  const knob = h('div', {class: 'knob'});
  const tip = h('div', {class: 'scrub-tip glass dark', hidden: true});
  const scrubber = h('div', {class: 'scrubber', role: 'slider', 'aria-label': 'Playback position', tabindex: '0'},
    h('div', {class: 'track'}, buffered, hoverFill, played), knob, tip);
  const timeButton = h('button', {class: 'time', title: 'Show remaining time', text: '0:00 / 0:00'});
  const endsText = h('span', {class: 'ends'});
  const playButton = h('button', {class: 'ctl main', 'aria-label': 'Play', title: 'Play (K)'}, icon('play'));
  const muteButton = h('button', {class: 'ctl', 'aria-label': 'Mute', title: 'Mute (M)'}, icon('volume'));
  const volume = h('input', {class: 'volume', type: 'range', min: 0, max: 1, step: 0.05, 'aria-label': 'Volume'});
  const nextButton = h('button', {class: 'btn btn-glass glass small', hidden: true}, icon('next'), 'Next Episode');
  const episodesButton = h('button', {class: 'ctl', 'aria-label': 'Episodes', title: 'Episodes (E)', hidden: true}, icon('episodes'));
  const captionsButton = h('button', {class: 'ctl', 'aria-label': 'Subtitles', title: 'Subtitles (C)', 'data-pop': true, hidden: true}, icon('captions'));
  const settingsButton = h('button', {class: 'ctl', 'aria-label': 'Settings', title: 'Speed, stats and shortcuts', 'data-pop': true}, icon('sliders'));
  const pipButton = h('button', {class: 'ctl pip', 'aria-label': 'Picture in picture', title: 'Picture in picture (P)',
    hidden: !document.pictureInPictureEnabled}, icon('pip'));
  const fullscreenButton = h('button', {class: 'ctl', 'aria-label': 'Full screen', title: 'Full screen (F)'}, icon('expand'));
  const controls = h('div', {class: 'controls glass dark'}, scrubber,
    h('div', {class: 'control-row'},
      playButton,
      h('button', {class: 'ctl', 'aria-label': 'Back 10 seconds', title: 'Back 10 seconds (←)', onclick: () => skip(-10)}, icon('back10')),
      h('button', {class: 'ctl', 'aria-label': 'Forward 10 seconds', title: 'Forward 10 seconds (→)', onclick: () => skip(10)}, icon('fwd10')),
      h('div', {class: 'volume-group'}, muteButton, volume),
      timeButton, h('span', {class: 'grow'}), endsText,
      nextButton, episodesButton, captionsButton, settingsButton, pipButton, fullscreenButton));

  const panel = h('aside', {class: 'player-panel glass dark', hidden: true});
  const pop = h('div', {class: 'player-pop glass dark', hidden: true});
  const statsBody = h('div');
  const stats = h('div', {class: 'player-stats glass dark', hidden: true},
    h('div', {class: 'stats-head'}, h('span', {text: 'Playback Stats'}),
      h('button', {class: 'ctl', 'aria-label': 'Close stats', title: 'Close (S)', onclick: () => toggleStats()}, icon('close'))),
    statsBody);
  const player = h('div', {class: `player cc-${storageGet('martube.captionSize', 'm')}`}, video,
    h('div', {class: 'player-top'},
      h('button', {class: 'btn btn-icon btn-glass glass', 'aria-label': 'Back', title: 'Back', onclick: back}, icon('left')),
      h('div', {class: 'player-heading'}, eyebrow, titleText, metaLine), infoButton),
    centre, osd, stats, controls, pop, panel);
  view.replaceChildren(player);

  let hls = null, info = null, saveTimer = null, idleTimer = null, nextTimer = null, osdTimer = null, clickTimer = null;
  let statsTimer = null, windowFullscreen = false, scrubbing = false, panelName = null, popBuilder = null;
  let subtitleTrack = null, subtitleDelay = 0, titlePromise = null;
  let showRemaining = storageGet('martube.remaining', false);
  const originalCues = new WeakMap();

  const duration = () => (isFinite(video.duration) ? video.duration : 0);
  const seek = seconds => { if (duration()) video.currentTime = Math.max(0, Math.min(duration() - 0.5, seconds)); };
  const togglePlay = () => (video.paused ? video.play().catch(() => {}) : video.pause());
  const togglePlayFlash = () => { togglePlay(); flash(video.paused ? 'pause' : 'play'); };
  const isEpisode = () => Boolean(info && info.details && info.details.kind === 'series' && info.details.season);
  const saveProgress = useBeacon => {
    if (!info || !duration()) return;
    const body = {url: info.url, position: video.currentTime, duration: video.duration};
    if (useBeacon) navigator.sendBeacon('/api/progress', new Blob([JSON.stringify(body)], {type: 'application/json'}));
    else api('/api/progress', body).catch(() => {});
  };

  /** A short message in the middle of the picture, e.g. "+10 s" or "Volume 80%". */
  const flash = (name, text) => {
    fill(osd, name ? icon(name) : null, text ? h('span', {text}) : null);
    osd.hidden = false;
    osd.classList.remove('fade');
    void osd.offsetWidth; // restart the pop-in animation
    clearTimeout(osdTimer);
    osdTimer = setTimeout(() => { osd.classList.add('fade'); osdTimer = setTimeout(() => { osd.hidden = true; }, 400); }, 650);
  };
  const skip = seconds => {
    seek(video.currentTime + seconds);
    flash(seconds < 0 ? 'back10' : 'fwd10', `${seconds > 0 ? '+' : '−'}${Math.abs(seconds)} s`);
  };
  const setVolume = value => {
    video.volume = Math.min(1, Math.max(0, value));
    video.muted = false;
    flash(video.volume ? 'volume' : 'mute', `${Math.round(video.volume * 100)}%`);
  };
  const toggleMute = () => { video.muted = !video.muted; flash(video.muted ? 'mute' : 'volume', video.muted ? 'Muted' : `${Math.round(video.volume * 100)}%`); };
  const setSpeed = rate => { video.playbackRate = rate; flash(null, `Speed ${speedLabel(rate)}`); drawTime(); };
  const stepSpeed = direction => {
    const index = SPEEDS.indexOf(video.playbackRate);
    const next = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, (index < 0 ? SPEEDS.indexOf(1) : index) + direction))];
    setSpeed(next);
  };
  const frameStep = direction => {
    if (!video.paused) video.pause();
    seek(video.currentTime + direction / 24);
  };

  const isFullscreen = () => windowFullscreen || Boolean(document.fullscreenElement);
  const drawFullscreen = () => fullscreenButton.replaceChildren(icon(isFullscreen() ? 'collapse' : 'expand'));
  const toggleFullscreen = () => {
    if (desktop()) {
      windowFullscreen = !windowFullscreen;
      desktop().toggle_fullscreen();
      drawFullscreen();
    } else if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {}); // the whole page, so toasts still show
  };
  const togglePip = () => {
    if (!document.pictureInPictureEnabled) return;
    (document.pictureInPictureElement ? document.exitPictureInPicture() : video.requestPictureInPicture())
      .catch(error => toast(`Picture in picture is unavailable: ${error.message}`));
  };
  const showMessage = (text, withRetry) => {
    centre.hidden = false;
    centre.replaceChildren(h('div', {class: 'player-message glass dark'},
      h('div', {class: 'title-3', text}),
      h('div', {class: 'btn-row', style: 'justify-content:center;margin-top:16px'},
        withRetry ? h('button', {class: 'btn btn-primary small', onclick: route}, 'Try Again') : null,
        h('button', {class: 'btn btn-glass glass small', onclick: back}, 'Back'))));
  };
  const showBuffering = on => {
    if (on) centre.replaceChildren(h('div', {class: 'spinner'}));
    centre.hidden = !on;
  };
  const goNext = () => { if (info && info.next) location.replace(watchHref(info.next.url)); };
  const wake = () => {
    player.classList.remove('idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (!video.paused && !scrubbing && pop.hidden && panel.hidden) player.classList.add('idle');
    }, 3000);
  };

  // ---------- Subtitles: on/off, size and timing ----------
  const setCaptions = (on, announce) => {
    if (!subtitleTrack) return;
    subtitleTrack.track.mode = on ? 'showing' : 'hidden';
    captionsButton.classList.toggle('off', !on);
    storageSet('martube.captions', on);
    if (announce) flash('captions', on ? 'Subtitles on' : 'Subtitles off');
    drawMeta();
  };
  const captionsOn = () => Boolean(subtitleTrack && subtitleTrack.track.mode === 'showing');
  const setCaptionSize = size => {
    CAPTION_SIZES.forEach(([key]) => player.classList.remove(`cc-${key}`));
    player.classList.add(`cc-${size}`);
    storageSet('martube.captionSize', size);
  };
  const applySubtitleDelay = () => {
    const cues = subtitleTrack && subtitleTrack.track.cues;
    if (!cues) return;
    for (const cue of Array.from(cues)) {
      if (!originalCues.has(cue)) originalCues.set(cue, [cue.startTime, cue.endTime]);
      const [start, end] = originalCues.get(cue);
      cue.startTime = Math.max(0, start + subtitleDelay);
      cue.endTime = Math.max(0.05, end + subtitleDelay);
    }
  };
  const shiftSubtitles = seconds => {
    if (!subtitleTrack) return;
    subtitleDelay = seconds === null ? 0 : Math.round((subtitleDelay + seconds) * 100) / 100;
    applySubtitleDelay();
    flash('captions', subtitleDelay ? `Subtitles ${signedSeconds(subtitleDelay)}` : 'Subtitle timing reset');
    refreshPop();
  };

  // ---------- Pop-over menus (settings, subtitles) inside the player, so they work in full screen ----------
  const closePop = () => { pop.hidden = true; popBuilder = null; wake(); };
  const refreshPop = () => { if (popBuilder) fill(pop, popBuilder()); };
  const openPop = (anchor, builder) => {
    if (popBuilder === builder) return closePop();
    popBuilder = builder;
    refreshPop();
    pop.hidden = false;
    const box = anchor.getBoundingClientRect(), frame = player.getBoundingClientRect();
    pop.style.right = `${Math.max(12, frame.right - box.right - 8)}px`;
    pop.style.bottom = `${frame.bottom - box.top + 14}px`;
  };
  const segmented = (options, isOn, choose) => h('div', {class: 'seg'},
    options.map(([value, label]) => h('button', {class: isOn(value) ? 'on' : '', onclick: () => { choose(value); refreshPop(); }}, label)));
  const popRow = (iconName, label, key, checked, action) => h('button', {class: 'pop-row', onclick: action},
    icon(iconName), h('span', {class: 'grow', text: label}), checked ? icon('check', 'check') : null, key ? h('kbd', {text: key}) : null);
  const settingsMenu = () => [
    h('div', {class: 'pop-title', text: 'Playback Speed'}),
    segmented(SPEEDS.map(rate => [rate, rate === 1 ? '1×' : `${rate}`]), rate => video.playbackRate === rate, setSpeed),
    h('hr'),
    popRow('stats', 'Playback stats', 'S', !stats.hidden, toggleStats),
    popRow('keyboard', 'Keyboard shortcuts', '?', false, () => { closePop(); openPanel('keys'); }),
  ];
  const captionsMenu = () => [
    h('div', {class: 'pop-title', text: 'Subtitles'}),
    segmented([[false, 'Off'], [true, 'Indonesian']], on => captionsOn() === on, on => setCaptions(on)),
    h('div', {class: 'pop-title', text: 'Text Size'}),
    segmented(CAPTION_SIZES, size => player.classList.contains(`cc-${size}`), setCaptionSize),
    h('div', {class: 'pop-title', text: 'Timing'}),
    h('div', {class: 'stepper'},
      h('button', {class: 'btn btn-glass glass small', title: 'Earlier ([)', onclick: () => shiftSubtitles(-0.25)}, '−0.25 s'),
      h('output', {text: subtitleDelay ? signedSeconds(subtitleDelay) : 'In sync'}),
      h('button', {class: 'btn btn-glass glass small', title: 'Later (])', onclick: () => shiftSubtitles(0.25)}, '+0.25 s')),
    subtitleDelay ? h('button', {class: 'btn btn-plain', onclick: () => shiftSubtitles(null)}, 'Reset timing') : null,
  ];

  // ---------- Side panel: details, episodes, shortcuts ----------
  const titleDetails = () => {
    const d = info && info.details;
    if (!d || !d.slug) return Promise.resolve(null);
    titlePromise = titlePromise || api(`/api/title/${d.kind}/${d.slug}`).catch(() => null);
    return titlePromise;
  };
  const closePanel = () => {
    panel.hidden = true;
    panelName = null;
    infoButton.classList.remove('on');
    episodesButton.classList.remove('on');
    wake();
  };
  const openPanel = name => {
    if (panelName === name) return closePanel();
    const builders = {info: infoPanel, episodes: episodesPanel, keys: keysPanel};
    if (!builders[name] || !info) return;
    closePop();
    panelName = name;
    infoButton.classList.toggle('on', name === 'info');
    episodesButton.classList.toggle('on', name === 'episodes');
    const titles = {info: 'Details', episodes: 'Episodes', keys: 'Keyboard Shortcuts'};
    fill(panel, h('div', {class: 'panel-head'}, h('h2', {class: 'title-3', text: titles[name]}),
      h('button', {class: 'ctl', 'aria-label': 'Close', title: 'Close (Esc)', onclick: closePanel}, icon('close'))),
    builders[name]());
    panel.hidden = false;
    panel.scrollTop = 0;
  };
  const infoPanel = () => {
    const d = info.details || {};
    const episode = isEpisode();
    const extra = h('div', {class: 'panel-tags'});
    titleDetails().then(title => {
      if (!title) return;
      const rating = Number(title.rating) ? `★ ${Number(title.rating).toFixed(1)}` : null;
      fill(extra, [rating, ...(title.genres || [])].filter(Boolean).map(text => h('span', {class: 'tag', text})));
      if (title.tagline && !episode) extra.after(h('p', {class: 'panel-tagline', text: title.tagline}));
    });
    const height = video.videoHeight;
    const facts = [
      ['Source', info.kind === 'local' ? 'Downloaded to this computer' : 'Streaming from IDLIX'],
      ['Video', height ? `${video.videoWidth} × ${height} (${height}p)` : null],
      ['Length', duration() ? clock(duration()) : d.runtime ? shortDuration(d.runtime * 60) : null],
      ['Subtitles', info.subtitle ? 'Indonesian' : 'None'],
      ['Aired', d.air_date ? shortDate(d.air_date) : null],
      ['File', d.file], ['Size', d.size ? bytes(d.size) : null],
      ['Downloaded', d.added_at ? shortDate(new Date(d.added_at * 1000).toISOString()) : null],
      ['Account', info.kind === 'stream' && info.tier ? `${info.tier[0].toUpperCase()}${info.tier.slice(1)} · up to ${info.max_height || '?'}p` : null],
    ].filter(([, value]) => value);
    return [
      d.art ? h('div', {class: 'art panel-art'}, artImage(d.art, 'w780', '')) : null,
      h('div', {class: 'eyebrow', text: episode ? `Season ${d.season} · Episode ${d.episode}` : 'Movie'}),
      h('h3', {class: 'title-2 panel-title', text: (episode ? d.episode_name : d.title) || info.title}),
      h('div', {class: 'subhead', text: [episode ? d.title : null, d.year].filter(Boolean).join(' · ')}),
      extra,
      d.overview ? h('p', {class: 'panel-overview', text: d.overview}) : null,
      h('dl', {class: 'facts'}, facts.map(([label, value]) => [h('dt', {text: label}), h('dd', {text: value})])),
      d.slug ? h('a', {class: 'btn btn-glass glass small', href: titleHref(d.kind, d.slug, d.season)},
        icon('info'), episode ? 'Open Series Page' : 'Open Movie Page') : null,
    ];
  };
  const episodeRow = episode => {
    const state = episode.state || {};
    const playing = episode.url === info.url;
    const playable = episode.has_video || state.media_id;
    const notes = [playing ? 'Now Playing' : null, state.finished ? 'Watched' : null, state.media_id ? 'Downloaded' : null,
      episode.runtime ? shortDuration(episode.runtime * 60) : null, playable ? null : 'Not available'].filter(Boolean);
    return h('button', {class: `ep-row${playing ? ' now' : ''}`, disabled: !playable,
      onclick: () => (playing ? closePanel() : location.replace(watchHref(episode.url)))},
    h('div', {class: 'art ep-thumb'}, artImage(episode.still_path, 'w500', `E${episode.number}`),
      playing ? h('div', {class: 'ep-playing'}, icon('play')) : null,
      miniProgress(state.finished ? 1 : state.position, state.finished ? 1 : state.duration)),
    h('div', {class: 'ep-text'},
      h('div', {class: 'ep-name', text: `${episode.number}. ${episode.name}`}),
      h('div', {class: 'footnote', text: notes.join(' · ')})));
  };
  const episodesPanel = () => {
    const d = info.details;
    const list = h('div', {class: 'ep-list'});
    const picker = h('select', {class: 'season-select', 'aria-label': 'Season', hidden: true});
    const load = async season => {
      fill(list, h('div', {class: 'panel-loading'}, h('div', {class: 'spinner'})));
      try {
        const data = await api(`/api/season/${d.slug}/${season}`);
        if (panelName !== 'episodes') return;
        fill(list, data.episodes.length ? data.episodes.map(episodeRow) : h('p', {class: 'footnote', text: 'No episodes yet.'}));
        list.querySelector('.now')?.scrollIntoView({block: 'center'});
      } catch (error) {
        fill(list, h('p', {class: 'footnote', text: `Couldn’t load the episodes. ${error.message}`}));
      }
    };
    picker.addEventListener('change', () => load(Number(picker.value)));
    titleDetails().then(title => {
      const seasons = (title && title.seasons) || [];
      if (seasons.length < 2) return;
      fill(picker, seasons.map(([number, count]) => h('option', {value: number, selected: number === d.season},
        `Season ${number}${count ? ` · ${plural(count, 'episode')}` : ''}`)));
      picker.hidden = false;
    });
    load(d.season);
    return [picker, list];
  };
  const keysPanel = () => h('dl', {class: 'keys'},
    SHORTCUTS.map(([keys, label]) => [h('dt', {}, keys.split(' ').map(key => (['·', '–'].includes(key)
      ? h('span', {class: 'or', text: key === '·' ? 'or' : 'to'}) : h('kbd', {text: key})))), h('dd', {text: label})]));

  // ---------- Playback stats ----------
  let lastFrames = null;
  const drawStats = () => {
    const quality = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
    let fps = null;
    if (quality) {
      const now = performance.now();
      if (lastFrames && now > lastFrames.at) fps = ((quality.totalVideoFrames - lastFrames.total) * 1000) / (now - lastFrames.at);
      lastFrames = {total: quality.totalVideoFrames, at: now};
    }
    const level = hls && hls.levels ? hls.levels[hls.currentLevel] : null;
    const size = info && info.details && info.details.size;
    const bitrate = level ? level.bitrate : size && duration() ? (size * 8) / duration() : 0;
    const rows = [
      ['Source', !info ? '—' : info.kind === 'local' ? 'Downloaded file' : 'HLS stream'],
      ['Resolution', video.videoWidth ? `${video.videoWidth}×${video.videoHeight}` : '—'],
      ['Frames', quality ? `${quality.totalVideoFrames} shown · ${quality.droppedVideoFrames} dropped` : '—'],
      ['Frame rate', fps !== null && !video.paused ? `${fps.toFixed(1)} fps` : '—'],
      ['Buffered', `${bufferedAhead().toFixed(1)} s ahead`],
      ['Bitrate', bitrate ? `${(bitrate / 1e6).toFixed(2)} Mbps` : '—'],
      hls ? ['Bandwidth', hls.bandwidthEstimate ? `${(hls.bandwidthEstimate / 1e6).toFixed(1)} Mbps` : '—'] : null,
      ['Speed', speedLabel(video.playbackRate)],
      ['Volume', video.muted ? 'Muted' : `${Math.round(video.volume * 100)}%`],
      ['Subtitles', !subtitleTrack ? 'None' : captionsOn() ? `On${subtitleDelay ? ` · ${signedSeconds(subtitleDelay)}` : ''}` : 'Off'],
      ['Position', `${video.currentTime.toFixed(2)} / ${duration() ? duration().toFixed(2) : '—'} s`],
    ].filter(Boolean);
    fill(statsBody, rows.map(([label, value]) => h('div', {class: 'stats-row'}, h('span', {text: label}), h('span', {text: value}))));
  };
  const toggleStats = () => {
    stats.hidden = !stats.hidden;
    clearInterval(statsTimer);
    lastFrames = null;
    if (!stats.hidden) { drawStats(); statsTimer = setInterval(drawStats, 1000); }
    refreshPop();
  };

  // ---------- Heading badges ----------
  const drawMeta = () => {
    if (!info) return;
    const d = info.details || {};
    const height = video.videoHeight || (/x(\d+)$/.exec(info.quality || '') || [])[1];
    const badges = [
      isEpisode() ? h('span', {text: `S${d.season} · E${d.episode}`}) : null,
      d.year ? h('span', {text: d.year}) : null,
      height ? h('span', {class: 'pill', text: Number(height) >= 1080 ? `HD ${height}p` : `${height}p`}) : null,
      subtitleTrack ? h('span', {class: `pill${captionsOn() ? '' : ' dim'}`, text: 'CC'}) : null,
      h('span', {class: 'source'}, icon(info.kind === 'local' ? 'download' : 'link'), info.kind === 'local' ? 'Downloaded' : 'Streaming'),
    ];
    fill(metaLine, badges);
    // Guests get 720p; when the title has more, offer the sign-in that unlocks it.
    if (info.kind === 'stream' && info.tier === 'guest' && info.best_height > (info.max_height || 0)) {
      metaLine.append(h('button', {class: 'quality-hint', onclick: async () => {
        video.pause();
        if (await accountSheet() && account.signed_in) {
          toast(`Restarting in up to ${info.best_height}p…`);
          route();
        }
      }}, `Sign in for ${info.best_height}p`));
    }
  };

  // ---------- Scrubbing: click or drag along the bar; hovering shows the time under the pointer ----------
  const fractionAt = event => {
    const box = scrubber.getBoundingClientRect();
    return Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
  };
  scrubber.addEventListener('pointerdown', event => {
    scrubbing = true;
    scrubber.setPointerCapture(event.pointerId);
    seek(fractionAt(event) * duration());
  });
  scrubber.addEventListener('pointermove', event => {
    const fraction = fractionAt(event);
    if (!duration()) return;
    const at = fraction * duration();
    tip.hidden = false;
    fill(tip, h('strong', {text: clock(at)}), h('span', {text: ` · −${clock(duration() - at)}`}));
    tip.style.left = `${Math.min(Math.max(fraction * 100, 4), 96)}%`;
    hoverFill.style.width = `${fraction * 100}%`;
    if (scrubbing) seek(at);
  });
  scrubber.addEventListener('pointerup', () => { scrubbing = false; });
  scrubber.addEventListener('pointerleave', () => { tip.hidden = true; hoverFill.style.width = '0'; });

  const bufferedAhead = () => {
    for (let i = 0; i < video.buffered.length; i++) {
      if (video.buffered.start(i) <= video.currentTime + 0.5 && video.currentTime <= video.buffered.end(i)) {
        return video.buffered.end(i) - video.currentTime;
      }
    }
    return 0;
  };
  const drawTime = () => {
    const total = duration();
    const fraction = total ? video.currentTime / total : 0;
    played.style.width = `${fraction * 100}%`;
    knob.style.left = `${fraction * 100}%`;
    scrubber.setAttribute('aria-valuenow', String(Math.round(video.currentTime)));
    scrubber.setAttribute('aria-valuetext', `${clock(video.currentTime)} of ${clock(total)}`);
    timeButton.textContent = showRemaining && total
      ? `−${clock(total - video.currentTime)}` : `${clock(video.currentTime)} / ${clock(total)}`;
    endsText.textContent = total ? `Ends at ${clockTime(new Date(Date.now() + ((total - video.currentTime) * 1000) / (video.playbackRate || 1)))}` : '';
    buffered.style.width = total ? `${((video.currentTime + bufferedAhead()) / total) * 100}%` : '0';
  };

  const onKey = event => {
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.target.matches('input, textarea, select') && event.target !== volume) return;
    const keys = {
      ' ': togglePlayFlash, k: togglePlayFlash,
      ArrowLeft: () => skip(event.shiftKey ? -30 : -10), ArrowRight: () => skip(event.shiftKey ? 30 : 10),
      j: () => skip(-10), l: () => skip(10), ',': () => frameStep(-1), '.': () => frameStep(1),
      Home: () => seek(0), End: () => seek(duration()),
      ArrowUp: () => setVolume(video.volume + 0.05), ArrowDown: () => setVolume(video.volume - 0.05),
      m: toggleMute, f: toggleFullscreen, p: togglePip, n: goNext, '<': () => stepSpeed(-1), '>': () => stepSpeed(1),
      c: () => setCaptions(!captionsOn(), true), '[': () => shiftSubtitles(-0.25), ']': () => shiftSubtitles(0.25),
      i: () => openPanel('info'), e: () => { if (!episodesButton.hidden) openPanel('episodes'); },
      s: toggleStats, '?': () => openPanel('keys'),
      Escape: () => (!pop.hidden ? closePop() : panelName ? closePanel()
        : windowFullscreen ? toggleFullscreen() : document.fullscreenElement ? null : back()),
    };
    if (/^[0-9]$/.test(event.key) && duration()) {
      event.preventDefault();
      seek((Number(event.key) / 10) * duration());
      flash(null, `${Number(event.key) * 10}%`);
      wake();
      return;
    }
    const action = keys[event.key] || keys[event.key.toLowerCase()];
    if (action) { event.preventDefault(); action(); wake(); }
  };
  // In the app window an element can only fill the window, so turn it into real full screen.
  const onFullscreenChange = () => {
    if (desktop() && document.fullscreenElement) { document.exitFullscreen(); toggleFullscreen(); }
    drawFullscreen();
  };
  // Clicks outside an open menu close it (but not the click that opened it).
  const onPointerDown = event => {
    if (!pop.hidden && !pop.contains(event.target) && !event.target.closest('[data-pop]')) closePop();
  };

  playButton.addEventListener('click', togglePlay);
  captionsButton.addEventListener('click', () => openPop(captionsButton, captionsMenu));
  settingsButton.addEventListener('click', () => openPop(settingsButton, settingsMenu));
  episodesButton.addEventListener('click', () => openPanel('episodes'));
  infoButton.addEventListener('click', () => openPanel('info'));
  muteButton.addEventListener('click', toggleMute);
  volume.addEventListener('input', () => { video.volume = Number(volume.value); video.muted = false; });
  timeButton.addEventListener('click', () => {
    showRemaining = !showRemaining;
    storageSet('martube.remaining', showRemaining);
    timeButton.title = showRemaining ? 'Show elapsed time' : 'Show remaining time';
    drawTime();
  });
  pipButton.addEventListener('click', togglePip);
  fullscreenButton.addEventListener('click', toggleFullscreen);
  nextButton.addEventListener('click', goNext);
  // A single click plays or pauses; a double click goes full screen without also pausing.
  video.addEventListener('click', () => {
    if (!pop.hidden) return closePop();
    clearTimeout(clickTimer);
    clickTimer = setTimeout(togglePlayFlash, 220);
  });
  video.addEventListener('dblclick', () => { clearTimeout(clickTimer); toggleFullscreen(); });
  video.addEventListener('play', () => { playButton.replaceChildren(icon('pause')); playButton.title = 'Pause (K)'; });
  video.addEventListener('pause', () => { playButton.replaceChildren(icon('play')); playButton.title = 'Play (K)'; saveProgress(false); wake(); });
  video.addEventListener('volumechange', () => {
    muteButton.replaceChildren(icon(video.muted || !video.volume ? 'mute' : 'volume'));
    volume.value = video.muted ? 0 : video.volume;
    volume.style.setProperty('--level', `${(video.muted ? 0 : video.volume) * 100}%`);
    storageSet('martube.volume', video.volume);
  });
  video.addEventListener('timeupdate', drawTime);
  video.addEventListener('progress', drawTime);
  video.addEventListener('durationchange', drawTime);
  video.addEventListener('ratechange', drawTime);
  video.addEventListener('waiting', () => showBuffering(true));
  video.addEventListener('playing', () => { showBuffering(false); wake(); });
  video.addEventListener('resize', drawMeta); // the picture size is known (or changed quality)
  video.volume = storageGet('martube.volume', 1);
  volume.value = video.volume;
  volume.style.setProperty('--level', `${video.volume * 100}%`);
  timeButton.title = showRemaining ? 'Show elapsed time' : 'Show remaining time';
  document.addEventListener('keydown', onKey);
  document.addEventListener('fullscreenchange', onFullscreenChange);
  player.addEventListener('pointerdown', onPointerDown, true);
  player.addEventListener('pointermove', wake);
  onLeave(() => {
    saveProgress(true);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('fullscreenchange', onFullscreenChange);
    clearInterval(saveTimer); clearTimeout(idleTimer); clearInterval(nextTimer); clearInterval(statsTimer);
    clearTimeout(osdTimer); clearTimeout(clickTimer);
    if (document.pictureInPictureElement === video) document.exitPictureInPicture().catch(() => {});
    if (hls) hls.destroy();
    video.removeAttribute('src'); video.load();
    if (windowFullscreen && desktop()) desktop().toggle_fullscreen();
    if (document.fullscreenElement) document.exitFullscreen();
    document.body.classList.remove('watching');
  });
  window.addEventListener('beforeunload', () => saveProgress(true), {once: true});

  try {
    info = await api('/api/play', request);
  } catch (error) {
    if (!current(token)) return;
    const network = /timed out|timeout|connect|resolve|curl/i.test(error.message);
    showMessage(network ? 'Can’t reach the server. Check your connection and try again.' : `This video can’t be played. ${error.message}`, true);
    return;
  }
  if (!current(token)) return;

  const d = info.details || {};
  if (isEpisode()) {
    eyebrow.textContent = d.title;
    titleText.textContent = d.episode_name || info.title;
  } else {
    eyebrow.textContent = d.slug ? 'Movie' : '';
    titleText.textContent = d.title || info.title;
  }
  eyebrow.hidden = !eyebrow.textContent;
  document.title = `${titleText.textContent} · MarTube`;
  onLeave(() => { document.title = 'MarTube'; });
  infoButton.hidden = false;
  episodesButton.hidden = !(isEpisode() && d.slug);
  if (info.next) {
    nextButton.hidden = false;
    nextButton.title = `${info.next.title} (N)`;
  }
  if (info.subtitle) {
    subtitleTrack = h('track', {kind: 'subtitles', srclang: 'id', label: 'Indonesian', src: info.subtitle, default: true});
    subtitleTrack.addEventListener('load', applySubtitleDelay);
    video.append(subtitleTrack);
    captionsButton.hidden = false;
  }
  drawMeta();

  if (info.kind === 'stream' && window.Hls && Hls.isSupported()) {
    hls = new Hls({maxBufferLength: 60});
    hls.on(Hls.Events.ERROR, (event, data) => {
      if (!data.fatal) return;
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
      else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
      else showMessage(`Playback stopped (${data.details}).`, true);
    });
    hls.on(Hls.Events.LEVEL_SWITCHED, drawMeta);
    hls.loadSource(info.src);
    hls.attachMedia(video);
  } else {
    video.src = info.src;
  }

  video.addEventListener('loadedmetadata', () => {
    // hls.js disables text tracks it does not manage; restore the viewer's choice once.
    setCaptions(storageGet('martube.captions', true));
    drawMeta();
    if (info.resume && info.resume < video.duration - 10) {
      video.currentTime = info.resume;
      toast(`Resumed from ${clock(info.resume)}`, 'Start Over', () => { video.currentTime = 0; });
    }
  }, {once: true});
  video.addEventListener('error', () => showMessage('The video couldn’t be loaded.', true));
  video.addEventListener('ended', () => {
    saveProgress(false);
    if (!info.next) return;
    let seconds = 8;
    const count = h('strong', {text: seconds});
    const card = h('div', {class: 'next-up glass dark'},
      h('div', {class: 'eyebrow', text: 'Up Next'}), h('div', {class: 'headline', text: info.next.title}),
      h('div', {class: 'footnote'}, 'Starts in ', count, ' seconds'),
      h('div', {class: 'btn-row', style: 'margin-top:12px'},
        h('button', {class: 'btn btn-primary small', onclick: goNext}, icon('play'), 'Play Now'),
        h('button', {class: 'btn btn-glass glass small', onclick: () => { clearInterval(nextTimer); card.remove(); }}, 'Cancel')));
    player.append(card);
    nextTimer = setInterval(() => {
      seconds -= 1;
      count.textContent = seconds;
      if (seconds <= 0) { clearInterval(nextTimer); goNext(); }
    }, 1000);
  });
  saveTimer = setInterval(() => { if (!video.paused) saveProgress(false); }, 5000);
  wake();
}

// ------------------------------------------------------------
// IDLIX account (member quality: Full HD)
// ------------------------------------------------------------

let account = {available: false, signed_in: false, user: null};
const accountButton = document.getElementById('nav-account');

function accountName(user) {
  return (user && (user.name || user.username)) || 'IDLIX member';
}

async function refreshAccount() {
  account = await api('/api/account').catch(() => account);
  accountButton.hidden = !account.available;
  const initial = accountButton.querySelector('.account-initial');
  accountButton.classList.toggle('signed-in', account.signed_in);
  initial.hidden = !account.signed_in;
  initial.textContent = account.signed_in ? accountName(account.user).slice(0, 1).toUpperCase() : '';
  accountButton.title = account.signed_in ? `Signed in as ${accountName(account.user)}` : 'Sign in to IDLIX for Full HD';
  return account;
}

/** The sign-in sheet, or the signed-in summary. Resolves true when the account changed. */
function accountSheet() {
  return new Promise(resolve => {
    let changed = false;
    const sheet = h('div', {class: 'dialog account-sheet glass dark', role: 'dialog', 'aria-modal': 'true'});
    const scrim = h('div', {class: 'scrim', onclick: event => { if (event.target === scrim) close(); }}, sheet);
    const onKey = event => { if (event.key === 'Escape') close(); };
    function close() { scrim.remove(); document.removeEventListener('keydown', onKey); resolve(changed); }

    function signedIn() {
      sheet.replaceChildren(
        h('h2', {class: 'title-3', text: 'IDLIX Account', style: 'margin-bottom:16px'}),
        h('div', {class: 'who'},
          h('span', {class: 'account-initial', text: accountName(account.user).slice(0, 1).toUpperCase()}),
          h('div', {}, h('div', {class: 'headline', text: accountName(account.user)}),
            account.user && account.user.username ? h('div', {class: 'footnote', text: `@${account.user.username}`}) : null)),
        h('p', {class: 'footnote', text: 'Streams and downloads use your account’s quality — up to Full HD (1080p) when IDLIX offers it.'}),
        h('div', {class: 'btn-row'},
          h('button', {class: 'btn btn-glass glass btn-destructive', onclick: async () => {
            await api('/api/account/sign-out', {});
            await refreshAccount();
            changed = true;
            toast('Signed out · videos play in 720p');
            close();
          }}, 'Sign Out'),
          h('button', {class: 'btn btn-primary', onclick: close}, 'Done')));
    }

    function signInForm() {
      const identifier = h('input', {class: 'field', name: 'username', autocomplete: 'username', placeholder: 'Email or username', spellcheck: 'false', required: true});
      const password = h('input', {class: 'field', type: 'password', name: 'password', autocomplete: 'current-password', placeholder: 'Password', required: true});
      const error = h('div', {class: 'error', role: 'alert'});
      const submit = h('button', {class: 'btn btn-primary', type: 'submit'}, 'Sign In');
      const attempt = async replaceSessions => {
        submit.disabled = true;
        error.textContent = '';
        try {
          await api('/api/account/sign-in', {identifier: identifier.value, password: password.value, replace_sessions: replaceSessions});
          password.value = '';
          await refreshAccount();
          changed = true;
          toast(`Signed in as ${accountName(account.user)} · Full HD is on`);
          close();
        } catch (failure) {
          error.textContent = failure.message;
          if (/maximum number of devices|session/i.test(failure.message) && !replaceSessions && await dialog({
            title: 'Sign Out Other Devices?', message: 'IDLIX allows a limited number of signed-in devices. Sign them out to continue here.',
            confirm: 'Sign Out Others'})) {
            return attempt(true);
          }
        } finally {
          submit.disabled = false;
        }
      };
      const form = h('form', {onsubmit: event => { event.preventDefault(); attempt(false); }}, identifier, password, error,
        h('div', {class: 'btn-row'}, h('button', {class: 'btn btn-glass glass', type: 'button', onclick: close}, 'Cancel'), submit));
      sheet.replaceChildren(
        h('h2', {class: 'title-3', text: 'Sign In to IDLIX'}),
        h('p', {text: 'Use your IDLIX account to watch and download in Full HD (1080p). Guests are limited to 720p.'}),
        form,
        h('p', {class: 'note', text: 'Your password goes straight to IDLIX and is never saved. MarTube keeps only the sign-in session, encrypted for your Windows account.'}));
      identifier.focus();
    }

    (account.signed_in ? signedIn : signInForm)();
    overlayRoot.append(scrim);
    document.addEventListener('keydown', onKey);
  });
}

accountButton.addEventListener('click', () => accountSheet());

// ------------------------------------------------------------
// Navigation badges
// ------------------------------------------------------------

async function updateBadges() {
  try {
    const status = await api('/api/status');
    for (const [id, count] of [['download-count', status.downloads_active], ['library-count', status.new_episodes]]) {
      const badge = document.getElementById(id);
      badge.hidden = !count;
      badge.textContent = count;
    }
  } catch { /* offline or quitting */ }
}

setInterval(updateBadges, 3000);
updateBadges();
refreshAccount();
route();
