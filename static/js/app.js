/**
 * GitManager — AlpineJS Application
 * Multi-project upstream sync management.
 */

const THEMES = [
    { id: 'matrix',      name: 'Matrix'       },
    { id: 'matte-black', name: 'Matte Black'  },
    { id: 'black-brown', name: 'Black Brown'  },
    { id: 'jam-black',   name: 'Jam Black'    },
    { id: 'jam-navy',    name: 'Jam Navy'     },
    { id: 'pure-white',  name: 'Pure White'   },
    { id: 'matte-white', name: 'Matte White'  },
    { id: 'cream',       name: 'Cream'        },
    { id: 'block-white', name: 'Block White'  },
];

document.addEventListener('alpine:init', () => {

    Alpine.data('gitmanager', () => ({

        // ── Auth State ────────────────────────────────────────────────
        authReady: false,
        authenticated: false,
        loginUsername: '',
        loginPassword: '',
        loginError: '',

        // ── Project State ─────────────────────────────────────────────
        projects: [],
        activeProjectId: null,
        activeProject: null,
        loading: false,
        showAddProject: false,
        newProject: { name: '', path: '' },

        // ── Theme State ───────────────────────────────────────────────
        themeIndex: 0,
        themes: THEMES,
        get currentThemeName() { return THEMES[this.themeIndex].name; },

        // ── Tunnel State ──────────────────────────────────────────────
        tunnel: {
            installed: false,
            running: false,
            funnel_active: false,
            domain: null,
            funnel_url: null,
            port: 8000,
            error: null,
        },

        // ── Lifecycle ─────────────────────────────────────────────────
        async init() {
            // Restore theme
            const saved = localStorage.getItem('gm-theme');
            if (saved) {
                const idx = THEMES.findIndex(t => t.id === saved);
                if (idx >= 0) this.themeIndex = idx;
            }
            document.documentElement.setAttribute('data-theme', THEMES[this.themeIndex].id);

            // Fetch tunnel status in parallel
            this.loadTunnelStatus();

            // Check auth
            await this.checkAuth();
        },

        // ── Auth ──────────────────────────────────────────────────────
        async checkAuth() {
            try {
                const res = await fetch('/api/auth/check');
                const data = await res.json();
                this.authenticated = data.authenticated;
                if (this.authenticated) {
                    await this.fetchProjects();
                    if (this.projects.length > 0 && !this.activeProjectId) {
                        await this.selectProject(this.projects[0].id);
                    }
                }
            } catch (e) { this.authenticated = false; }
            finally { this.authReady = true; }
        },

        async login() {
            this.loginError = '';
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: this.loginUsername, password: this.loginPassword }),
                });
                if (res.ok) {
                    this.authenticated = true;
                    this.loginUsername = '';
                    this.loginPassword = '';
                    await this.fetchProjects();
                    if (this.projects.length > 0) await this.selectProject(this.projects[0].id);
                } else {
                    this.loginError = 'Invalid credentials';
                }
            } catch (e) { this.loginError = 'Connection error'; }
        },

        async logout() {
            await fetch('/api/auth/logout', { method: 'POST' });
            this.authenticated = false;
            this.activeProject = null;
            this.activeProjectId = null;
            this.projects = [];
        },

        // ── Theme ─────────────────────────────────────────────────────
        cycleTheme() {
            this.themeIndex = (this.themeIndex + 1) % THEMES.length;
            const theme = THEMES[this.themeIndex];
            document.documentElement.setAttribute('data-theme', theme.id);
            localStorage.setItem('gm-theme', theme.id);
        },

        // ── API Helpers ───────────────────────────────────────────────
        async api(method, path, body = null) {
            const opts = { method, headers: { 'Content-Type': 'application/json' } };
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch(`/api/projects${path}`, opts);
            if (res.status === 401) { this.authenticated = false; throw new Error('Session expired'); }
            if (!res.ok && res.status !== 204) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            if (res.status === 204) return null;
            return res.json();
        },

        // ── Projects CRUD ─────────────────────────────────────────────
        async fetchProjects() {
            this.loading = true;
            try { this.projects = await this.api('GET', ''); }
            catch (e) { console.error('Fetch projects:', e); }
            this.loading = false;
        },

        async addProject() {
            if (!this.newProject.name.trim() || !this.newProject.path.trim()) return;
            try {
                const created = await this.api('POST', '', this.newProject);
                this.projects.push(created);
                this.newProject = { name: '', path: '' };
                this.showAddProject = false;
                await this.selectProject(created.id);
            } catch (e) { alert('Failed: ' + e.message); }
        },

        async selectProject(id) {
            this.loading = true;
            try {
                const proj = await this.api('GET', `/${id}`);
                if (proj.forwards) {
                    proj.forwards = proj.forwards.map(f => ({
                        from: f.from || f.from_path || '',
                        to: f.to || f.to_path || '',
                        enabled: f.enabled !== false,
                    }));
                }
                if (!proj.webhook) {
                    proj.webhook = { enabled: false, secret: '', use_tunnel: this.tunnel.funnel_active, tunnel_url: '' };
                } else {
                    if (proj.webhook.use_tunnel === undefined) proj.webhook.use_tunnel = this.tunnel.funnel_active;
                    if (proj.webhook.tunnel_url === undefined) proj.webhook.tunnel_url = '';
                }
                this.activeProject = proj;
                this.activeProjectId = id;
            } catch (e) { console.error('Load project:', e); }
            this.loading = false;
        },

        async saveProject() {
            if (!this.activeProject) return;
            try {
                const payload = {
                    upstreams: this.activeProject.upstreams,
                    forwards: this.activeProject.forwards.map(f => ({
                        from: f.from || '', to: f.to || '', enabled: f.enabled,
                    })),
                    git: this.activeProject.git,
                    schedule: this.activeProject.schedule,
                    webhook: this.activeProject.webhook,
                };
                const result = await this.api('PUT', `/${this.activeProjectId}`, payload);
                if (result.forwards) {
                    result.forwards = result.forwards.map(f => ({
                        from: f.from || f.from_path || '',
                        to: f.to || f.to_path || '',
                        enabled: f.enabled !== false,
                    }));
                }
                if (!result.webhook) {
                    result.webhook = { enabled: false, secret: '' };
                }
                this.activeProject = result;
                this.showToast('Saved');
            } catch (e) { alert('Save failed: ' + e.message); }
        },

        async deleteProject(id) {
            if (!confirm('Delete this project?')) return;
            try {
                await this.api('DELETE', `/${id}`);
                this.projects = this.projects.filter(p => p.id !== id);
                if (this.activeProjectId === id) {
                    this.activeProjectId = null;
                    this.activeProject = null;
                    if (this.projects.length > 0) await this.selectProject(this.projects[0].id);
                }
            } catch (e) { alert('Delete failed: ' + e.message); }
        },

        // ── Worker Control ────────────────────────────────────────────
        async runProject(id) {
            try {
                const res = await this.api('POST', `/${id}/run`);
                this.showToast(res.status === 'started' ? 'Sync started' : 'Already running');
                await this.fetchProjects();
                if (this.activeProject && this.activeProjectId === id) {
                    this.activeProject.status = 'running';
                }
            } catch (e) { alert('Run failed: ' + e.message); }
        },
        async stopProject(id) {
            try {
                await this.api('POST', `/${id}/stop`);
                this.showToast('Stopped');
                await this.fetchProjects();
                if (this.activeProject && this.activeProjectId === id) {
                    this.activeProject.status = 'idle';
                }
            } catch (e) { alert('Stop failed: ' + e.message); }
        },

        // ── Upstream / Forward Management ─────────────────────────────
        addUpstream() {
            if (!this.activeProject) return;
            this.activeProject.upstreams.push({
                name: '', path: '', url: '', branch: 'main', pull: true, sparse: true, blobless: true,
            });
        },
        removeUpstream(i) { this.activeProject.upstreams.splice(i, 1); },
        addForward() {
            if (!this.activeProject) return;
            this.activeProject.forwards.push({ from: '', to: '', enabled: true });
        },
        removeForward(i) { this.activeProject.forwards.splice(i, 1); },

        // ── Webhook & Tunnel Helpers ─────────────────────────────────
        async loadTunnelStatus() {
            try {
                const res = await fetch('/api/system/tunnel');
                if (res.ok) {
                    this.tunnel = await res.json();
                }
            } catch (e) {
                console.warn('Failed to load tunnel status:', e);
            }
        },
        async refreshTunnel() {
            await this.loadTunnelStatus();
            if (this.tunnel.funnel_active) {
                this.showToast(`Tailscale Funnel Active: ${this.tunnel.domain}`);
            } else if (this.tunnel.running) {
                this.showToast('Tailscale is running, but Funnel is inactive');
            } else {
                this.showToast('Tailscale daemon is not active');
            }
        },
        getWebhookUrl(id) {
            if (!id) return '';
            const useTunnel = this.activeProject?.webhook?.use_tunnel;
            const customUrl = this.activeProject?.webhook?.tunnel_url;
            if (useTunnel) {
                const base = customUrl || this.tunnel.funnel_url || (this.tunnel.domain ? `https://${this.tunnel.domain}` : window.location.origin);
                return `${base.replace(/\/+$/, '')}/api/webhooks/${id}`;
            }
            return `${window.location.origin}/api/webhooks/${id}`;
        },
        toggleWebhook() {
            if (!this.activeProject) return;
            if (!this.activeProject.webhook) this.activeProject.webhook = { enabled: false, secret: '', use_tunnel: false, tunnel_url: '' };
            this.activeProject.webhook.enabled = !this.activeProject.webhook.enabled;
        },
        toggleTunnel() {
            if (!this.activeProject) return;
            if (!this.activeProject.webhook) this.activeProject.webhook = { enabled: false, secret: '', use_tunnel: false, tunnel_url: '' };
            this.activeProject.webhook.use_tunnel = !this.activeProject.webhook.use_tunnel;
            if (this.activeProject.webhook.use_tunnel && !this.tunnel.funnel_active) {
                this.loadTunnelStatus();
            }
        },
        copyWebhookUrl(id) {
            const url = this.getWebhookUrl(id);
            if (navigator.clipboard) {
                navigator.clipboard.writeText(url).then(() => {
                    this.showToast('Webhook URL copied');
                }).catch(() => {
                    this.showToast('Copied');
                });
            } else {
                this.showToast('Copied');
            }
        },

        // ── Grouped Forwards (by upstream name) ───────────────────────
        get groupedForwards() {
            if (!this.activeProject) return {};
            const groups = {};
            const upNames = (this.activeProject.upstreams || []).map(u => u.name).filter(Boolean);
            (this.activeProject.forwards || []).forEach((f, i) => {
                let cat = 'other';
                const src = (f.from || '').toLowerCase();
                for (const name of upNames) {
                    const cleanName = name.toLowerCase().replace(/^[._]/, '');
                    if (src.includes(cleanName) || src.includes(name.toLowerCase())) {
                        cat = name;
                        break;
                    }
                }
                if (!groups[cat]) groups[cat] = [];
                groups[cat].push({ ...f, _idx: i });
            });
            return groups;
        },

        // ── Helpers ───────────────────────────────────────────────────
        maskPath(p) { return (p || '').replace(/^\/home\/[^/]+\//, '{~}/'); },

        statusBadge(s) {
            return { idle: 'badge-idle', running: 'badge-running', error: 'badge-error', paused: 'badge-paused' }[s] || 'badge-idle';
        },
        statusIcon(s) { return { idle: '○', running: '●', error: '✗', paused: '⏸' }[s] || '○'; },

        _tt: null, toastMessage: '', toastVisible: false,
        showToast(m) {
            this.toastMessage = m; this.toastVisible = true;
            clearTimeout(this._tt);
            this._tt = setTimeout(() => { this.toastVisible = false; }, 2000);
        },
    }));
});
