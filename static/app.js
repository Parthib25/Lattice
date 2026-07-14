document.addEventListener('DOMContentLoaded', () => {
  const repoSelect = document.getElementById('repo-select');
  const providerSelect = document.getElementById('provider-select');
  const modelSelect = document.getElementById('model-select');
  const featureRequest = document.getElementById('feature-request');
  const evaluationForm = document.getElementById('evaluation-form');
  const submitBtn = document.getElementById('submit-btn');

  const placeholderView = document.getElementById('placeholder-view');
  const chatMessagesContainer = document.getElementById('chat-messages-container');
  const chatHistoryList = document.getElementById('chat-history-list');
  const newChatBtn = document.getElementById('new-chat-btn');

  const liveStreamLogger = document.getElementById('live-stream-logger');
  const consoleLines = document.getElementById('console-lines');
  const consoleStatus = document.getElementById('console-status');

  const userDisplay = document.getElementById('user-display');
  const userChip = document.getElementById('user-chip');
  const logoutBtn = document.getElementById('logout-btn');
  const loginOverlay = document.getElementById('login-overlay');
  const googleSigninBtnOverlay = document.getElementById('google-signin-btn-overlay');

  const roleSelectorWrapper = document.getElementById('role-selector-wrapper');
  const roleSelect = document.getElementById('role-select');
  const adminConfigPanel = document.getElementById('admin-config-panel');
  const repoConfigForm = document.getElementById('repo-config-form');


  let idToken = localStorage.getItem('google_id_token') || null;
  let currentSessionId = null;
  let mdParser = null;

  if (typeof window.markdownit !== 'undefined') {
    mdParser = window.markdownit({ html: true });
  }

  // LLM Provider -> Model mapping
  const providerModels = {
    openai: [
      { name: "gpt-4o (Reasoning & Speed)", value: "gpt-4o" },
      { name: "gpt-4-turbo (High Quality)", value: "gpt-4-turbo" },
      { name: "gpt-3.5-turbo (Lightweight)", value: "gpt-3.5-turbo" }
    ],
    gemini: [
      { name: "gemini-3.5-flash (Recommended)", value: "gemini-3.5-flash" },
      { name: "gemini-3.1-pro-preview (Advanced Reasoning)", value: "gemini-3.1-pro-preview" },
      { name: "gemini-3.1-flash-lite (Fast & Lightweight)", value: "gemini-3.1-flash-lite" },
      { name: "gemini-3-pro-preview (Legacy Pro)", value: "gemini-3-pro-preview" },
      { name: "gemini-3-flash-preview (Legacy Flash)", value: "gemini-3-flash-preview" },
      { name: "gemini-2.0-flash (Stable)", value: "gemini-2.0-flash" }
    ],
    anthropic: [
      { name: "claude-3-5-sonnet (Recommended)", value: "claude-3-5-sonnet-20240620" },
      { name: "claude-3-opus (Complex Tasks)", value: "claude-3-opus-20240229" }
    ],
    huggingface: [
      { name: "Llama-3-8B-Instruct", value: "meta-llama/Meta-Llama-3-8B-Instruct" },
      { name: "Llama-3-70B-Instruct", value: "meta-llama/Meta-Llama-3-70B-Instruct" }
    ],
    ollama: [
      { name: "llama3 (Local)", value: "llama3" },
      { name: "mistral (Local)", value: "mistral" }
    ]
  };

  function updateModelDropdown(selectedValue = "") {
    const provider = providerSelect.value;
    const models = providerModels[provider] || [];
    modelSelect.innerHTML = models.map(m => 
      `<option value="${m.value}">${m.name}</option>`
    ).join('');
    if (selectedValue) {
      modelSelect.value = selectedValue;
    }
  }

  providerSelect.addEventListener('change', () => updateModelDropdown());

  // ─── Authentication Headers ───────────────────────────────────────────────
  function getAuthHeaders(additional = {}) {
    const headers = { ...additional };
    if (idToken) {
      headers['Authorization'] = `Bearer ${idToken}`;
    }
    return headers;
  }

  // ─── Google Auth Lifecycle ────────────────────────────────────────────────
  function handleCredentialResponse(response) {
    idToken = response.credential;
    localStorage.setItem('google_id_token', idToken);
    updateAuthState();
  }

  async function updateAuthState() {
    if (idToken) {
      loginOverlay.style.display = 'none';
      if (userChip) userChip.style.display = 'flex';
      logoutBtn.style.display = 'inline';

      // Fetch user profile to read role status
      let userRoles = ['USER'];
      let activeRole = 'USER';
      try {
        const resp = await fetch('/api/users/me', { headers: getAuthHeaders() });
        if (resp.ok) {
          const profile = await resp.json();
          userDisplay.textContent = profile.email || profile.username || 'User';
          userRoles = profile.roles || ['USER'];
          activeRole = profile.active_role || 'USER';
        } else {
          // Fallback parsing from JWT payload
          const payload = JSON.parse(atob(idToken.split('.')[1]));
          userDisplay.textContent = payload.email || 'User';
        }
      } catch (e) {
        userDisplay.textContent = 'Signed In';
      }

      // Configure role selector and admin setting panel
      if (roleSelect) {
        roleSelect.innerHTML = userRoles.map(r => 
          `<option value="${r}">${r.toUpperCase()}</option>`
        ).join('');
        roleSelect.value = activeRole;
      }
      
      if (roleSelectorWrapper) {
        // Only show selector if user has more than 1 role to toggle
        roleSelectorWrapper.style.display = (userRoles.length > 1) ? 'flex' : 'none';
      }
      toggleAdminPanelUI(activeRole);

      // Initial loads
      await loadRepositories();
      await loadChatHistory();
    } else {
      loginOverlay.style.display = 'flex'; // show login screen if not authenticated
      if (userChip) userChip.style.display = 'none';
      if (roleSelectorWrapper) roleSelectorWrapper.style.display = 'none';
      if (adminConfigPanel) adminConfigPanel.style.display = 'none';
      logoutBtn.style.display = 'none';
      userDisplay.textContent = '';
      chatHistoryList.innerHTML = '<div style="font-size:12px; color:var(--mute); text-align:center; padding:1rem;">No history</div>';
    }
  }

  function toggleAdminPanelUI(role) {
    if (adminConfigPanel) {
      adminConfigPanel.style.display = (role === 'ADMIN') ? 'block' : 'none';
    }
  }


  logoutBtn.addEventListener('click', () => {
    idToken = null;
    localStorage.removeItem('google_id_token');
    currentSessionId = null;
    if (typeof google !== 'undefined') {
      google.accounts.id.disableAutoSelect();
    }
    updateAuthState();
  });

  async function initGoogleAuth() {
    let googleClientId = '';
    try {
      const resp = await fetch('/api/config');
      if (resp.ok) {
        const cfg = await resp.json();
        googleClientId = cfg.google_client_id || '';
      }
    } catch (e) {
      console.warn('Could not fetch config:', e);
    }

    if (!googleClientId || googleClientId === 'YOUR_GOOGLE_CLIENT_ID') {
      if (googleSigninBtnOverlay) {
        googleSigninBtnOverlay.innerHTML = `
          <div style="background: rgba(255,159,10,0.08); border: 1px solid var(--warning); border-radius: var(--radius-sm); padding: 0.75rem 1rem; font-size: 12px; color: var(--warning); text-align: center; max-width: 320px; line-height: 1.6;">
            ⚠️ Google OAuth not configured.<br>
            Set <strong>GOOGLE_CLIENT_ID</strong> in <code>.env</code> file and rebuild.
          </div>`;
      }
      updateAuthState();
      return;
    }

    if (typeof google !== 'undefined') {
      google.accounts.id.initialize({
        client_id: googleClientId,
        callback: handleCredentialResponse,
        auto_select: true
      });
      if (googleSigninBtnOverlay) {
        google.accounts.id.renderButton(
          googleSigninBtnOverlay,
          { theme: "outline", size: "large", width: 280 }
        );
      }
      google.accounts.id.prompt();
    }
    updateAuthState();
  }

  window.onload = initGoogleAuth;

  // ─── Repositories dropdown ───────────────────────────────────────────────
  async function loadRepositories() {
    try {
      const response = await fetch('/api/repositories', { headers: getAuthHeaders() });
      if (!response.ok) throw new Error('Failed to load repositories');
      const repos = await response.json();
      repoSelect.innerHTML = repos.map(repo => 
        `<option value="${repo.id}">${repo.name}</option>`
      ).join('');
    } catch (err) {
      repoSelect.innerHTML = '<option value="">Failed to fetch repositories</option>';
    }
  }

  // ─── Chat History List Management ─────────────────────────────────────────
  async function loadChatHistory() {
    try {
      const response = await fetch('/api/chats', { headers: getAuthHeaders() });
      if (!response.ok) throw new Error('Failed to load chats');
      const chats = await response.json();

      if (chats.length === 0) {
        chatHistoryList.innerHTML = '<div style="font-size:12px; color:var(--mute); text-align:center; padding:1rem;">No history yet</div>';
        return;
      }

      chatHistoryList.innerHTML = chats.map(c => `
        <div class="chat-thread-item ${currentSessionId === c.id ? 'active' : ''}" data-id="${c.id}">
          <span class="chat-thread-title">${c.title}</span>
          <button class="chat-thread-delete-btn" data-id="${c.id}">[x]</button>
        </div>
      `).join('');

      // Wire up clicks
      document.querySelectorAll('.chat-thread-item').forEach(item => {
        item.addEventListener('click', (e) => {
          if (e.target.classList.contains('chat-thread-delete-btn')) return;
          const sessionId = item.getAttribute('data-id');
          selectChatSession(sessionId);
        });
      });

      // Wire up deletes
      document.querySelectorAll('.chat-thread-delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const sessionId = btn.getAttribute('data-id');
          if (confirm('Delete this evaluation run history?')) {
            await deleteChatSession(sessionId);
          }
        });
      });
    } catch (err) {
      console.error(err);
    }
  }

  async function deleteChatSession(sessionId) {
    try {
      const resp = await fetch(`/api/chats/${sessionId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      });
      if (resp.ok) {
        if (currentSessionId === sessionId) {
          resetToEmptyState();
        }
        await loadChatHistory();
      }
    } catch (err) {
      console.error(err);
    }
  }

  function resetToEmptyState() {
    currentSessionId = null;
    placeholderView.style.display = 'flex';
    chatMessagesContainer.style.display = 'none';
    chatMessagesContainer.innerHTML = '';
    featureRequest.value = '';
    featureRequest.style.height = '';
    
    // Reset active active state highlights
    document.querySelectorAll('.chat-thread-item').forEach(item => {
      item.classList.remove('active');
    });
  }

  newChatBtn.addEventListener('click', () => {
    resetToEmptyState();
  });

  async function selectChatSession(sessionId) {
    currentSessionId = sessionId;
    // Highlight list
    document.querySelectorAll('.chat-thread-item').forEach(item => {
      if (item.getAttribute('data-id') === sessionId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    try {
      const resp = await fetch(`/api/chats/${sessionId}`, { headers: getAuthHeaders() });
      if (!resp.ok) throw new Error('Failed to load chat details');
      const details = await resp.json();

      // Configure sidebar forms to match historical values
      repoSelect.value = details.repo_id;
      providerSelect.value = details.provider;
      updateModelDropdown(details.model);

      // Render messages
      renderMessages(details.messages);
    } catch (err) {
      console.error(err);
    }
  }

  function renderMessages(messages) {
    placeholderView.style.display = 'none';
    chatMessagesContainer.style.display = 'flex';
    
    if (messages.length === 0) {
      chatMessagesContainer.innerHTML = '<div style="font-size:12px; color:var(--mute); text-align:center; padding:2rem;">Empty session</div>';
      return;
    }

    let messagesHtml = messages.map(m => {
      const isUser = m.role === 'user';
      let contentHtml = '';
      
      if (isUser) {
        contentHtml = `<p>${m.content}</p>`;
      } else {
        if (mdParser) {
          contentHtml = mdParser.render(m.content);
        } else {
          contentHtml = `<pre>${m.content}</pre>`;
        }
      }

      const roleTag = isUser ? '[+] USER PROMPT' : '[x] EVALUATION REPORT';
      const bubbleClass = isUser ? 'user' : 'assistant';

      const logsDrawerHtml = (!isUser && m.live_logs) ? `
        <div class="message-logs-drawer">
          <div class="message-logs-toggle" onclick="this.parentElement.classList.toggle('open')">Agent Logs Details</div>
          <pre class="message-logs-content">${m.live_logs}</pre>
        </div>
      ` : '';

      let docxChipHtml = '';
      if (!isUser && m.content && m.content.toLowerCase().includes("what can be implemented")) {
        docxChipHtml = `
          <button class="download-docx-chip btn-ghost" style="position: absolute; top: 0.5rem; right: 0.5rem; font-size: 11px; padding: 4px 8px; border: 1px solid var(--hairline);" onclick="window.downloadMD(this, '${currentSessionId}')">
            Download MD
          </button>
        `;
      }

      return `
        <div class="message-bubble ${bubbleClass}" style="position: relative;">
          <div class="message-role-tag">${roleTag}</div>
          ${docxChipHtml}
          <div class="message-content">${contentHtml}</div>
          ${logsDrawerHtml}
        </div>
      `;
    }).join('');

    chatMessagesContainer.innerHTML = messagesHtml;
    
    // Auto-scroll content
    const reportPane = document.getElementById('report-view');
    reportPane.scrollTop = reportPane.scrollHeight;
  }

  // ─── Form Submission & Event Stream Handling ────────────────────────────────
  async function runFeasibilityCheck(repoId, provider, model, promptText) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '...';

    // Hide empty placeholder if visible
    placeholderView.style.display = 'none';
    chatMessagesContainer.style.display = 'flex';

    // 1. Instantly append User Prompt bubble
    const userPromptHtml = `
      <div class="message-bubble user">
        <div class="message-role-tag">[+] USER PROMPT</div>
        <div class="message-content"><p>${promptText}</p></div>
      </div>
    `;
    
    // Create assistant running bubble placeholder
    const assistantBubbleHtml = `
      <div class="message-bubble assistant" id="active-run-bubble">
        <div class="message-role-tag">[x] EVALUATION REPORT (RUNNING...)</div>
        <div class="message-content">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--mute); font-size: 13px; margin-bottom: 0.75rem;">
            <span class="active-run-spinner"></span>
            <span>Agent analysis active...</span>
          </div>
          <div id="active-run-steps" style="font-family: var(--font-mono); font-size: 12px; background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: var(--radius-sm); padding: 0.75rem; max-height: 180px; overflow-y: auto; color: var(--body); white-space: pre-wrap; line-height: 1.5;">
          </div>
        </div>
      </div>
    `;

    // Remove any leftover active running bubble and append new bubbles
    const oldActiveBubble = document.getElementById('active-run-bubble');
    if (oldActiveBubble) oldActiveBubble.remove();
    
    chatMessagesContainer.insertAdjacentHTML('beforeend', userPromptHtml + assistantBubbleHtml);

    // Auto-scroll chat area
    const reportPane = document.getElementById('report-view');
    reportPane.scrollTop = reportPane.scrollHeight;

    const runStepsContainer = document.getElementById('active-run-steps');

    try {
      const headers = getAuthHeaders({ 'Content-Type': 'application/json' });
      
      // Phase 1: Trigger run
      const triggerResp = await fetch('/api/feasibility/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          session_id: currentSessionId,
          repo_id: repoId,
          feature_request: promptText,
          provider,
          model
        })
      });

      if (!triggerResp.ok) {
        const errData = await triggerResp.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to trigger feasibility check');
      }

      const { run_id, session_id } = await triggerResp.json();
      currentSessionId = session_id;
      
      // Immediately reload history to show/active the session thread
      await loadChatHistory();
      
      // Phase 2: Subscribe to real-time events
      const tokenParam = idToken ? `?token=${encodeURIComponent(idToken)}` : '';
      const eventSource = new EventSource(`/api/feasibility/stream/${run_id}${tokenParam}`);
      
      eventSource.onopen = () => {
        runStepsContainer.innerHTML += '> Connecting to agent graph…\n';
      };

      eventSource.onerror = (err) => {
        if (eventSource.readyState === EventSource.CLOSED) {
          eventSource.close();
          runStepsContainer.innerHTML += '\n> Connection closed by server.';
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
          
          // Re-sync with database to load final state
          setTimeout(() => selectChatSession(currentSessionId), 500);
        } else {
          runStepsContainer.innerHTML += '> Reconnecting to agent stream…\n';
        }
        runStepsContainer.scrollTop = runStepsContainer.scrollHeight;
      };

      eventSource.onmessage = async (event) => {
        const payload = JSON.parse(event.data);

        if (payload.event === 'done') {
          eventSource.close();
          runStepsContainer.innerHTML += '\n> Feasibility evaluation completed.';
          
          // Restore normal states
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
          featureRequest.value = '';
          featureRequest.style.height = '';

          // Reload session details to display finalized markdown content from DB
          await selectChatSession(currentSessionId);
        } else if (payload.event === 'error') {
          runStepsContainer.innerHTML += `\n⚠️ Error: ${payload.message}\n`;
        } else if (payload.event === 'node_start') {
          const stepName = payload.node.toUpperCase();
          runStepsContainer.innerHTML += `>[${stepName} START] ${payload.message || ''}\n`;
        } else if (payload.event === 'node_complete') {
          const stepName = payload.node.toUpperCase();
          runStepsContainer.innerHTML += `>[${stepName} COMPLETE] ${payload.message || ''}\n`;
        } else {
          runStepsContainer.innerHTML += `> ${payload.message || JSON.stringify(payload)}\n`;
        }
        runStepsContainer.scrollTop = runStepsContainer.scrollHeight;
        reportPane.scrollTop = reportPane.scrollHeight;
      };

    } catch (err) {
      if (runStepsContainer) {
        runStepsContainer.innerHTML += `\n⚠️ Error: ${err.message}\n`;
        runStepsContainer.scrollTop = runStepsContainer.scrollHeight;
      }
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
    }
  }

  // Handle Enter key for submission
  featureRequest.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (featureRequest.value.trim() !== '') {
        evaluationForm.dispatchEvent(new Event('submit'));
      }
    }
  });

  evaluationForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const repoId = repoSelect.value;
    const provider = providerSelect.value;
    const model = modelSelect.value || null;
    const requestVal = featureRequest.value;

    if (!repoId) return;

    await runFeasibilityCheck(repoId, provider, model, requestVal);
  });

  // ─── Rules Template Downloading ──────────────────────────────────────────
  const downloadTemplateBtn = document.getElementById('download-template-btn');
  downloadTemplateBtn.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/rules/template', { headers: getAuthHeaders() });
      if (!response.ok) throw new Error('Failed to download rules template');
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'rules.md';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert('Error: ' + err.message);
    }
  });

  // ─── Rules Template Uploading ────────────────────────────────────────────
  const uploadRulesBtn = document.getElementById('upload-rules-btn');
  const rulesFileInput = document.getElementById('rules-file-input');
  uploadRulesBtn.addEventListener('click', async () => {
    const file = rulesFileInput.files[0];
    if (!file) {
      alert('Please select a rules.md file first.');
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    try {
      uploadRulesBtn.disabled = true;
      uploadRulesBtn.textContent = 'Uploading…';
      const response = await fetch('/api/rules/upload', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to upload rules');
      }
      alert('Rules uploaded successfully!');
      rulesFileInput.value = '';
    } catch (err) {
      alert('Error: ' + err.message);
    } finally {
      uploadRulesBtn.disabled = false;
      uploadRulesBtn.textContent = 'Upload Rules File';
    }
  });

  // ─── User Role Switching ──────────────────────────────────────────────────
  if (roleSelect) {
    roleSelect.addEventListener('change', async () => {
      const selectedRole = roleSelect.value;
      try {
        const response = await fetch('/api/users/role', {
          method: 'POST',
          headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ role: selectedRole })
        });
        if (response.ok) {
          toggleAdminPanelUI(selectedRole);
          // Reload repository lists and chat history under the new role
          await loadRepositories();
          await loadChatHistory();
        } else {
          const errData = await response.json().catch(() => ({}));
          alert('Failed to update role: ' + (errData.detail || 'Unknown error'));
          // Revert selection
          await updateAuthState();
        }
      } catch (err) {
        alert('Error: ' + err.message);
        await updateAuthState();
      }
    });
  }

  // ─── Repository Config Submission ─────────────────────────────────────────
  if (repoConfigForm) {
    repoConfigForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('new-repo-name').value;
      const vcsUrl = document.getElementById('new-repo-url').value;
      const customDomain = document.getElementById('new-repo-domain').value || null;

      try {
        const addBtn = document.getElementById('add-repo-btn');
        addBtn.disabled = true;
        addBtn.textContent = 'Adding…';

        const response = await fetch('/api/repositories', {
          method: 'POST',
          headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ name, vcs_url: vcsUrl, custom_domain: customDomain })
        });

        if (response.ok) {
          alert('Repository added successfully!');
          document.getElementById('new-repo-name').value = '';
          document.getElementById('new-repo-url').value = '';
          document.getElementById('new-repo-domain').value = '';
          // Reload repositories dropdown
          await loadRepositories();
        } else {
          const errData = await response.json().catch(() => ({}));
          alert('Failed to add repository: ' + (errData.detail || 'Unknown error'));
        }
      } catch (err) {
        alert('Error: ' + err.message);
      } finally {
        const addBtn = document.getElementById('add-repo-btn');
        addBtn.disabled = false;
        addBtn.textContent = 'Add Repository';
      }
    });
  }

  // ─── Markdown Download Implementation ──────────────────────────────────────
  window.downloadMD = async function(btn, sessionId) {
    try {
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Downloading...';
      
      const response = await fetch(`/api/chats/${sessionId}`, {
        headers: getAuthHeaders()
      });
      if (!response.ok) throw new Error('Failed to fetch chat data');
      
      const data = await response.json();
      const messages = data.messages || [];
      const reportMsg = messages.slice().reverse().find(m => m.role !== 'user' && m.content && m.content.toLowerCase().includes("what can be implemented"));
      
      if (!reportMsg) throw new Error('Report not found in chat history');
      
      const blob = new Blob([reportMsg.content], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `feasibility_report_${sessionId.substring(0, 8)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      btn.textContent = originalText;
      btn.disabled = false;
    } catch (err) {
      alert('Failed to download MD: ' + err.message);
      btn.textContent = 'Download MD';
      btn.disabled = false;
    }
  };
});

