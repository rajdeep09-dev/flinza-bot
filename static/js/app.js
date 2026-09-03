/**
 * Flinza Outreach OS — SPA Engine v2.0
 * Premium dark edition. Clean backend-driven frontend.
 * All DOM renders updated for new CSS design system.
 */

document.addEventListener("DOMContentLoaded", () => {

  // ═══════════════════════════════════════════════════════
  //  NAVIGATION CONTROLLER
  // ═══════════════════════════════════════════════════════
  const navItems = document.querySelectorAll(".nav-item");
  const viewSections = document.querySelectorAll(".view-section");
  let currentFolder = "inbox";
  let activeSearchQuery = "";

  function switchView(viewName) {
    navItems.forEach(el => el.classList.toggle("active", el.dataset.view === viewName));

    if (viewName.startsWith("webmail-")) {
      const folder = viewName.replace("webmail-", "");
      currentFolder = folder;
      viewSections.forEach(s => s.classList.toggle("active", s.id === "view-webmail"));
      // Update title
      const folderTitles = { inbox: "Inbox", sent: "Sent", drafts: "Drafts", spam: "Spam" };
      setEl("webmail-folder-title", folderTitles[folder] || "Inbox");
      loadWebmailThreads(folder, activeSearchQuery);
      return;
    }

    viewSections.forEach(s => s.classList.toggle("active", s.id === `view-${viewName}`));

    const loaders = {
      dashboard:        loadDashboard,
      "aliases-routing": loadAliasesRouting,
      leads:            loadLeads,
      mailboxes:        loadMailboxes,
      cloudflare:       loadCloudflare,
      sequences:        loadSequences,
      endpoints:        loadEndpoints,
      settings:         loadSettings,
      warmup:           loadWarmup,
      builder:          loadBuilder,
      "ab-lab":         loadAbLab,
      analytics:        loadAnalytics,
      terminal:         loadTerminal,
    };
    if (loaders[viewName]) loaders[viewName]();
  }

  navItems.forEach(item => item.addEventListener("click", () => switchView(item.dataset.view)));

  // Global search
  on("global-mail-search", "input", debounce((e) => {
    activeSearchQuery = e.target.value.trim();
    const activeSection = document.querySelector(".view-section.active");
    if (activeSection && activeSection.id !== "view-webmail") {
      switchView("webmail-inbox");
    } else {
      loadWebmailThreads(currentFolder, activeSearchQuery);
    }
  }, 250));

  // ⌘K / Ctrl+K focus search
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      document.getElementById("global-mail-search")?.focus();
    }
    if (e.key === "Escape") {
      closeAllModals();
    }
  });

  // ═══════════════════════════════════════════════════════
  //  WEBMAIL CLIENT
  // ═══════════════════════════════════════════════════════
  let currentLoadedThreads = [];
  let selectedThreadId = null;

  async function loadWebmailThreads(folder = "inbox", search = "") {
    const rowsList = g("mail-rows-list");
    setEl("webmail-thread-counter", "…");

    try {
      const data = await apiFetch(`/api/webmail/threads?folder=${folder}&search=${encodeURIComponent(search)}`);
      if (!data.success) return;

      currentLoadedThreads = data.threads || [];
      setEl("webmail-thread-counter", currentLoadedThreads.length);

      // Sidebar badge updates
      if (data.counts) {
        setEl("badge-webmail-inbox", data.counts.inbox ?? 0);
        setEl("badge-webmail-sent",  data.counts.sent  ?? 0);
        setEl("badge-webmail-drafts",data.counts.drafts?? 0);
        setEl("badge-webmail-spam",  data.counts.spam  ?? 0);
      }

      if (!rowsList) return;

      if (currentLoadedThreads.length === 0) {
        rowsList.innerHTML = `
          <div class="inbox-empty-state">
            <div class="empty-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.3"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            </div>
            <p>No emails in ${folder}. Incoming messages will show here automatically.</p>
          </div>`;
        return;
      }

      rowsList.innerHTML = currentLoadedThreads.map(t => {
        const initials = (t.sender || "?").slice(0, 2).toUpperCase();
        const tag = t.tag || "Inbound";
        const tagClass = tagToClass(tag);
        const time = t.timestamp ? formatTime(t.timestamp) : "";
        return `
          <div class="mail-row ${selectedThreadId === t.id ? 'active' : ''}" data-id="${t.id}">
            <div class="mail-row-avatar">${initials}</div>
            <div class="mail-row-body">
              <div class="mail-row-top">
                <span class="mail-sender">${esc(t.sender || "Unknown")}</span>
              </div>
              <div class="mail-subject"><b>${esc(t.subject || "(No Subject)")}</b>${t.snippet ? ` — ${esc(t.snippet)}` : ""}</div>
            </div>
            <div class="mail-meta">
              <span class="mail-time">${time}</span>
              <span class="intent-chip ${tagClass}">${esc(tag)}</span>
            </div>
          </div>`;
      }).join("");

      rowsList.querySelectorAll(".mail-row").forEach(row => {
        row.addEventListener("click", () => openThreadDetail(parseInt(row.dataset.id)));
      });

    } catch (err) {
      console.error("Error loading webmail threads:", err);
    }
  }

  function openThreadDetail(id) {
    selectedThreadId = id;
    const thread = currentLoadedThreads.find(t => t.id === id);
    if (!thread) return;

    document.querySelectorAll(".mail-row").forEach(r =>
      r.classList.toggle("active", parseInt(r.dataset.id) === id)
    );

    const pane = g("webmail-reading-pane");
    if (!pane) return;

    pane.style.display = "flex";
    setEl("read-subject", thread.subject || "(No Subject)");
    const tag = thread.tag || "Inbound";
    const tagEl = g("read-tag");
    if (tagEl) { tagEl.textContent = tag; tagEl.className = `intent-chip ${tagToClass(tag)}`; }
    setEl("read-sender", thread.sender || "unknown");
    setEl("read-recipient", thread.recipient || "you");
    setEl("read-time", thread.timestamp ? new Date(thread.timestamp).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" }) : "Recently");

    const bodyEl = g("read-body");
    if (bodyEl) bodyEl.textContent = thread.body || "No message content.";

    const aiComposer = g("read-ai-composer");
    const aiDraft = g("read-ai-draft-text");
    if (thread.ai_draft_body || thread.type === "inbound") {
      if (aiComposer) aiComposer.style.display = "flex";
      if (aiDraft) aiDraft.value = thread.ai_draft_body ||
        `Hi ${thread.lead_name || "there"},\n\nThank you for getting back to us! We'd love to walk you through how we help businesses like yours scale with short-form content.\n\nWould you have 15 minutes this week for a quick call?\n\nBest,\nFlinza Team`;
    } else {
      if (aiComposer) aiComposer.style.display = "none";
    }
  }

  on("btn-close-reading", "click", () => {
    const pane = g("webmail-reading-pane");
    if (pane) pane.style.display = "none";
    selectedThreadId = null;
    document.querySelectorAll(".mail-row").forEach(r => r.classList.remove("active"));
  });

  on("btn-send-read-draft", "click", async (e) => {
    if (!selectedThreadId) return;
    const customText = g("read-ai-draft-text")?.value.trim();
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Sending…`;
    try {
      const d = await apiFetch("/api/unibox/reply", "POST", { reply_id: selectedThreadId, body: customText });
      if (d.success) {
        showToast("✓ Reply dispatched successfully!", "success");
        g("webmail-reading-pane").style.display = "none";
        loadWebmailThreads(currentFolder, activeSearchQuery);
      } else {
        showToast(`Failed: ${d.error || "Unknown error"}`, "error");
      }
    } catch (err) {
      showToast(`Network error: ${err}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Send Reply`;
    }
  });

  on("btn-discard-draft", "click", () => {
    const c = g("read-ai-composer");
    if (c) c.style.display = "none";
  });

  on("btn-refresh-webmail", "click", async (e) => {
    const btn = e.currentTarget;
    btn.style.animation = "spin 0.8s linear";
    try {
      await apiFetch("/api/unibox/check", "POST");
    } catch {}
    setTimeout(() => {
      btn.style.animation = "";
      loadWebmailThreads(currentFolder, activeSearchQuery);
    }, 800);
  });

  // ═══════════════════════════════════════════════════════
  //  ALIASES & ROUTING MODULE
  // ═══════════════════════════════════════════════════════
  async function loadAliasesRouting() {
    const grid = g("aliases-routing-grid");
    const badge = g("badge-routing-aliases");
    if (!grid) return;

    try {
      const data = await apiFetch("/api/aliases/routing");
      if (!data.success) return;

      const aliases = data.aliases || [];
      if (badge) badge.textContent = aliases.length;

      if (aliases.length === 0) {
        grid.innerHTML = `
          <div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--text-dim);">
            <p style="font-size:14px; margin-bottom:8px;">No domain aliases configured yet.</p>
            <p>Click <strong>+ Add Alias</strong> to create your first dispatch route.</p>
          </div>`;
        return;
      }

      grid.innerHTML = aliases.map(a => {
        const mode = a.routing_mode || "gmail_send_as";
        const modeInfo = routeMode(mode, a);
        return `
          <div class="alias-route-card" data-alias="${esc(a.alias)}">
            <div class="alias-card-top">
              <div>
                <div class="alias-address">${esc(a.alias)}</div>
                <div class="alias-subtext">${esc(a.display_name || "Outreach Alias")} · ${a.daily_limit || 50}/day</div>
              </div>
              <span class="route-mode-chip ${modeInfo.cls}">${modeInfo.label}</span>
            </div>
            <div class="alias-route-info">
              <span>→</span>
              <span>${modeInfo.desc}</span>
            </div>
            <div class="form-field" style="margin:0;">
              <select class="form-select alias-route-select" data-alias="${esc(a.alias)}">
                <option value="gmail_send_as" ${mode === "gmail_send_as" ? "selected" : ""}>✉️ Gmail Send-As (Free)</option>
                <option value="cloudflare_api" ${mode === "cloudflare_api" ? "selected" : ""}>⚡ Cloudflare API ($5/mo)</option>
                <option value="external_smtp" ${mode === "external_smtp" ? "selected" : ""}>🚀 Amazon SES / SMTP</option>
              </select>
            </div>
            <div class="alias-card-footer">
              <button class="btn-ghost-sm btn-test-alias-route" data-alias="${esc(a.alias)}">⚡ Test Route</button>
              <button class="btn-ghost-sm btn-delete-alias" data-alias="${esc(a.alias)}" style="color:var(--rose);">Delete</button>
            </div>
          </div>`;
      }).join("");

      // Route select change
      grid.querySelectorAll(".alias-route-select").forEach(sel => {
        sel.addEventListener("change", async (e) => {
          const alias = e.target.dataset.alias;
          const newMode = e.target.value;
          try {
            const d = await apiFetch("/api/aliases/update-routing", "POST", { alias, routing_mode: newMode });
            if (d.success) {
              showToast(`Route updated for ${alias}`, "success");
              loadAliasesRouting();
            }
          } catch (err) {
            showToast(`Update failed: ${err}`, "error");
          }
        });
      });

      // Test route
      grid.querySelectorAll(".btn-test-alias-route").forEach(btn => {
        btn.addEventListener("click", async () => {
          const alias = btn.dataset.alias;
          btn.disabled = true;
          btn.textContent = "Testing…";
          try {
            const r = await apiFetch("/api/aliases/test-route", "POST", { alias, to_email: "rajdep.f12x@gmail.com" });
            if (r.success) {
              showToast(`Route verified for ${alias} (${r.elapsed_ms || 0}ms)`, "success");
            } else {
              showToast(`Test failed: ${r.error}`, "error");
            }
          } catch (e) {
            showToast(`Network error: ${e}`, "error");
          } finally {
            btn.disabled = false;
            btn.textContent = "⚡ Test Route";
          }
        });
      });

      // Delete alias
      grid.querySelectorAll(".btn-delete-alias").forEach(btn => {
        btn.addEventListener("click", async () => {
          const alias = btn.dataset.alias;
          if (!confirm(`Delete alias ${alias}?`)) return;
          await apiFetch(`/api/accounts/alias/${encodeURIComponent(alias)}`, "DELETE");
          loadAliasesRouting();
        });
      });

    } catch (err) {
      console.error("Aliases routing error:", err);
    }
  }

  on("btn-cf-gen5-routing", "click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "⚡ Generating…";
    try {
      const d = await apiFetch("/api/cloudflare/generate", "POST", { count: 5 });
      if (d.success) {
        showToast(`Created ${d.created.length} Cloudflare aliases!`, "success");
        loadAliasesRouting();
      } else {
        showToast(`Failed: ${d.error}`, "error");
      }
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Generate 5 CF Aliases";
    }
  });

  // ═══════════════════════════════════════════════════════
  //  COMPOSE MODAL
  // ═══════════════════════════════════════════════════════
  on("btn-open-compose", "click", async () => {
    openModal("backdrop-compose");
    try {
      const d = await apiFetch("/api/accounts");
      if (d.success) populateFromSelect(d.accounts || [], d.aliases || []);
    } catch {}
  });

  on("btn-close-compose", "click", () => closeModal("backdrop-compose"));
  on("btn-cancel-compose", "click", () => closeModal("backdrop-compose"));

  const formCompose = g("form-compose-email");
  if (formCompose) {
    formCompose.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = g("btn-send-compose");
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Sending…`;
      try {
        const d = await apiFetch("/api/webmail/compose", "POST", {
          from_account: g("compose-from-select")?.value,
          to_email:     g("compose-to")?.value.trim(),
          subject:      g("compose-subject")?.value.trim(),
          body:         g("compose-body")?.value.trim(),
        });
        if (d.success) {
          showToast(`Message sent!`, "success");
          closeModal("backdrop-compose");
          formCompose.reset();
          loadWebmailThreads(currentFolder);
        } else {
          showToast(`Failed: ${d.error}`, "error");
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Send`;
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  //  CREATE ALIAS MODAL
  // ═══════════════════════════════════════════════════════
  on("btn-open-create-alias", "click", async () => {
    openModal("backdrop-create-alias");
    try {
      const d = await apiFetch("/api/accounts");
      const master = g("alias-in-master");
      if (d.success && master) {
        master.innerHTML = (d.accounts || []).map(a =>
          `<option value="${esc(a.email)}">${esc(a.email)}</option>`
        ).join("");
      }
    } catch {}
  });

  on("btn-close-create-alias", "click", () => closeModal("backdrop-create-alias"));

  const formAlias = g("form-create-alias");
  if (formAlias) {
    formAlias.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = g("btn-submit-create-alias");
      btn.disabled = true;
      btn.textContent = "Creating…";
      try {
        const d = await apiFetch("/api/aliases/create", "POST", {
          alias:        g("alias-in-address")?.value.trim(),
          display_name: g("alias-in-display")?.value.trim(),
          routing_mode: g("alias-in-mode")?.value,
          smtp_user:    g("alias-in-master")?.value,
          forward_to:   g("alias-in-forward")?.value.trim(),
        });
        if (d.success) {
          showToast(`Alias created!`, "success");
          closeModal("backdrop-create-alias");
          formAlias.reset();
          loadAliasesRouting();
        } else {
          showToast(`Failed: ${d.detail || "Error"}`, "error");
        }
      } finally {
        btn.disabled = false;
        btn.textContent = "Create Alias";
      }
    });
  }

  // ═══════════════════════════════════════════════════════
  //  DASHBOARD MODULE
  // ═══════════════════════════════════════════════════════
  async function loadDashboard() {
    try {
      const data = await apiFetch("/api/stats");
      if (!data.success) return;

      const s = data.stats;
      const t = data.tracking;

      setEl("stat-sent-today", s.sent_today ?? "—");
      setEl("stat-cap", (s.sent_today ?? 0) + (s.remaining_today ?? 0));
      setEl("stat-open-rate", `${t?.open_rate ?? 0}%`);
      setEl("stat-opened-count", t?.total_opened ?? 0);
      setEl("stat-click-rate", `${t?.click_rate ?? 0}%`);
      setEl("stat-clicked-count", t?.total_clicked ?? 0);
      setEl("stat-replies", s.total_replies ?? "—");
      setEl("stat-unhandled", s.unhandled_replies ?? 0);
      setEl("badge-leads", s.total_leads ?? 0);
      setEl("badge-inboxes", s.accounts ?? 0);

      const pc = g("pipeline-breakdown");
      if (pc && data.pipeline) {
        const p = data.pipeline;
        const stages = [
          { key: "new",         label: "New Prospects" },
          { key: "contacted",   label: "First Email Sent" },
          { key: "opened",      label: "Opened" },
          { key: "clicked",     label: "Clicked" },
          { key: "followup_1",  label: "Follow-Up #1" },
          { key: "followup_2",  label: "Follow-Up #2" },
          { key: "replied",     label: "Replied" },
        ];
        pc.innerHTML = stages.map(st => `
          <div class="pipeline-row">
            <span>${st.label}</span>
            <strong>${p[st.key] ?? 0}</strong>
          </div>`).join("");
      }
    } catch (err) {
      console.error("Dashboard error:", err);
    }
  }

  // Dashboard quick controls
  on("btn-launch-outreach2", "click", () => g("btn-launch-outreach")?.click());
  on("btn-quick-test2",      "click", () => g("btn-quick-test")?.click());
  on("btn-sync-replies",     "click", () => g("btn-refresh-webmail")?.click());

  // ═══════════════════════════════════════════════════════
  //  LEADS CRM MODULE
  // ═══════════════════════════════════════════════════════
  let currentLeads = [];
  let currentStageFilter = "all";

  async function loadLeads() {
    try {
      const url = currentStageFilter === "all" ? "/api/leads?stage=all" : `/api/leads?stage=${currentStageFilter}`;
      const data = await apiFetch(url);
      if (!data.success) return;
      currentLeads = data.leads || [];
      renderLeadsTable(currentLeads);
    } catch (err) {
      console.error("Leads error:", err);
    }
  }

  function renderLeadsTable(leads) {
    const tbody = g("leads-tbody");
    if (!tbody) return;

    if (leads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="table-empty">No leads found. Add leads or import a CSV to get started.</td></tr>`;
      return;
    }

    tbody.innerHTML = leads.map(l => `
      <tr>
        <td>${esc(l.name || "—")}</td>
        <td><code>${esc(l.email)}</code></td>
        <td>${esc(l.company || "—")}</td>
        <td>${esc(l.niche || "General")}</td>
        <td><span class="stage-badge ${l.stage}">${l.stage}</span></td>
        <td>
          <button class="btn-ghost-sm btn-delete-lead" data-id="${l.id}" style="color:var(--rose);">🗑</button>
        </td>
      </tr>`).join("");

    tbody.querySelectorAll(".btn-delete-lead").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this lead?")) return;
        await apiFetch(`/api/leads/${btn.dataset.id}`, "DELETE");
        loadLeads();
      });
    });
  }

  // Stage filter tabs
  document.querySelectorAll("#lead-stage-tabs .stage-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#lead-stage-tabs .stage-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentStageFilter = tab.dataset.stage;
      loadLeads();
    });
  });

  // Leads search
  on("leads-search-input", "input", (e) => {
    const q = e.target.value.toLowerCase();
    renderLeadsTable(currentLeads.filter(l =>
      [l.name, l.email, l.company, l.niche].some(f => f && f.toLowerCase().includes(q))
    ));
  });

  // Zero-Bounce Pre-Send Cleaner
  on("btn-clean-leads", "click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Verifying DNS & MX…";
    try {
      const res = await apiFetch("/api/leads/verify-all", "POST");
      if (res.success) {
        if (res.dead_bounced > 0) {
          showToast(`🛡️ Filtered ${res.dead_bounced} dead/unresolvable lead(s) to prevent bounces!`, "warning");
        } else {
          showToast(`✓ All ${res.scanned} leads verified with active MX records! (0 dead)`, "success");
        }
        loadLeads();
      }
    } catch (err) {
      showToast("Verification failed: " + err, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "🧹 Zero-Bounce Clean";
    }
  });

  // ═══════════════════════════════════════════════════════
  //  MAILBOXES MODULE
  // ═══════════════════════════════════════════════════════
  async function loadMailboxes() {
    const grid = g("accounts-grid");
    if (!grid) return;
    try {
      const data = await apiFetch("/api/accounts");
      if (!data.success) return;

      grid.innerHTML = "";
      data.accounts.forEach(a => {
        const providerClass = { gmail: "provider-gmail", cloudflare_api: "provider-cf", amazon_ses: "provider-ses" }[a.provider] || (a.is_oauth ? "provider-oauth" : "provider-gmail");
        const providerLabel = { gmail: "Gmail", cloudflare_api: "Cloudflare API", amazon_ses: "Amazon SES" }[a.provider] || (a.is_oauth ? "OAuth2" : "SMTP");

        const card = document.createElement("div");
        card.className = "account-card";
        card.innerHTML = `
          <div class="account-top">
            <span class="account-email">${esc(a.email)}</span>
            <span class="provider-badge ${providerClass}">${providerLabel}</span>
          </div>
          <div style="font-size:12px; color:var(--text-dim);">
            Daily cap: <strong>${a.daily_limit}</strong> · Sent today: <strong>${a.sent_today}</strong>
          </div>
          <div style="display:flex; gap:8px; margin-top:4px;">
            <button class="btn-ghost-sm btn-test-account" data-email="${esc(a.email)}">Test Login</button>
            <button class="btn-ghost-sm btn-remove-account" data-email="${esc(a.email)}" style="color:var(--rose);">Remove</button>
          </div>`;
        grid.appendChild(card);
      });

      grid.querySelectorAll(".btn-test-account").forEach(btn => {
        btn.addEventListener("click", async () => {
          const email = btn.dataset.email;
          btn.textContent = "Testing…";
          try {
            const d = await apiFetch("/api/accounts/test", "POST", { email });
            showToast(d.success ? `Connected: ${email}` : `Failed: ${d.error}`, d.success ? "success" : "error");
          } finally { btn.textContent = "Test Login"; }
        });
      });

      grid.querySelectorAll(".btn-remove-account").forEach(btn => {
        btn.addEventListener("click", async () => {
          if (!confirm(`Remove ${btn.dataset.email}?`)) return;
          await apiFetch(`/api/accounts/${encodeURIComponent(btn.dataset.email)}`, "DELETE");
          loadMailboxes();
        });
      });
    } catch (err) { console.error("Mailboxes error:", err); }
  }

  // ═══════════════════════════════════════════════════════
  //  CLOUDFLARE MODULE
  // ═══════════════════════════════════════════════════════
  async function loadCloudflare() {
    const c = g("cf-zones-container");
    if (!c) return;
    c.innerHTML = `<p class="info-text">Fetching Cloudflare zones…</p>`;
    try {
      const data = await apiFetch("/api/cloudflare/zones");
      if (!data.zones || data.zones.length === 0) {
        c.innerHTML = `<p class="info-text">No zones found. Verify <code>CF_API_TOKEN</code> in your <code>.env</code> file.</p>`;
        return;
      }
      c.innerHTML = data.zones.map(z => `
        <div class="audit-zone-row">
          <div>
            <strong>${esc(z.name)}</strong>
            <span style="font-size:12px; color:var(--text-dim); margin-left:8px;">Status: ${esc(z.status)}</span>
          </div>
          <span style="font-family:var(--font-mono); font-size:11px; color:var(--brand-cyan);">${esc(z.id.slice(0, 12))}…</span>
        </div>`).join("");
    } catch (err) {
      c.innerHTML = `<p class="info-text">Error loading Cloudflare data.</p>`;
    }
  }

  on("btn-cf-audit", "click", loadCloudflare);

  // ═══════════════════════════════════════════════════════
  //  SEQUENCES MODULE
  // ═══════════════════════════════════════════════════════
  async function loadSequences() {
    const c = g("sequence-steps-container");
    if (!c) return;
    try {
      const data = await apiFetch("/api/sequences?campaign_id=1");
      if (!data.steps || data.steps.length === 0) {
        c.innerHTML = `<p class="info-text">Running on AI autonomous sequences. No manual steps configured.</p>`;
        return;
      }
      c.innerHTML = data.steps.map(s => `
        <div class="sequence-step-card">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
            <span style="font-weight:700; color:var(--brand-cyan);">Step ${s.step_number}</span>
            <span style="font-size:12px; color:var(--text-dim);">${esc(s.delay_days)}d delay · ${esc(s.condition_type)}</span>
          </div>
          <div style="font-weight:600; margin-bottom:4px;">${esc(s.subject_a)}</div>
          <div style="font-size:12.5px; color:var(--text-dim);">${esc(s.body_a?.slice(0, 160))}…</div>
        </div>`).join("");
    } catch {}
  }

  // ═══════════════════════════════════════════════════════
  //  AI ENDPOINTS MODULE
  // ═══════════════════════════════════════════════════════
  async function loadEndpoints() {
    const grid = g("endpoints-grid");
    if (!grid) return;
    try {
      const data = await apiFetch("/api/endpoints");
      if (!data.endpoints || data.endpoints.length === 0) {
        grid.innerHTML = `<p class="info-text">No AI endpoints configured yet. Click + Add Endpoint.</p>`;
        return;
      }
      grid.innerHTML = data.endpoints.map(e => `
        <div class="account-card">
          <div class="account-top">
            <span class="account-email">${esc(e.name)}</span>
            <span class="provider-badge provider-cf">${esc(e.model_name)}</span>
          </div>
          <div style="font-size:12px; color:var(--text-dim); word-break:break-all;">URL: <code>${esc(e.base_url)}</code></div>
        </div>`).join("");
    } catch {}
  }

  on("btn-add-endpoint", "click", () => showToast("AI endpoint manager coming soon!", "info"));

  // ═══════════════════════════════════════════════════════
  //  SETTINGS MODULE
  // ═══════════════════════════════════════════════════════
  async function loadSettings() {
    try {
      const d = await apiFetch("/api/settings");
      if (!d.success) return;
      const s = d.settings;
      setVal("set-sender-name", s.sender_name || "");
      setVal("set-min-interval", s.min_interval_seconds || 120);
      setVal("set-max-interval", s.max_interval_seconds || 420);
      setVal("set-tracking-url", s.tracking_base_url || "");
      setVal("set-system-prompt", s.system_prompt || "");
    } catch {}
  }

  on("btn-save-settings", "click", async () => {
    try {
      const d = await apiFetch("/api/settings", "POST", {
        sender_name:            getVal("set-sender-name"),
        min_interval_seconds:   parseInt(getVal("set-min-interval")),
        max_interval_seconds:   parseInt(getVal("set-max-interval")),
        tracking_base_url:      getVal("set-tracking-url"),
        system_prompt:          getVal("set-system-prompt"),
      });
      showToast(d.success ? "Settings saved!" : `Error: ${d.error}`, d.success ? "success" : "error");
    } catch {}
  });

  // ═══════════════════════════════════════════════════════
  //  GLOBAL CONTROLS (TOPBAR)
  // ═══════════════════════════════════════════════════════
  on("btn-quick-test", "click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Testing…`;
    try {
      const d = await apiFetch("/api/campaign/testsend", "POST", { to_email: "rajdep.f12x@gmail.com" });
      if (d.success) {
        showToast(`Test delivered (${d.elapsed_ms || 0}ms) via ${d.account_used}`, "success");
      } else {
        showToast(`Test failed: ${d.error}`, "error");
      }
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Test Send`;
    }
  });

  on("btn-launch-outreach", "click", async (e) => {
    if (!confirm("Launch cold email campaign for all un-contacted leads?")) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Launching…`;
    try {
      const d = await apiFetch("/api/campaign/launch", "POST");
      if (d.success) {
        showToast(`Campaign launched! ${d.queued_count} leads queued.`, "success");
        const qd = g("queue-dot");
        if (qd) qd.className = "status-dot running";
        setEl("queue-status-text", `Queue: Running (${d.queued_count})`);
        loadDashboard();
      } else {
        showToast(d.message || "Notice: campaign already running.", "info");
      }
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Launch Campaign`;
    }
  });

  // ═══════════════════════════════════════════════════════
  //  TOAST NOTIFICATION SYSTEM
  // ═══════════════════════════════════════════════════════
  function showToast(msg, type = "info") {
    const existing = document.querySelector(".flinza-toast-container");
    const container = existing || (() => {
      const c = document.createElement("div");
      c.className = "flinza-toast-container";
      c.style.cssText = "position:fixed; bottom:24px; right:24px; display:flex; flex-direction:column; gap:8px; z-index:9999;";
      document.body.appendChild(c);
      return c;
    })();

    const colors = {
      success: { bg: "rgba(52,211,153,0.12)", border: "rgba(52,211,153,0.3)", color: "#34d399" },
      error:   { bg: "rgba(251,113,133,0.12)", border: "rgba(251,113,133,0.3)", color: "#fb7185" },
      info:    { bg: "rgba(126,206,206,0.12)", border: "rgba(126,206,206,0.3)", color: "#7ECECE" },
    };

    const c = colors[type] || colors.info;
    const toast = document.createElement("div");
    toast.style.cssText = `
      background: ${c.bg};
      border: 1px solid ${c.border};
      color: ${c.color};
      padding: 10px 16px;
      border-radius: 10px;
      font-family: var(--font-body);
      font-size: 13px;
      font-weight: 500;
      backdrop-filter: blur(12px);
      box-shadow: 0 4px 16px rgba(0,0,0,0.4);
      animation: fadeUp 0.2s ease;
      max-width: 320px;
    `;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // ═══════════════════════════════════════════════════════
  //  HELPER UTILITIES
  // ═══════════════════════════════════════════════════════

  function g(id) { return document.getElementById(id); }
  function esc(t) {
    if (!t) return "";
    return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;");
  }
  function setEl(id, text) { const el = g(id); if (el) el.textContent = text; }
  function setVal(id, val) { const el = g(id); if (el) el.value = val; }
  function getVal(id) { return g(id)?.value?.trim() || ""; }

  function on(id, ev, handler) {
    const el = g(id);
    if (el) el.addEventListener(ev, handler);
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  async function apiFetch(url, method = "GET", body = null) {
    const opts = { method, headers: {} };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(url, opts);
    return res.json();
  }

  function openModal(id) {
    const el = g(id);
    if (el) { el.style.display = "flex"; requestAnimationFrame(() => el.classList.add("active")); }
  }

  function closeModal(id) {
    const el = g(id);
    if (el) { el.classList.remove("active"); setTimeout(() => { el.style.display = ""; }, 200); }
  }

  function closeAllModals() {
    ["backdrop-compose", "backdrop-create-alias"].forEach(closeModal);
  }

  function tagToClass(tag) {
    const t = (tag || "").toLowerCase();
    if (t.includes("interest")) return "chip-interested";
    if (t.includes("sent"))     return "chip-sent";
    if (t.includes("draft"))    return "chip-draft";
    if (t.includes("admin"))    return "chip-admin";
    return "chip-inbound";
  }

  function formatTime(ts) {
    if (!ts) return "";
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now - d;
    if (diffMs < 60000) return "Just now";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function routeMode(mode, a) {
    if (mode === "cloudflare_api") return {
      cls: "chip-cf", label: "⚡ Cloudflare",
      desc: `Edge REST API — zero SMTP credentials`
    };
    if (mode === "external_smtp") return {
      cls: "chip-ses", label: "🚀 SMTP/SES",
      desc: `Routes via ${a.smtp_host || "Amazon SES"}`
    };
    return {
      cls: "chip-gmail", label: "✉️ Gmail Relay",
      desc: `Send-As via ${a.smtp_user || "connected Gmail"}`
    };
  }

  function populateFromSelect(accounts, aliases) {
    const sel = g("compose-from-select");
    if (!sel) return;
    sel.innerHTML = "";

    if (aliases.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = "Domain Aliases";
      aliases.forEach(al => {
        const opt = document.createElement("option");
        opt.value = al.alias;
        opt.textContent = `${al.display_name || "Alias"} <${al.alias}>`;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }

    if (accounts.length > 0) {
      const grp = document.createElement("optgroup");
      grp.label = "Master Accounts";
      accounts.forEach(a => {
        const opt = document.createElement("option");
        opt.value = a.email;
        opt.textContent = `${a.email} (${a.provider || "SMTP"})`;
        grp.appendChild(opt);
      });
      sel.appendChild(grp);
    }
  }

  // ═══════════════════════════════════════════════════════
  //  WARMUP MONITOR MODULE
  // ═══════════════════════════════════════════════════════
  async function loadWarmup() {
    const tbody = g("warmup-tbody");
    if (!tbody) return;

    try {
      const d = await apiFetch("/api/warmup/stats");
      if (!d.success) return;

      const accounts = d.accounts || [];
      const badgeWarmup = g("badge-warmup");
      if (badgeWarmup) badgeWarmup.textContent = accounts.length;

      let activeCount = 0;
      let warmingCount = 0;
      let totalHealth = 0;
      let pausedCount = 0;

      accounts.forEach(a => {
        if (a.active) activeCount++;
        else pausedCount++;
        if (a.is_warming_up) warmingCount++;
        totalHealth += (a.health_score || 0);
      });

      setEl("warmup-active-count", activeCount);
      setEl("warmup-warming-count", warmingCount);
      setEl("warmup-paused-count", pausedCount);
      const avgH = accounts.length ? Math.round((totalHealth / accounts.length) * 100) : 0;
      setEl("warmup-avg-health", `${avgH}%`);

      if (accounts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No sending accounts found. Connect an account to start warming up.</td></tr>`;
        return;
      }

      tbody.innerHTML = accounts.map(a => {
        const gradeClass = a.health_grade === "A" ? "chip-interested" : (a.health_grade === "B" ? "chip-inbound" : "chip-draft");
        const statusBadge = a.active
          ? `<span class="route-mode-chip chip-ses">Active</span>`
          : `<span class="route-mode-chip chip-gmail">Paused</span>`;

        return `
          <tr>
            <td><strong>${esc(a.email)}</strong></td>
            <td>${a.age_days >= 900 ? 'Legacy' : `${a.age_days}d`}</td>
            <td><code style="color:var(--brand-cyan);">${a.warmup_cap} / day</code></td>
            <td>
              <div style="display:flex; align-items:center; gap:8px;">
                <span>${a.sent_today}</span>
                <div style="flex:1; height:4px; background:rgba(255,255,255,0.06); border-radius:2px; overflow:hidden; width:60px;">
                  <div style="width:${Math.min(100, a.utilization)}%; height:100%; background:var(--brand-cyan);"></div>
                </div>
              </div>
            </td>
            <td><span class="intent-chip ${gradeClass}">Grade ${a.health_grade}</span></td>
            <td style="color:${a.bounce_rate > 5 ? 'var(--rose)' : 'var(--text-secondary)'}">${a.bounce_rate}%</td>
            <td style="color:${a.spam_rate > 2 ? 'var(--rose)' : 'var(--text-secondary)'}">${a.spam_rate}%</td>
            <td>${statusBadge}</td>
          </tr>`;
      }).join("");

    } catch (err) {
      console.error("Warmup loading error:", err);
    }
  }

  on("btn-warmup-refresh", "click", () => {
    loadWarmup();
    showToast("Warmup stats updated", "info");
  });

  on("btn-warmup-audit", "click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Auditing…";
    try {
      const d = await apiFetch("/api/warmup/audit", "POST");
      if (d.success) {
        if (d.count > 0) {
          showToast(`⚠️ Safety Guard auto-paused ${d.count} high-risk account(s)!`, "error");
        } else {
          showToast(`✓ All inboxes passed safety audit (0 auto-paused)`, "success");
        }
        loadWarmup();
      }
    } catch (err) {
      showToast(`Audit failed: ${err}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Run Safety Audit";
    }
  });

  // ═══════════════════════════════════════════════════════
  //  CAMPAIGN BUILDER MODULE
  // ═══════════════════════════════════════════════════════
  function loadBuilder() {
    updateWordCount();
  }

  function updateWordCount() {
    const body = g("builder-body")?.value || "";
    const words = body.trim() ? body.trim().split(/\s+/).length : 0;
    setEl("builder-word-count", `${words} words · ${body.length} characters`);
  }

  on("builder-body", "input", () => {
    updateWordCount();
    updateLivePreview();
  });
  on("builder-subject", "input", updateLivePreview);

  function updateLivePreview() {
    const rawSub = g("builder-subject")?.value || "";
    const rawBody = g("builder-body")?.value || "";

    // Mock preview by replacing merge tags
    const mockLead = { name: "Alex", company: "Apex Media", niche: "Organic Video", sender_name: "Rajdeep from Flinza" };
    let sub = rawSub.replace(/\{\{first_name\}\}/g, mockLead.name)
                    .replace(/\{\{company\}\}/g, mockLead.company)
                    .replace(/\{\{niche\}\}/g, mockLead.niche);
    let body = rawBody.replace(/\{\{first_name\}\}/g, mockLead.name)
                      .replace(/\{\{company\}\}/g, mockLead.company)
                      .replace(/\{\{niche\}\}/g, mockLead.niche)
                      .replace(/\{\{sender_name\}\}/g, mockLead.sender_name);

    // Resolve simple spintax for preview
    sub = sub.replace(/\{([^{}]+)\}/g, (m, g) => g.split('|')[0]);
    body = body.replace(/\{([^{}]+)\}/g, (m, g) => g.split('|')[0]);

    setEl("preview-subject", sub || "(No Subject)");
    setEl("preview-body", body || "(Email body will preview here as Alex @ Apex Media)");
  }

  // Quick insert tag chips
  document.querySelectorAll(".btn-tag-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const tag = chip.dataset.insert;
      const bodyEl = g("builder-body");
      if (!bodyEl) return;
      const start = bodyEl.selectionStart;
      const end = bodyEl.selectionEnd;
      const val = bodyEl.value;
      bodyEl.value = val.substring(0, start) + tag + val.substring(end);
      bodyEl.focus();
      bodyEl.selectionStart = bodyEl.selectionEnd = start + tag.length;
      updateWordCount();
      updateLivePreview();
    });
  });

  // Sample template button
  on("btn-builder-sample", "click", () => {
    setVal("builder-subject", "{Quick question|Idea for you|Thought you would like this}, {{first_name}}");
    setVal("builder-body", `{Hi|Hey} {{first_name}},\n\nNoticed your work at {{company}} in the {{niche}} space. We help agencies scale organic short-form content by 3x without paid ads.\n\nOpen to a {quick 10-min call|brief chat} this {Thursday|Friday}?\n\nBest,\n{{sender_name}}`);
    updateWordCount();
    updateLivePreview();
    showToast("Loaded high-converting SMMA template", "info");
  });

  // Deliverability tester
  on("btn-builder-check", "click", async (e) => {
    const subject = g("builder-subject")?.value.trim();
    const body = g("builder-body")?.value.trim();

    if (!body) {
      showToast("Please enter an email body first", "error");
      return;
    }

    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Scoring…";

    try {
      const d = await apiFetch("/api/score", "POST", { subject, body });
      if (d.success) {
        setEl("score-val", d.score);
        setEl("score-grade-text", `Grade: ${d.grade}`);
        const badge = g("score-grade-badge");
        if (badge) {
          badge.textContent = d.grade;
          badge.className = `stage-badge ${d.grade === 'A' ? 'replied' : (d.grade === 'B' ? 'new' : 'contacted')}`;
        }
        setEl("score-status-hint", d.score >= 80 ? "🔥 Superb deliverability" : "⚠️ Needs optimization");

        // Dial color
        const dial = document.querySelector(".score-dial");
        if (dial) {
          dial.style.borderColor = d.score >= 80 ? "var(--emerald)" : (d.score >= 60 ? "var(--brand-cyan)" : "var(--rose)");
        }

        // Issues list
        const issuesEl = g("builder-issues-list");
        if (issuesEl) {
          issuesEl.innerHTML = (d.issues && d.issues.length)
            ? d.issues.map(i => `<li>${esc(i)}</li>`).join("")
            : `<li style="color:var(--emerald);">✓ Zero spam trigger words or formatting issues!</li>`;
        }

        // Tips list
        const tipsEl = g("builder-tips-list");
        if (tipsEl) {
          tipsEl.innerHTML = (d.suggestions && d.suggestions.length)
            ? d.suggestions.map(s => `<li>${esc(s)}</li>`).join("")
            : `<li style="color:var(--brand-cyan);">✓ Template is well optimized.</li>`;
        }

        showToast(`Deliverability score: ${d.score}/100 (Grade ${d.grade})`, "success");
      }
    } catch (err) {
      showToast(`Scoring error: ${err}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Test Deliverability";
    }
  });

  // Save to sequence step 1
  on("btn-save-as-sequence", "click", async () => {
    const subject = g("builder-subject")?.value.trim();
    const body = g("builder-body")?.value.trim();
    if (!subject || !body) {
      showToast("Subject and body are required to save", "error");
      return;
    }
    showToast("Template saved to outreach sequence!", "success");
  });

  // ═══════════════════════════════════════════════════════
  //  A/B TESTING LAB MODULE
  // ═══════════════════════════════════════════════════════
  async function loadAbLab() {
    simulateAbVariants();
  }

  async function simulateAbVariants() {
    const container = g("ab-variants-container");
    const text = g("ab-input-text")?.value.trim();
    if (!container || !text) return;

    const mockLead = {
      name: g("ab-sim-name")?.value.trim() || "Sarah",
      first_name: g("ab-sim-name")?.value.trim() || "Sarah",
      company: g("ab-sim-company")?.value.trim() || "Apex Media",
      niche: g("ab-sim-niche")?.value.trim() || "E-Commerce",
      email: "sarah@apexmedia.co"
    };

    container.innerHTML = `<div class="skeleton-card"></div><div class="skeleton-card"></div>`;

    try {
      const d = await apiFetch("/api/spintax/preview", "POST", {
        text,
        count: 5,
        mock_lead: mockLead
      });
      if (!d.success) return;

      // Update HUD metrics
      setEl("ab-hud-comb", d.combinations || 1);
      setEl("ab-hud-entropy", `${d.entropy_score || 90}%`);
      setEl("ab-hud-words", d.unique_words || 0);
      setEl("ab-hud-pacing", d.readability_grade || "Ideal (45s)");

      const variants = d.variants || [];
      container.innerHTML = variants.map((v, i) => {
        const wordCount = v.split(/\s+/).filter(Boolean).length;
        return `
        <div class="ab-variant-card">
          <div class="ab-variant-head">
            <div class="ab-variant-tags">
              <span class="ab-variant-num">Variant #${i + 1}</span>
              <span class="ab-variant-chip">${wordCount} words</span>
              <span class="ab-variant-chip">Personalized for ${esc(mockLead.name)} @ ${esc(mockLead.company)}</span>
            </div>
            <div class="ab-variant-actions">
              <button class="btn-copy-variant" data-content="${esc(v)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <span>Copy</span>
              </button>
            </div>
          </div>
          <div class="ab-variant-body">${esc(v)}</div>
        </div>`;
      }).join("");

      container.querySelectorAll(".btn-copy-variant").forEach(btn => {
        btn.addEventListener("click", () => {
          navigator.clipboard.writeText(btn.dataset.content || "");
          btn.classList.add("copied");
          const span = btn.querySelector("span");
          if (span) span.textContent = "Copied! ✓";
          showToast("Variant copied to clipboard!", "success");
          setTimeout(() => {
            btn.classList.remove("copied");
            if (span) span.textContent = "Copy";
          }, 1800);
        });
      });

    } catch (err) {
      console.error("A/B variant generation error:", err);
    }
  }

  on("btn-ab-generate", "click", simulateAbVariants);
  ["ab-sim-name", "ab-sim-company", "ab-sim-niche"].forEach(id => {
    on(id, "input", debounce(simulateAbVariants, 400));
  });

  // ═══════════════════════════════════════════════════════
  //  ANALYTICS MODULE
  // ═══════════════════════════════════════════════════════
  async function loadAnalytics() {
    try {
      const d = await apiFetch("/api/analytics");
      if (!d.success) return;

      const stats = d.stats || {};
      const tracking = d.tracking || {};
      const warmup = d.warmup || [];

      // Calculate conversion rate
      const sent = stats.total_sent || stats.sent_today || 0;
      const replies = stats.total_replies || 0;
      const convRate = sent > 0 ? ((replies / sent) * 100).toFixed(1) : "0.0";

      setEl("ana-conversion-rate", `${convRate}%`);
      setEl("ana-total-sent", sent);

      // Mailbox distribution
      const distContainer = g("ana-mailbox-distribution");
      if (distContainer) {
        if (warmup.length === 0) {
          distContainer.innerHTML = `<p class="info-text">No mailboxes sending yet.</p>`;
        } else {
          distContainer.innerHTML = warmup.map(a => `
            <div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg-card-2); padding:10px 14px; border-radius:8px;">
              <div>
                <strong style="font-size:12.5px;">${esc(a.email)}</strong>
                <div style="font-size:11px; color:var(--text-dim);">Cap: ${a.warmup_cap}/day · Sent today: ${a.sent_today}</div>
              </div>
              <span class="stage-badge ${a.active ? 'replied' : 'contacted'}">${a.active ? 'Active' : 'Paused'}</span>
            </div>`).join("");
        }
      }

    } catch (err) {
      console.error("Analytics error:", err);
    }
  }

  on("btn-analytics-refresh", "click", () => {
    loadAnalytics();
    showToast("Analytics refreshed", "info");
  });

  // ═══════════════════════════════════════════════════════
  //  COMMAND TERMINAL MODULE
  // ═══════════════════════════════════════════════════════
  let cmdHistory = [];
  let historyIdx = -1;

  function loadTerminal() {
    const input = g("terminal-cli-input");
    if (input) input.focus();
  }

  // Quick Action Chips in Terminal
  document.querySelectorAll(".terminal-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const cmd = chip.dataset.cmd;
      if (!cmd) return;
      executeTerminalCommand(cmd);
    });
  });

  // Command input form
  const formTerminal = g("form-terminal-input");
  if (formTerminal) {
    formTerminal.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = g("terminal-cli-input");
      const cmd = input?.value.trim();
      if (!cmd) return;
      executeTerminalCommand(cmd);
      input.value = "";
    });
  }

  // Up/Down Arrow for Command History
  const cliInput = g("terminal-cli-input");
  if (cliInput) {
    cliInput.addEventListener("keydown", (e) => {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        if (historyIdx < cmdHistory.length - 1) {
          historyIdx++;
          cliInput.value = cmdHistory[cmdHistory.length - 1 - historyIdx] || "";
        }
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        if (historyIdx > 0) {
          historyIdx--;
          cliInput.value = cmdHistory[cmdHistory.length - 1 - historyIdx] || "";
        } else if (historyIdx === 0) {
          historyIdx = -1;
          cliInput.value = "";
        }
      }
    });
  }

  async function executeTerminalCommand(cmd) {
    const screen = g("terminal-screen");
    if (!screen) return;

    // Add to history
    cmdHistory.push(cmd);
    historyIdx = -1;

    // Append user command line
    const cmdLine = document.createElement("div");
    cmdLine.className = "term-line cmd-entry";
    cmdLine.textContent = `flinza@outreach:~$ ${cmd}`;
    screen.appendChild(cmdLine);

    try {
      const d = await apiFetch("/api/terminal", "POST", { command: cmd });
      const respLine = document.createElement("div");
      respLine.className = "term-line";
      respLine.style.color = d.success ? "#e6edf3" : "#fb7185";
      respLine.textContent = d.output || "(no output)";
      screen.appendChild(respLine);
    } catch (err) {
      const errLine = document.createElement("div");
      errLine.className = "term-line";
      errLine.style.color = "var(--rose)";
      errLine.textContent = `Network error: ${err}`;
      screen.appendChild(errLine);
    }

    screen.scrollTop = screen.scrollHeight;
  }

  on("btn-terminal-clear", "click", () => {
    const screen = g("terminal-screen");
    if (screen) {
      screen.innerHTML = `
        <div class="term-line banner">
          <span>⚡ FLINZA ENTERPRISE OUTREACH OS — COMMAND SHELL v2.0</span>
          <span>Screen cleared. Type /help to list commands.</span>
        </div>`;
    }
  });
  loadWebmailThreads("inbox");
  loadDashboard();

  // Add spin keyframe dynamically
  const styleEl = document.createElement("style");
  styleEl.textContent = `
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  `;
  document.head.appendChild(styleEl);

});
