// AI Chat Monitor - background.js
// Coordinates between content script and native Python host

const HOST_NAME = 'com.aimonitor.host';

let nativePort = null;

function connectNative() {
  try {
    nativePort = chrome.runtime.connectNative(HOST_NAME);
    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      // Retry after 5 seconds
      setTimeout(connectNative, 5000);
    });
    nativePort.onMessage.addListener((msg) => {
      console.log('Native host response:', msg);
    });
  } catch (e) {
    console.warn('Native host not available:', e);
  }
}

function sendToNative(data) {
  if (!nativePort) connectNative();
  if (nativePort) {
    nativePort.postMessage(data);
  } else {
    // Fallback: store in chrome.storage if native not available
    chrome.storage.local.get(['savedChats'], (result) => {
      const chats = result.savedChats || [];
      chats.push(data);
      // Keep last 50 sessions
      if (chats.length > 50) chats.shift();
      chrome.storage.local.set({ savedChats: chats });
    });
  }
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type === 'SAVE_CHAT') {
    sendToNative({
      action: 'save',
      platform: msg.platform,
      summary: msg.summary,
      messageCount: msg.messageCount,
      timestamp: msg.timestamp
    });

    // Update badge
    chrome.action.setBadgeText({ text: '✓', tabId: sender.tab.id });
    chrome.action.setBadgeBackgroundColor({ color: '#1D9E75' });
    setTimeout(() => {
      chrome.action.setBadgeText({ text: '', tabId: sender.tab.id });
    }, 3000);
  }

  if (msg.type === 'GET_SAVED') {
    chrome.storage.local.get(['savedChats'], (result) => {
      chrome.runtime.sendMessage({
        type: 'SAVED_DATA',
        chats: result.savedChats || []
      });
    });
  }
});

// Connect on startup
connectNative();
