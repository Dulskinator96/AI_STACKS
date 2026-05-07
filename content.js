// AI Chat Monitor - content.js
// Reads chat messages from Claude, ChatGPT, Gemini

const PLATFORMS = {
  'claude.ai': {
    user: '[data-testid="user-message"]',
    ai: '.font-claude-message, [data-testid="assistant-message"]',
    name: 'Claude'
  },
  'chatgpt.com': {
    user: '[data-message-author-role="user"]',
    ai: '[data-message-author-role="assistant"]',
    name: 'ChatGPT'
  },
  'chat.openai.com': {
    user: '[data-message-author-role="user"]',
    ai: '[data-message-author-role="assistant"]',
    name: 'ChatGPT'
  },
  'gemini.google.com': {
    user: '.user-query-text, .query-text',
    ai: '.response-content, .model-response-text',
    name: 'Gemini'
  }
};

function getPlatform() {
  const host = window.location.hostname;
  for (const key in PLATFORMS) {
    if (host.includes(key)) return { key, ...PLATFORMS[key] };
  }
  return null;
}

function extractMessages(platform) {
  const messages = [];
  const hostKey = platform.key;

  if (hostKey === 'claude.ai') {
    const nodes = document.querySelectorAll(
      '[data-testid="user-message"], [data-testid="assistant-message"]'
    );
    nodes.forEach(node => {
      const id = node.getAttribute('data-testid');
      const role = id === 'user-message' ? 'You' : platform.name;
      const text = node.innerText?.trim();
      if (text) messages.push({ role, text });
    });
    return messages;
  }

  if (hostKey === 'chatgpt.com' || hostKey === 'chat.openai.com') {
    const nodes = document.querySelectorAll(
      '[data-message-author-role="user"], [data-message-author-role="assistant"]'
    );
    nodes.forEach(node => {
      const r = node.getAttribute('data-message-author-role');
      const role = r === 'user' ? 'You' : platform.name;
      const text = node.innerText?.trim();
      if (text) messages.push({ role, text });
    });
    return messages;
  }

  if (hostKey === 'gemini.google.com') {
    const sel = `${platform.user}, ${platform.ai}`;
    const userSels = platform.user.split(',').map(s => s.trim()).filter(Boolean);
    const nodes = document.querySelectorAll(sel);
    const scored = Array.from(nodes).map(node => {
      const text = node.innerText?.trim();
      if (!text) return null;
      const isUser = userSels.some(s => {
        try { return node.matches(s); } catch { return false; }
      });
      const role = isUser ? 'You' : platform.name;
      return { role, text, y: node.getBoundingClientRect().top };
    }).filter(Boolean);
    scored.sort((a, b) => a.y - b.y);
    scored.forEach(({ role, text }) => messages.push({ role, text }));
    return messages;
  }

  return messages;
}

function buildSummary(platform, messages) {
  const date = new Date().toLocaleString();
  const url = window.location.href;
  let out = `=== AI CHAT SESSION ===\n`;
  out += `Platform : ${platform.name}\n`;
  out += `Date     : ${date}\n`;
  out += `URL      : ${url}\n`;
  out += `Messages : ${messages.length}\n`;
  out += `${'='.repeat(40)}\n\n`;

  messages.forEach((m, i) => {
    out += `[${m.role}]\n${m.text}\n\n`;
  });

  return out;
}

function clip() {
  const platform = getPlatform();
  if (!platform) return;

  const messages = extractMessages(platform);
  if (messages.length === 0) return;

  const summary = buildSummary(platform, messages);

  chrome.runtime.sendMessage({
    type: 'SAVE_CHAT',
    platform: platform.name,
    summary,
    messageCount: messages.length,
    timestamp: new Date().toISOString()
  });
}

// Clip on load and every 2 minutes automatically
clip();
setInterval(clip, 120000);

// Also clip when user scrolls to bottom (end of conversation)
window.addEventListener('scroll', () => {
  const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 100;
  if (nearBottom) clip();
});

// Listen for manual clip or context injection
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'CLIP_NOW') {
    clip();
  } else if (msg.type === 'INJECT_TEXT') {
    injectIntoChat(msg.text);
  }
});

function injectIntoChat(text) {
  const platform = getPlatform();
  if (!platform) return;

  // Find the chat input field
  // common selectors for Claude, Gemini, ChatGPT
  const selectors = [
    '[contenteditable="true"]',
    'textarea',
    '[role="textbox"]',
    '.input-area',
    '#input-field'
  ];

  let inputField = null;
  for (const s of selectors) {
    const el = document.querySelector(s);
    if (el) {
      inputField = el;
      break;
    }
  }

  if (inputField) {
    if (inputField.tagName === 'TEXTAREA' || inputField.tagName === 'INPUT') {
      inputField.value = text + "\n" + inputField.value;
    } else {
      // For contenteditable divs
      const currentText = inputField.innerText;
      inputField.innerText = text + "\n" + currentText;
    }
    
    // Focus the field
    inputField.focus();
    
    // Trigger input event to let the web app know text has changed
    const event = new Event('input', { bubbles: true });
    inputField.dispatchEvent(event);
    
    console.log('AI Monitor: Context injected into ' + platform.name);
  }
}
