/**
 * Flinza Works — Enterprise Outreach Studio SPA Engine
 * Mailflare Webmail Client, Aliases Routing Manager, and Dual Theme Controller.
 */

document.addEventListener("DOMContentLoaded", () => {
  // ═══════════════════════════════════════════════════════════════
  //                    THEME CONTROLLER
  // ═══════════════════════════════════════════════════════════════
  const themeToggleBtn = document.getElementById("btn-toggle-theme");
  const themeToggleIcon = document.getElementById("theme-toggle-icon");
  const themeToggleText = document.getElementById("theme-toggle-text");

  function initTheme() {
    const saved = localStorage.getItem("flinza_theme") || "light";
    setTheme(saved);
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("flinza_theme", theme);
    if (theme === "dark") {
      themeToggleIcon.textContent = "☀️";
      themeToggleText.textContent = "Light Mode";
    } else {
      themeToggleIcon.textContent = "🌙";
      themeToggleText.textContent = "Dark Mode";
    }
  }

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      setTheme(current === "dark" ? "light" : "dark");
    });
  }

  initTheme();

  // ═══════════════════════════════════════════════════════════════
  //                    NAVIGATION CONTROLLER
  // ═══════════════════════════════════════════════════════════════
  const navItems = document.querySelectorAll(".nav-item");
  const viewSections = document.querySelectorAll(".view-section");
  let currentFolder = "inbox";
  let activeSearchQuery = "";

  function switchView(viewName) {
    navItems.forEach(item => {
      item.classList.toggle("active", item.dataset.view === viewName);
    });

    // Check if it's a webmail folder view
    if (viewName.startsWith("webmail-")) {
      const folder = viewName.replace("webmail-", "");
      currentFolder = folder;
      viewSections.forEach(section => {
        section.classList.toggle("active", section.id === "view-webmail");
      });
      loadWebmailThreads(folder, activeSearchQuery);
      return;
    }

    viewSections.forEach(section => {
      section.classList.toggle("active", section.id === `view-${viewName}`);
    });

    if (viewName === "dashboard") loadDashboard();
    else if (viewName === "aliases-routing") loadAliasesRouting();
    else if (viewName === "leads") loadLeads();
    else if (viewName === "mailboxes") loadMailboxes();
    else if (viewName === "cloudflare") loadCloudflare();
    else if (viewName === "sequences") loadSequences();
    else if (viewName === "endpoints") loadEndpoints();
    else if (viewName === "settings") loadSettings();
  }

  navItems.forEach(item => {
    item.addEventListener("click", () => switchView(item.dataset.view));
  });

  // Global search bar
  const globalSearchInput = document.getElementById("global-mail-search");
  if (globalSearchInput) {
    let debounceTimer;
    globalSearchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        activeSearchQuery = e.target.value.trim();
        // Switch to webmail if in another view
        const activeSection = document.querySelector(".view-section.active");
        if (activeSection && activeSection.id !== "view-webmail") {
          switchView("webmail-inbox");
        } else {
          loadWebmailThreads(currentFolder, activeSearchQuery);
        }
      }, 250);
    });
  }

  // ═══════════════════════════════════════════════════════════════
  //             MAILFLARE WEBMAIL CLIENT (PRIORITY INBOX)
  // ═══════════════════════════════════════════════════════════════
  let currentLoadedThreads = [];
  let selectedThreadId = null;

  async function loadWebmailThreads(folder = "inbox", search = "") {
    const titleEl = document.getElementById("webmail-folder-title");
    const countEl = document.getElementById("webmail-thread-counter");
    const rowsList = document.getElementById("mail-rows-list");
    const updatedTimeEl = document.getElementById("webmail-updated-time");

    const folderTitles = {
      inbox: "Priority inbox",
      sent: "Sent outreach",
      drafts: "Drafts & AI responses",
      spam: "Spam & suppressed",
    };
    if (titleEl) titleEl.textContent = folderTitles[folder] || "Priority inbox";

    try {
      const res = await fetch(`/api/webmail/threads?folder=${folder}&search=${encodeURIComponent(search)}`);
      const data = await res.json();
      if (!data.success) return;

      currentLoadedThreads = data.threads || [];
      if (countEl) countEl.textContent = currentLoadedThreads.length;
      if (updatedTimeEl) updatedTimeEl.textContent = "Updated just now";

      // Update folder badges in sidebar
      if (data.counts) {
        const bInbox = document.getElementById("badge-webmail-inbox");
        const bDrafts = document.getElementById("badge-webmail-drafts");
        const bSent = document.getElementById("badge-webmail-sent");
        const bSpam = document.getElementById("badge-webmail-spam");
        if (bInbox) bInbox.textContent = data.counts.inbox || 0;
        if (bDrafts) bDrafts.textContent = data.counts.drafts || 0;
        if (bSent) bSent.textContent = data.counts.sent || 0;
        if (bSpam) bSpam.textContent = data.counts.spam || 0;
      }

      if (currentLoadedThreads.length === 0) {
        rowsList.innerHTML = `
          <div style="padding: 48px 24px; text-align: center; color: var(--text-dim);">
            <div style="font-size: 32px; margin-bottom: 12px;">📭</div>
            <h3 style="color: var(--text-main); font-size: 16px; margin-bottom: 4px;">No emails in ${folderTitles[folder] || folder}</h3>
            <p style="font-size: 13px;">Incoming responses and messages will appear here automatically.</p>
          </div>
        `;
        return;
      }

      rowsList.innerHTML = currentLoadedThreads.map(t => {
        let tagClass = "tag-inbound";
        const tagLower = (t.tag || "").toLowerCase();
        if (tagLower.includes("sent")) tagClass = "tag-sent";
        else if (tagLower.includes("interest")) tagClass = "tag-interested";
        else if (tagLower.includes("draft")) tagClass = "tag-draft";
        else if (tagLower.includes("hook")) tagClass = "tag-hook";
        else if (tagLower.includes("admin")) tagClass = "tag-admin";

        const senderDisplay = t.sender || "Unknown Sender";
        const subjectDisplay = t.subject || "(No Subject)";
        const snippetDisplay = t.snippet || "";

        return `
          <div class="mail-row ${selectedThreadId === t.id ? 'active' : ''}" data-id="${t.id}">
            <div class="mail-icon-cell">✉️</div>
            <div class="mail-sender-cell" title="${senderDisplay}">${senderDisplay}</div>
            <div class="mail-snippet-cell">
              <span class="mail-subject-bold">${escapeHtml(subjectDisplay)}</span>
              ${snippetDisplay ? `<span class="mail-snippet-muted"> - ${escapeHtml(snippetDisplay)}</span>` : ''}
            </div>
            <div class="mail-tag-cell">
              <span class="mail-tag ${tagClass}">${t.tag || 'Inbound'}</span>
            </div>
          </div>
        `;
      }).join("");

      // Attach row click listeners
      rowsList.querySelectorAll(".mail-row").forEach(row => {
        row.addEventListener("click", () => {
          const id = parseInt(row.dataset.id);
          openThreadDetail(id);
        });
      });

    } catch (err) {
      console.error("Error loading webmail threads:", err);
    }
  }

  function openThreadDetail(id) {
    selectedThreadId = id;
    const thread = currentLoadedThreads.find(t => t.id === id);
    if (!thread) return;

    // Highlight row
    document.querySelectorAll(".mail-row").forEach(r => {
      r.classList.toggle("active", parseInt(r.dataset.id) === id);
    });

    const readingPane = document.getElementById("webmail-reading-pane");
    const readSubject = document.getElementById("read-subject");
    const readTag = document.getElementById("read-tag");
    const readSender = document.getElementById("read-sender");
    const readRecipient = document.getElementById("read-recipient");
    const readTime = document.getElementById("read-time");
    const readBody = document.getElementById("read-body");
    const aiComposer = document.getElementById("read-ai-composer");
    const aiDraftText = document.getElementById("read-ai-draft-text");

    readingPane.style.display = "flex";
    readSubject.textContent = thread.subject || "(No Subject)";
    readTag.textContent = thread.tag || "Inbound";
    readSender.textContent = thread.sender || "unknown";
    readRecipient.textContent = thread.recipient || "you";
    readTime.textContent = thread.timestamp ? new Date(thread.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Recently";
    readBody.textContent = thread.body || "No message content.";

    // If there is an AI draft or inbound message
    if (thread.ai_draft_body || thread.type === "inbound") {
      aiComposer.style.display = "flex";
      aiDraftText.value = thread.ai_draft_body || `Hi ${thread.lead_name || 'there'},\n\nThank you for getting back to us. We would love to walk you through our short-form organic growth workflow.\n\nBest,\nFlinza Team`;
    } else {
      aiComposer.style.display = "none";
    }
  }

  const btnCloseReading = document.getElementById("btn-close-reading");
  if (btnCloseReading) {
    btnCloseReading.addEventListener("click", () => {
      document.getElementById("webmail-reading-pane").style.display = "none";
      selectedThreadId = null;
      document.querySelectorAll(".mail-row").forEach(r => r.classList.remove("active"));
    });
  }

  const btnSendReadDraft = document.getElementById("btn-send-read-draft");
  if (btnSendReadDraft) {
    btnSendReadDraft.addEventListener("click", async () => {
      if (!selectedThreadId) return;
      const customText = document.getElementById("read-ai-draft-text").value.trim();
      btnSendReadDraft.disabled = true;
      btnSendReadDraft.textContent = "🚀 Dispatching...";

      try {
        const res = await fetch("/api/unibox/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reply_id: selectedThreadId, body: customText })
        });
        const d = await res.json();
        if (d.success) {
          alert("✅ Reply successfully sent to prospect!");
          document.getElementById("webmail-reading-pane").style.display = "none";
          loadWebmailThreads(currentFolder, activeSearchQuery);
        } else {
          alert(`❌ Error sending reply: ${d.error || 'Failed'}`);
        }
      } catch (err) {
        alert(`❌ Network error: ${err}`);
      } finally {
        btnSendReadDraft.disabled = false;
        btnSendReadDraft.textContent = "🚀 Send This Reply";
      }
    });
  }

  const btnDiscardDraft = document.getElementById("btn-discard-draft");
  if (btnDiscardDraft) {
    btnDiscardDraft.addEventListener("click", () => {
      document.getElementById("read-ai-composer").style.display = "none";
    });
  }

  const btnRefreshWebmail = document.getElementById("btn-refresh-webmail");
  if (btnRefreshWebmail) {
    btnRefreshWebmail.addEventListener("click", async () => {
      btnRefreshWebmail.style.transform = "rotate(360deg)";
      try {
        await fetch("/api/unibox/check", { method: "POST" });
      } catch (e) {}
      setTimeout(() => {
        btnRefreshWebmail.style.transform = "rotate(0deg)";
        loadWebmailThreads(currentFolder, activeSearchQuery);
      }, 400);
    });
  }

  // ═══════════════════════════════════════════════════════════════
  //           CUSTOM ALIASES & ROUTING ARCHITECTURE MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadAliasesRouting() {
    const grid = document.getElementById("aliases-routing-grid");
    const badgeAliases = document.getElementById("badge-routing-aliases");
    if (!grid) return;

    try {
      const res = await fetch("/api/aliases/routing");
      const data = await res.json();
      if (!data.success) return;

      const aliases = data.aliases || [];
      const accounts = data.accounts || [];
      if (badgeAliases) badgeAliases.textContent = aliases.length;

      if (aliases.length === 0) {
        grid.innerHTML = `
          <div style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-dim);">
            <h3>No Custom Domain Aliases Registered</h3>
            <p style="margin-top: 6px;">Click "Add Domain Alias & Route" or "Auto-Generate 5 CF Aliases" to begin.</p>
          </div>
        `;
        return;
      }

      grid.innerHTML = aliases.map(a => {
        const mode = a.routing_mode || "gmail_send_as";
        let modeBadge = `<span class="route-mode-badge route-mode-gmail">✉️ Gmail Send-As</span>`;
        let pathDesc = `Routes via connected Gmail (<code>${a.smtp_user}</code>)`;

        if (mode === "cloudflare_api") {
          modeBadge = `<span class="route-mode-badge route-mode-cf">⚡ Cloudflare Native API ($5/mo)</span>`;
          pathDesc = `Sends directly through Cloudflare Edge REST API`;
        } else if (mode === "external_smtp") {
          modeBadge = `<span class="route-mode-badge route-mode-ses">🚀 Amazon SES / Dedicated SMTP</span>`;
          pathDesc = `Routes through AWS SES (<code>${a.smtp_host || 'email-smtp'}</code>)`;
        }

        return `
          <div class="alias-route-card" data-alias="${a.alias}">
            <div class="alias-card-top">
              <div>
                <div class="alias-address-title">${a.alias}</div>
                <div class="alias-display-subtitle">${a.display_name || 'Outreach Alias'} • Limit: ${a.daily_limit}/day</div>
              </div>
              ${modeBadge}
            </div>

            <div class="alias-route-path">
              <span>🔀</span>
              <div>${pathDesc}</div>
            </div>

            <div class="alias-route-selector">
              <label>Switch Dispatch Route:</label>
              <select class="form-select alias-route-select" data-alias="${a.alias}">
                <option value="gmail_send_as" ${mode === 'gmail_send_as' ? 'selected' : ''}>✉️ Gmail Send-As Relay</option>
                <option value="cloudflare_api" ${mode === 'cloudflare_api' ? 'selected' : ''}>⚡ Cloudflare Native API ($5/mo)</option>
                <option value="external_smtp" ${mode === 'external_smtp' ? 'selected' : ''}>🚀 Amazon SES / Dedicated SMTP</option>
              </select>
            </div>

            <div class="alias-card-actions">
              <button class="btn btn-outline btn-sm btn-test-alias-route" data-alias="${a.alias}">⚡ Test Route</button>
              <button class="btn btn-sm btn-danger btn-delete-alias" data-alias="${a.alias}">🗑️ Delete</button>
            </div>
          </div>
        `;
      }).join("");

      // Route select change listener
      grid.querySelectorAll(".alias-route-select").forEach(sel => {
        sel.addEventListener("change", async (e) => {
          const alias = e.target.dataset.alias;
          const newMode = e.target.value;
          try {
            const upd = await fetch("/api/aliases/update-routing", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ alias: alias, routing_mode: newMode })
            });
            const d = await upd.json();
            if (d.success) {
              loadAliasesRouting();
            }
          } catch (err) {
            alert(`Failed to update routing: ${err}`);
          }
        });
      });

      // Test route listener
      grid.querySelectorAll(".btn-test-alias-route").forEach(btn => {
        btn.addEventListener("click", async () => {
          const alias = btn.dataset.alias;
          btn.disabled = true;
          btn.textContent = "⚡ Testing...";
          try {
            const res = await fetch("/api/aliases/test-route", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ alias: alias, to_email: "rajdep.f12x@gmail.com" })
            });
            const r = await res.json();
            if (r.success) {
              alert(`✅ Test route verified for ${alias}!\nLatency: ${r.elapsed_ms || 0}ms\nMessage-ID: ${r.message_id || 'OK'}`);
            } else {
              alert(`❌ Route test failed: ${r.error || 'Failed'}`);
            }
          } catch (e) {
            alert(`❌ Network error: ${e}`);
          } finally {
            btn.disabled = false;
            btn.textContent = "⚡ Test Route";
          }
        });
      });

      // Delete alias listener
      grid.querySelectorAll(".btn-delete-alias").forEach(btn => {
        btn.addEventListener("click", async () => {
          const alias = btn.dataset.alias;
          if (!confirm(`Delete sending alias ${alias}?`)) return;
          try {
            await fetch(`/api/accounts/alias/${encodeURIComponent(alias)}`, { method: "DELETE" });
            loadAliasesRouting();
          } catch (e) {}
        });
      });

    } catch (err) {
      console.error("Error loading aliases routing:", err);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //                    COMPOSE MODAL MODULE
  // ═══════════════════════════════════════════════════════════════
  const btnOpenCompose = document.getElementById("btn-open-compose");
  const backdropCompose = document.getElementById("backdrop-compose");
  const btnCloseCompose = document.getElementById("btn-close-compose");
  const btnCancelCompose = document.getElementById("btn-cancel-compose");
  const formCompose = document.getElementById("form-compose-email");
  const composeFromSelect = document.getElementById("compose-from-select");

  if (btnOpenCompose) {
    btnOpenCompose.addEventListener("click", async () => {
      backdropCompose.classList.add("active");
      // Populate senders list
      try {
        const res = await fetch("/api/accounts");
        const d = await res.json();
        if (d.success) {
          const accs = d.accounts || [];
          const aliases = d.aliases || [];
          composeFromSelect.innerHTML = "";

          if (aliases.length > 0) {
            const optgroupAliases = document.createElement("optgroup");
            optgroupAliases.label = "Verified Domain Aliases";
            aliases.forEach(al => {
              const opt = document.createElement("option");
              opt.value = al.alias;
              opt.textContent = `${al.display_name || 'Alias'} <${al.alias}>`;
              optgroupAliases.appendChild(opt);
            });
            composeFromSelect.appendChild(optgroupAliases);
          }

          if (accs.length > 0) {
            const optgroupAccs = document.createElement("optgroup");
            optgroupAccs.label = "Master Outbound Accounts";
            accs.forEach(a => {
              const opt = document.createElement("option");
              opt.value = a.email;
              opt.textContent = `${a.email} (${a.provider || 'SMTP'})`;
              optgroupAccs.appendChild(opt);
            });
            composeFromSelect.appendChild(optgroupAccs);
          }
        }
      } catch (e) {}
    });
  }

  if (btnCloseCompose) btnCloseCompose.addEventListener("click", () => backdropCompose.classList.remove("active"));
  if (btnCancelCompose) btnCancelCompose.addEventListener("click", () => backdropCompose.classList.remove("active"));

  if (formCompose) {
    formCompose.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fromAcct = composeFromSelect.value;
      const toEmail = document.getElementById("compose-to").value.trim();
      const subject = document.getElementById("compose-subject").value.trim();
      const body = document.getElementById("compose-body").value.trim();

      const submitBtn = document.getElementById("btn-send-compose");
      submitBtn.disabled = true;
      submitBtn.textContent = "🚀 Sending...";

      try {
        const res = await fetch("/api/webmail/compose", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            from_account: fromAcct,
            to_email: toEmail,
            subject: subject,
            body: body
          })
        });
        const d = await res.json();
        if (d.success) {
          alert(`✅ Message sent to ${toEmail}!`);
          backdropCompose.classList.remove("active");
          formCompose.reset();
          loadWebmailThreads(currentFolder, activeSearchQuery);
        } else {
          alert(`❌ Failed to send: ${d.error || 'Unknown error'}`);
        }
      } catch (err) {
        alert(`❌ Network error: ${err}`);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "🚀 Send Message";
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════
  //             CREATE ALIAS & ROUTE MODAL MODULE
  // ═══════════════════════════════════════════════════════════════
  const btnOpenCreateAlias = document.getElementById("btn-open-create-alias");
  const backdropCreateAlias = document.getElementById("backdrop-create-alias");
  const btnCloseCreateAlias = document.getElementById("btn-close-create-alias");
  const formCreateAlias = document.getElementById("form-create-alias");
  const aliasInMaster = document.getElementById("alias-in-master");

  if (btnOpenCreateAlias) {
    btnOpenCreateAlias.addEventListener("click", async () => {
      backdropCreateAlias.classList.add("active");
      try {
        const res = await fetch("/api/accounts");
        const d = await res.json();
        if (d.success && aliasInMaster) {
          aliasInMaster.innerHTML = (d.accounts || []).map(a => `<option value="${a.email}">${a.email}</option>`).join("");
        }
      } catch (e) {}
    });
  }

  if (btnCloseCreateAlias) btnCloseCreateAlias.addEventListener("click", () => backdropCreateAlias.classList.remove("active"));

  if (formCreateAlias) {
    formCreateAlias.addEventListener("submit", async (e) => {
      e.preventDefault();
      const alias = document.getElementById("alias-in-address").value.trim();
      const display = document.getElementById("alias-in-display").value.trim();
      const mode = document.getElementById("alias-in-mode").value;
      const master = aliasInMaster.value;
      const forward = document.getElementById("alias-in-forward").value.trim();

      try {
        const res = await fetch("/api/aliases/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            alias: alias,
            display_name: display,
            routing_mode: mode,
            smtp_user: master,
            forward_to: forward
          })
        });
        const d = await res.json();
        if (d.success) {
          alert(`✅ Alias ${alias} created and configured for ${mode}!`);
          backdropCreateAlias.classList.remove("active");
          formCreateAlias.reset();
          loadAliasesRouting();
        } else {
          alert(`❌ Failed to create alias: ${d.detail || 'Error'}`);
        }
      } catch (err) {
        alert(`❌ Network error: ${err}`);
      }
    });
  }

  // 1-Click Auto-generate 5 CF Aliases button
  const btnCfGen5Routing = document.getElementById("btn-cf-gen5-routing");
  if (btnCfGen5Routing) {
    btnCfGen5Routing.addEventListener("click", async () => {
      btnCfGen5Routing.disabled = true;
      btnCfGen5Routing.textContent = "⚡ Generating...";
      try {
        const res = await fetch("/api/cloudflare/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count: 5 })
        });
        const d = await res.json();
        if (d.success) {
          alert(`✅ Successfully created ${d.created.length} new Cloudflare domain aliases!`);
          loadAliasesRouting();
        } else {
          alert(`❌ Cloudflare generation error: ${d.error || 'Failed'}`);
        }
      } catch (e) {
        alert(`Network error: ${e}`);
      } finally {
        btnCfGen5Routing.disabled = false;
        btnCfGen5Routing.textContent = "⚡ Auto-Generate 5 CF Aliases";
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════
  //                      DASHBOARD MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadDashboard() {
    try {
      const res = await fetch("/api/stats");
      const data = await res.json();
      if (!data.success) return;

      const s = data.stats;
      const t = data.tracking;

      document.getElementById("stat-sent-today").textContent = s.sent_today;
      document.getElementById("stat-cap").textContent = (s.sent_today + s.remaining_today);
      document.getElementById("stat-open-rate").textContent = `${t.open_rate}%`;
      document.getElementById("stat-opened-count").textContent = t.total_opened;
      document.getElementById("stat-click-rate").textContent = `${t.click_rate}%`;
      document.getElementById("stat-clicked-count").textContent = t.total_clicked;
      document.getElementById("stat-replies").textContent = s.total_replies;
      document.getElementById("stat-unhandled").textContent = s.unhandled_replies;

      // Badges
      const bLeads = document.getElementById("badge-leads");
      const bInboxes = document.getElementById("badge-inboxes");
      if (bLeads) bLeads.textContent = s.total_leads;
      if (bInboxes) bInboxes.textContent = s.accounts;

      // Pipeline breakdown
      const pipelineContainer = document.getElementById("pipeline-breakdown");
      if (pipelineContainer) {
        pipelineContainer.innerHTML = "";
        const p = data.pipeline;
        const stageOrder = [
          { key: "new", label: "🆕 New Prospects" },
          { key: "contacted", label: "📤 First Opener Sent" },
          { key: "opened", label: "👁️ Email Opened" },
          { key: "clicked", label: "🔗 Link Clicked" },
          { key: "followup_1", label: "1️⃣ Follow-Up #1 Sent" },
          { key: "followup_2", label: "2️⃣ Follow-Up #2 Sent" },
          { key: "replied", label: "💬 Replied / Inbound" },
        ];

        stageOrder.forEach(stage => {
          const count = p[stage.key] || 0;
          const row = document.createElement("div");
          row.className = "pipeline-row";
          row.innerHTML = `
            <span>${stage.label}</span>
            <strong>${count}</strong>
          `;
          pipelineContainer.appendChild(row);
        });
      }
    } catch (err) {
      console.error("Dashboard error:", err);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //                      LEADS CRM MODULE
  // ═══════════════════════════════════════════════════════════════
  let currentLeads = [];
  let currentStageFilter = "all";

  async function loadLeads() {
    try {
      const url = currentStageFilter === "all"
        ? "/api/leads?stage=all"
        : `/api/leads?stage=${currentStageFilter}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!data.success) return;

      currentLeads = data.leads;
      renderLeadsTable(currentLeads);
    } catch (err) {
      console.error("Leads error:", err);
    }
  }

  function renderLeadsTable(leads) {
    const tbody = document.getElementById("leads-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (leads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 32px;">No leads found. Click "Add Lead" or "Import CSV" to get started.</td></tr>`;
      return;
    }

    leads.forEach(l => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${escapeHtml(l.name || "Lead")}</strong></td>
        <td><code>${escapeHtml(l.email)}</code></td>
        <td>${escapeHtml(l.company || "-")}</td>
        <td>${escapeHtml(l.niche || "General")}</td>
        <td><span class="stage-badge ${l.stage}">${l.stage}</span></td>
        <td>
          <button class="btn btn-outline btn-sm btn-delete-lead" data-id="${l.id}">🗑️</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".btn-delete-lead").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        const id = e.target.dataset.id;
        if (!confirm("Are you sure you want to delete this lead?")) return;
        await fetch(`/api/leads/${id}`, { method: "DELETE" });
        loadLeads();
      });
    });
  }

  // Stage filter tabs
  const stageTabs = document.querySelectorAll("#lead-stage-tabs .tab-btn");
  stageTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      stageTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentStageFilter = tab.dataset.stage;
      loadLeads();
    });
  });

  // Leads search
  const leadsSearch = document.getElementById("leads-search-input");
  if (leadsSearch) {
    leadsSearch.addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase();
      const filtered = currentLeads.filter(l =>
        (l.name && l.name.toLowerCase().includes(query)) ||
        l.email.toLowerCase().includes(query) ||
        (l.company && l.company.toLowerCase().includes(query)) ||
        (l.niche && l.niche.toLowerCase().includes(query))
      );
      renderLeadsTable(filtered);
    });
  }

  // ═══════════════════════════════════════════════════════════════
  //                      MAILBOX FLEET MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadMailboxes() {
    try {
      const res = await fetch("/api/accounts");
      const data = await res.json();
      if (!data.success) return;

      const grid = document.getElementById("accounts-grid");
      if (!grid) return;
      grid.innerHTML = "";

      data.accounts.forEach(a => {
        let badge = '<span class="provider-badge badge-gmail">Gmail</span>';
        if (a.provider === "cloudflare_api") {
          badge = '<span class="provider-badge badge-cf-sending">Cloudflare API ($5/mo)</span>';
        } else if (a.provider === "amazon_ses") {
          badge = '<span class="provider-badge badge-ses">Amazon SES</span>';
        } else if (a.is_oauth) {
          badge = '<span class="provider-badge badge-gmail">OAuth2</span>';
        }

        const card = document.createElement("div");
        card.className = "account-card";
        card.innerHTML = `
          <div class="account-header">
            <span class="account-email">${a.email}</span>
            ${badge}
          </div>
          <div style="font-size: 12.5px; color: var(--text-dim);">
            Daily Limit: <strong>${a.daily_limit}</strong> | Sent Today: <strong>${a.sent_today}</strong>
          </div>
          <div style="display: flex; gap: 8px; margin-top: 6px;">
            <button class="btn btn-outline btn-sm btn-test-account" data-email="${a.email}">Test Login</button>
            <button class="btn btn-danger btn-sm btn-remove-account" data-email="${a.email}">Remove</button>
          </div>
        `;
        grid.appendChild(card);
      });

      // Test account handlers
      grid.querySelectorAll(".btn-test-account").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          const email = e.target.dataset.email;
          btn.textContent = "Testing...";
          const res = await fetch("/api/accounts/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
          });
          const d = await res.json();
          btn.textContent = "Test Login";
          if (d.success) {
            alert(`✅ ${email}: Connection successful!`);
          } else {
            alert(`❌ ${email}: Connection failed!\n${d.error}`);
          }
        });
      });

      // Remove account handlers
      grid.querySelectorAll(".btn-remove-account").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          const email = e.target.dataset.email;
          if (!confirm(`Remove account ${email}?`)) return;
          await fetch(`/api/accounts/${encodeURIComponent(email)}`, { method: "DELETE" });
          loadMailboxes();
        });
      });

    } catch (err) {
      console.error("Mailboxes error:", err);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //                      CLOUDFLARE MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadCloudflare() {
    try {
      const res = await fetch("/api/cloudflare/zones");
      const data = await res.json();
      const container = document.getElementById("cf-zones-container");
      if (!container) return;

      if (!data.zones || data.zones.length === 0) {
        container.innerHTML = `
          <p style="color: var(--text-dim);">No zones discovered. Please verify <code>CF_API_TOKEN</code> in your <code>.env</code> file.</p>
        `;
        return;
      }

      container.innerHTML = data.zones.map(z => `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--bg-card-subtle); border-radius: 12px; margin-bottom: 8px;">
          <div>
            <strong>${z.name}</strong> (Status: ${z.status})
          </div>
          <span class="badge badge-primary">ID: ${z.id.slice(0, 10)}...</span>
        </div>
      `).join("");
    } catch (err) {
      console.error("Cloudflare error:", err);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //                      SEQUENCE ARCHITECT
  // ═══════════════════════════════════════════════════════════════
  async function loadSequences() {
    try {
      const res = await fetch("/api/sequences?campaign_id=1");
      const data = await res.json();
      const container = document.getElementById("sequence-steps-container");
      if (!container) return;

      if (!data.steps || data.steps.length === 0) {
        container.innerHTML = `<p style="color: var(--text-dim);">Using dynamic AI autonomous sequences.</p>`;
        return;
      }

      container.innerHTML = data.steps.map(s => `
        <div class="sequence-step-card" style="background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 14px; padding: 18px; margin-bottom: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 700; color: var(--accent-primary);">Step ${s.step_number} (${s.delay_days} days delay)</span>
            <span class="badge">${s.condition_type}</span>
          </div>
          <div style="font-weight: 600; font-size: 13.5px; margin-bottom: 4px;">${escapeHtml(s.subject_a)}</div>
          <div style="font-size: 12.5px; color: var(--text-muted);">${escapeHtml(s.body_a.slice(0, 150))}...</div>
        </div>
      `).join("");
    } catch (err) {
      console.error("Sequences error:", err);
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //                      ENDPOINTS MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadEndpoints() {
    try {
      const res = await fetch("/api/endpoints");
      const data = await res.json();
      const grid = document.getElementById("endpoints-grid");
      if (!grid) return;

      if (!data.endpoints || data.endpoints.length === 0) {
        grid.innerHTML = `<p style="color: var(--text-dim); grid-column: 1/-1;">No custom endpoints configured yet.</p>`;
        return;
      }

      grid.innerHTML = data.endpoints.map(e => `
        <div class="account-card">
          <div class="account-header">
            <span class="account-email">${escapeHtml(e.name)}</span>
            <span class="provider-badge badge-cf-sending">${escapeHtml(e.model_name)}</span>
          </div>
          <div style="font-size: 12px; color: var(--text-dim); word-break: break-all;">
            URL: <code>${escapeHtml(e.base_url)}</code>
          </div>
        </div>
      `).join("");
    } catch (err) {}
  }

  // ═══════════════════════════════════════════════════════════════
  //                      SETTINGS MODULE
  // ═══════════════════════════════════════════════════════════════
  async function loadSettings() {
    try {
      const res = await fetch("/api/settings");
      const d = await res.json();
      if (!d.success) return;

      const s = d.settings;
      if (document.getElementById("set-sender-name")) document.getElementById("set-sender-name").value = s.sender_name || "";
      if (document.getElementById("set-min-interval")) document.getElementById("set-min-interval").value = s.min_interval_seconds || 120;
      if (document.getElementById("set-max-interval")) document.getElementById("set-max-interval").value = s.max_interval_seconds || 420;
      if (document.getElementById("set-tracking-url")) document.getElementById("set-tracking-url").value = s.tracking_base_url || "";
      if (document.getElementById("set-system-prompt")) document.getElementById("set-system-prompt").value = s.system_prompt || "";
    } catch (err) {}
  }

  // ═══════════════════════════════════════════════════════════════
  //                      GLOBAL CONTROLS
  // ═══════════════════════════════════════════════════════════════
  const btnQuickTest = document.getElementById("btn-quick-test");
  if (btnQuickTest) {
    btnQuickTest.addEventListener("click", async () => {
      btnQuickTest.disabled = true;
      btnQuickTest.textContent = "⚡ Sending...";
      try {
        const res = await fetch("/api/campaign/testsend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to_email: "rajdep.f12x@gmail.com" }),
        });
        const d = await res.json();
        if (d.success) {
          alert(`✅ Instant test email delivered to rajdep.f12x@gmail.com!\nLatency: ${d.elapsed_ms || 0}ms\nAccount: ${d.account_used}`);
        } else {
          alert(`❌ Test failed: ${d.error}`);
        }
      } catch (e) {
        alert(`❌ Network error: ${e}`);
      } finally {
        btnQuickTest.disabled = false;
        btnQuickTest.textContent = "⚡ Instant Test Send";
      }
    });
  }

  const btnLaunchOutreach = document.getElementById("btn-launch-outreach");
  if (btnLaunchOutreach) {
    btnLaunchOutreach.addEventListener("click", async () => {
      if (!confirm("🚀 Launch cold email campaign for all un-contacted leads?")) return;
      btnLaunchOutreach.disabled = true;
      btnLaunchOutreach.textContent = "▶️ Launching...";
      try {
        const res = await fetch("/api/campaign/launch", { method: "POST" });
        const d = await res.json();
        if (d.success) {
          alert(`🎉 Campaign launched! Queued ${d.queued_count} leads for AI outreach.`);
          loadDashboard();
        } else {
          alert(`⚠️ Notice: ${d.message || d.detail}`);
        }
      } catch (e) {
        alert(`❌ Error: ${e}`);
      } finally {
        btnLaunchOutreach.disabled = false;
        btnLaunchOutreach.textContent = "▶️ Launch Outreach";
      }
    });
  }

  // Helper
  function escapeHtml(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initial load
  loadWebmailThreads("inbox");
  loadDashboard();
});
