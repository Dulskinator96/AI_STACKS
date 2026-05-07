// popup.js
const log = document.getElementById('log');
const statusText = document.getElementById('status-text');

function addLog(msg) {
  const line = document.createElement('div');
  line.textContent = '> ' + msg;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

document.getElementById('clip-btn').addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    chrome.tabs.sendMessage(tabs[0].id, { type: 'CLIP_NOW' });
    addLog('Clipping current chat...');
    statusText.textContent = 'Clipped and saved.';
  });
});

document.getElementById('view-btn').addEventListener('click', () => {
  chrome.storage.local.get(['savedChats'], (result) => {
    const chats = result.savedChats || [];
    addLog(`${chats.length} sessions in local storage.`);
    if (chats.length > 0) {
      const last = chats[chats.length - 1];
      addLog(`Last: ${last.platform} — ${new Date(last.timestamp).toLocaleDateString()}`);
    }
  });
});

document.getElementById('open-folder').addEventListener('click', () => {
  addLog('Open: C:\\Users\\[YOU]\\Documents\\AI_Monitor\\');
  statusText.textContent = 'Check Documents > AI_Monitor folder';
});

addLog('Extension loaded and active.');
