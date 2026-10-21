/* Public guidance chat. Conversations stay in this page's memory only. */
(() => {
  function mount() {
    if (document.getElementById('resq-chat-toggle')) return;

    const history = [];
    let busy = false;
    const root = document.createElement('div');
    root.className = 'resq-chat';

    const toggle = document.createElement('button');
    toggle.id = 'resq-chat-toggle';
    toggle.type = 'button';
    toggle.className = 'resq-chat-toggle';
    toggle.textContent = 'Ask ResQNet';
    toggle.setAttribute('aria-controls', 'resq-chat-panel');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-haspopup', 'dialog');

    const panel = document.createElement('section');
    panel.id = 'resq-chat-panel';
    panel.className = 'resq-chat-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'ResQNet AI guidance');
    panel.hidden = true;

    const header = document.createElement('header');
    header.className = 'resq-chat-header';
    const avatar = document.createElement('span');
    avatar.className = 'resq-chat-avatar';
    avatar.textContent = 'RQ';
    avatar.setAttribute('aria-hidden', 'true');
    const heading = document.createElement('div');
    heading.className = 'resq-chat-heading';
    const title = document.createElement('strong');
    title.textContent = 'ResQNet guidance';
    const subtitle = document.createElement('span');
    subtitle.textContent = 'AI assistant · general guidance';
    heading.append(title, subtitle);
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'resq-chat-close';
    close.textContent = '×';
    close.setAttribute('aria-label', 'Close guidance chat');
    header.append(avatar, heading, close);

    const notice = document.createElement('p');
    notice.className = 'resq-chat-notice';
    notice.textContent = 'AI guidance can be wrong. For immediate danger, contact local emergency services. An SOS is submitted only after the ResQNet form confirms it. Do not share passwords or private contact details here.';

    const empty = document.createElement('div');
    empty.className = 'resq-chat-empty';
    const welcome = document.createElement('p');
    welcome.textContent = 'How can I help you use ResQNet?';
    const suggestions = document.createElement('div');
    suggestions.className = 'resq-chat-suggestions';
    empty.append(welcome, suggestions);

    const log = document.createElement('div');
    log.className = 'resq-chat-log';
    log.setAttribute('role', 'log');
    log.setAttribute('aria-label', 'Chat messages');
    log.setAttribute('aria-live', 'polite');
    log.setAttribute('aria-relevant', 'additions text');

    const typing = document.createElement('div');
    typing.className = 'resq-chat-typing';
    typing.setAttribute('role', 'status');
    typing.setAttribute('aria-label', 'Generating guidance');
    typing.hidden = true;
    const typingLabel = document.createElement('span');
    typingLabel.textContent = 'ResQNet is responding';
    typing.append(typingLabel);
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement('span');
      dot.className = 'resq-chat-typing-dot';
      dot.setAttribute('aria-hidden', 'true');
      typing.append(dot);
    }

    const form = document.createElement('form');
    form.className = 'resq-chat-form';
    const label = document.createElement('label');
    label.setAttribute('for', 'resq-chat-input');
    label.textContent = 'Your question';
    const composer = document.createElement('div');
    composer.className = 'resq-chat-composer';
    const input = document.createElement('textarea');
    input.id = 'resq-chat-input';
    input.rows = 2;
    input.maxLength = 1000;
    input.required = true;
    input.placeholder = 'Ask about SOS, volunteering or reports…';
    const send = document.createElement('button');
    send.type = 'submit';
    send.textContent = 'Send';
    send.setAttribute('aria-label', 'Send question');
    composer.append(input, send);
    form.append(label, composer);

    const status = document.createElement('p');
    status.className = 'resq-chat-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    panel.append(header, notice, empty, log, typing, form, status);
    root.append(toggle, panel);
    document.body.appendChild(root);

    function scrollToLatest() {
      if (typeof log.scrollTo === 'function') {
        log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' });
      } else {
        log.scrollTop = log.scrollHeight;
      }
    }

    function addMessage(role, content) {
      const entry = document.createElement('div');
      entry.className = 'resq-chat-message resq-chat-' + role;
      const bubble = document.createElement('p');
      bubble.className = 'resq-chat-bubble';
      bubble.textContent = content;
      const time = document.createElement('time');
      time.className = 'resq-chat-time';
      const now = new Date();
      time.dateTime = now.toISOString();
      time.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      entry.append(bubble, time);
      log.appendChild(entry);
      empty.hidden = true;
      scrollToLatest();
    }

    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      if (open) input.focus(); else toggle.focus();
    }

    for (const question of [
      'How do I submit an SOS?',
      'What can volunteers do?',
      'What does Flood Intelligence show?'
    ]) {
      const choice = document.createElement('button');
      choice.type = 'button';
      choice.textContent = question;
      choice.addEventListener('click', () => {
        input.value = question;
        input.focus();
      });
      suggestions.append(choice);
    }

    toggle.addEventListener('click', () => setOpen(panel.hidden));
    close.addEventListener('click', () => setOpen(false));
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') setOpen(false);
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const message = input.value.trim();
      if (busy || !message || message.length > 1000) return;
      busy = true;
      send.disabled = true;
      input.disabled = true;
      typing.hidden = false;
      log.setAttribute('aria-busy', 'true');
      status.textContent = '';
      addMessage('user', message);
      input.value = '';
      try {
        const response = await Api.fetchWithTimeout(Api.BASE + '/api/chat', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, history: history.slice(-8) })
        });
        const data = await response.json();
        if (!response.ok || data?.success !== true || typeof data.reply !== 'string') {
          if (response.status === 429) throw new Error('busy');
          if (response.status === 503 && data?.message === 'Chat service is not configured.') throw new Error('unconfigured');
          throw new Error('unavailable');
        }
        addMessage('assistant', data.reply);
        history.push({ role: 'user', content: message },
          { role: 'assistant', content: data.reply.slice(0, 1000) });
        if (history.length > 8) history.splice(0, history.length - 8);
      } catch (error) {
        status.textContent = error.message === 'busy' ? 'Chat is busy. Please retry shortly.'
          : error.message === 'unconfigured' ? 'Chat is not configured yet.'
            : 'Chat is unavailable. Please retry. For immediate danger, contact local emergency services.';
      } finally {
        busy = false;
        typing.hidden = true;
        log.setAttribute('aria-busy', 'false');
        send.disabled = false;
        input.disabled = false;
        input.focus();
        scrollToLatest();
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
