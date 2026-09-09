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
        showWebhookMenu: false,
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
                    this.loadTunnelStatus();
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
                    this.loadTunnelStatus();
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

        _gen8Id() {
            if (window.crypto && window.crypto.getRandomValues) {
                return Array.from(window.crypto.getRandomValues(new Uint8Array(4)))
                    .map(b => b.toString(16).padStart(2, '0')).join('');
            }
            return Math.random().toString(16).substring(2, 10);
        },

        async selectProject(id) {
            this.loading = true;
            try {
                const proj = await this.api('GET', `/${id}`);
                if (proj.upstreams) {
                    proj.upstreams = proj.upstreams.map(u => {
                        const uid = u.upstream_id || u.id || this._gen8Id();
                        const pname = u.project_name || u.name || '';
                        return {
                            ...u,
                            project_name: pname,
                            name: pname,
                            upstream_id: uid,
                            id: uid,
                        };
                    });
                }
                const upIdMap = {};
                (proj.upstreams || []).forEach(u => {
                    const uid = u.upstream_id || u.id;
                    if (uid) upIdMap[uid] = u;
                });

                if (proj.forwards) {
                    proj.forwards = proj.forwards.map(f => {
                        let upId = f.upstream_id || '';
                        let upName = f.project_name || f.upstream || '';
                        if (!upId && upName) {
                            const match = (proj.upstreams || []).find(u => (u.project_name || u.name) === upName);
                            if (match) upId = match.upstream_id || match.id;
                        }
                        if (!upId) {
                            const src = (f.from || f.from_path || '').toLowerCase();
                            for (const u of (proj.upstreams || [])) {
                                const cleanName = (u.project_name || u.name || '').toLowerCase().replace(/^[._]/, '');
                                if (cleanName && (src.includes(cleanName) || src.includes((u.project_name || u.name).toLowerCase()))) {
                                    upId = u.upstream_id || u.id;
                                    upName = u.project_name || u.name;
                                    break;
                                }
                            }
                        }
                        if (upId && upIdMap[upId] && !upName) {
                            upName = upIdMap[upId].project_name || upIdMap[upId].name;
                        }
                        const fid = f.forward_id || f.id || this._gen8Id();
                        return {
                            forward_id: fid,
                            id: fid,
                            from: f.from || f.from_path || '',
                            to: f.to || f.to_path || '',
                            upstream_id: upId,
                            project_name: upName,
                            upstream: upName,
                            enabled: f.enabled !== false,
                        };
                    });
                }
                if (!proj.webhook) {
                    proj.webhook = { enabled: false, secret: '', use_tunnel: this.tunnel.funnel_active, tunnel_url: '' };
                } else {
                    if (proj.webhook.use_tunnel === undefined) proj.webhook.use_tunnel = this.tunnel.funnel_active;
                    if (proj.webhook.tunnel_url === undefined) proj.webhook.tunnel_url = '';
                }
                this.activeProject = proj;
                this.activeProjectId = id;
                this.showWebhookMenu = false;
            } catch (e) { console.error('Load project:', e); }
            this.loading = false;
        },

        async saveProject() {
            if (!this.activeProject) return;
            try {
                const upMap = {};
                (this.activeProject.upstreams || []).forEach(u => {
                    const uid = u.upstream_id || u.id;
                    if (uid) upMap[uid] = u.project_name || u.name || '';
                });

                const payload = {
                    upstreams: this.activeProject.upstreams.map(u => ({
                        project_name: u.project_name || u.name || '',
                        upstream_id: u.upstream_id || u.id || this._gen8Id(),
                        pull: u.pull !== false,
                        sparse: u.sparse !== false,
                        blobless: u.blobless !== false,
                        branch: u.branch || 'main',
                        path: u.path || '',
                        url: u.url || '',
                    })),
                    forwards: this.activeProject.forwards.map(f => {
                        const uid = f.upstream_id || '';
                        const resolvedName = (uid && upMap[uid]) ? upMap[uid] : (f.project_name || f.upstream || '');
                        return {
                            enabled: f.enabled !== false,
                            project_name: resolvedName,
                            upstream_id: uid,
                            forward_id: f.forward_id || f.id || this._gen8Id(),
                            from: f.from || '',
                            to: f.to || '',
                        };
                    }),
                    git: this.activeProject.git,
                    schedule: this.activeProject.schedule,
                    webhook: this.activeProject.webhook,
                };
                const result = await this.api('PUT', `/${this.activeProjectId}`, payload);
                if (result.upstreams) {
                    this.activeProject.upstreams = result.upstreams.map(u => {
                        const uid = u.upstream_id || u.id || this._gen8Id();
                        const pname = u.project_name || u.name || '';
                        return {
                            ...u,
                            project_name: pname,
                            name: pname,
                            upstream_id: uid,
                            id: uid,
                        };
                    });
                }
                if (result.forwards) {
                    const upIdMap = {};
                    (this.activeProject.upstreams || []).forEach(u => {
                        const uid = u.upstream_id || u.id;
                        if (uid) upIdMap[uid] = u;
                    });
                    this.activeProject.forwards = result.forwards.map(f => {
                        const upId = f.upstream_id || '';
                        const upName = f.project_name || f.upstream || (upIdMap[upId] ? (upIdMap[upId].project_name || upIdMap[upId].name) : '');
                        const fid = f.forward_id || f.id || this._gen8Id();
                        return {
                            forward_id: fid,
                            id: fid,
                            from: f.from || f.from_path || '',
                            to: f.to || f.to_path || '',
                            upstream_id: upId,
                            project_name: upName,
                            upstream: upName,
                            enabled: f.enabled !== false,
                        };
                    });
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
            const uid = this._gen8Id();
            this.activeProject.upstreams.push({
                project_name: '',
                name: '',
                upstream_id: uid,
                id: uid,
                path: '', url: '', branch: 'main', pull: true, sparse: true, blobless: true,
            });
        },
        removeUpstream(i) {
            const removed = this.activeProject.upstreams.splice(i, 1)[0];
            // Clear upstream_id from forwards if their upstream was deleted
            if (removed) {
                const remId = removed.upstream_id || removed.id;
                (this.activeProject.forwards || []).forEach(f => {
                    if (f.upstream_id === remId) {
                        f.upstream_id = '';
                    }
                });
            }
        },
        addForward(upstreamIdOrName = null) {
            if (!this.activeProject) return;
            const upstreams = this.activeProject.upstreams || [];
            let matchUp = null;
            if (upstreamIdOrName) {
                matchUp = upstreams.find(u =>
                    (u.upstream_id && u.upstream_id === upstreamIdOrName) ||
                    (u.id && u.id === upstreamIdOrName) ||
                    (u.project_name && u.project_name === upstreamIdOrName) ||
                    (u.name && u.name === upstreamIdOrName)
                );
            } else if (upstreams.length === 1) {
                matchUp = upstreams[0];
            }

            let upId = matchUp ? (matchUp.upstream_id || matchUp.id || '') : '';
            let upName = matchUp ? (matchUp.project_name || matchUp.name || '') : '';
            let defaultFrom = '';
            if (matchUp && matchUp.path) {
                defaultFrom = matchUp.path.endsWith('/') ? matchUp.path : matchUp.path + '/';
            }

            const fid = this._gen8Id();
            this.activeProject.forwards.push({
                forward_id: fid,
                id: fid,
                upstream_id: upId,
                project_name: upName,
                upstream: upName,
                from: defaultFrom,
                to: '',
                enabled: true,
            });
        },
        onForwardUpstreamChange(idx) {
            const f = this.activeProject.forwards[idx];
            if (!f) return;
            const upstreams = this.activeProject.upstreams || [];
            const u = upstreams.find(up =>
                (up.upstream_id && up.upstream_id === f.upstream_id) ||
                (up.id && up.id === f.upstream_id) ||
                (up.project_name && up.project_name === f.upstream_id) ||
                (up.name && up.name === f.upstream_id)
            );
            if (u) {
                f.upstream_id = u.upstream_id || u.id;
                f.project_name = u.project_name || u.name;
                f.upstream = f.project_name;
                if (u.path) {
                    const base = u.path.endsWith('/') ? u.path : u.path + '/';
                    const wasOtherUpstream = upstreams.some(
                        other => ((other.upstream_id !== u.upstream_id && other.id !== u.id)) && other.path && f.from.startsWith(other.path)
                    );
                    if (!f.from || wasOtherUpstream) {
                        let sub = '';
                        if (wasOtherUpstream) {
                            const prevUp = upstreams.find(other => f.from.startsWith(other.path));
                            if (prevUp && prevUp.path) {
                                sub = f.from.slice(prevUp.path.length).replace(/^\/+/, '');
                            }
                        }
                        f.from = sub ? `${base}${sub}` : base;
                    }
                }
            } else {
                f.upstream_id = '';
                f.project_name = '';
                f.upstream = '';
            }
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
            const useTunnel = (this.activeProject?.webhook?.use_tunnel ?? true) && this.tunnel?.funnel_active;
            const customUrl = this.activeProject?.webhook?.tunnel_url;
            if (useTunnel || customUrl) {
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
        async toggleTunnel() {
            if (!this.activeProject) return;
            if (!this.activeProject.webhook) this.activeProject.webhook = { enabled: false, secret: '', use_tunnel: false, tunnel_url: '' };

            const shouldEnable = !this.tunnel.funnel_active;
            this.showToast(shouldEnable ? 'Starting Tailscale Funnel...' : 'Stopping Tailscale Funnel...');
            try {
                const res = await fetch('/api/system/tunnel/funnel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enable: shouldEnable }),
                });
                const data = await res.json();
                if (res.ok) {
                    if (data.tunnel) {
                        this.tunnel = data.tunnel;
                    } else {
                        await this.loadTunnelStatus();
                    }
                    this.activeProject.webhook.use_tunnel = this.tunnel.funnel_active;
                    if (this.tunnel.funnel_active) {
                        this.showToast(`Tailscale Funnel Active: ${this.tunnel.domain}`);
                    } else {
                        this.showToast('Tailscale Funnel Stopped');
                    }
                } else {
                    this.showToast(data.detail || 'Failed to toggle Funnel');
                }
            } catch (e) {
                console.error('Toggle tunnel error:', e);
                this.showToast('Network error toggling Funnel');
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

        // ── Grouped Forwards (by upstream) ───────────────────────────
        get groupedForwards() {
            if (!this.activeProject) return {};
            const groups = {};
            const upstreams = this.activeProject.upstreams || [];
            const upMap = {};
            upstreams.forEach(u => {
                const uid = u.upstream_id || u.id;
                if (uid) upMap[uid] = u;
            });

            (this.activeProject.forwards || []).forEach((f, i) => {
                let cat = '';
                // 1. Match by upstream_id
                if (f.upstream_id && upMap[f.upstream_id]) {
                    cat = upMap[f.upstream_id].project_name || upMap[f.upstream_id].name;
                }
                // 2. Match by upstream name / project_name
                const targetName = f.project_name || f.upstream;
                if (!cat && targetName) {
                    const found = upstreams.find(u => (u.project_name === targetName || u.name === targetName));
                    if (found) {
                        cat = found.project_name || found.name;
                        if (!f.upstream_id) f.upstream_id = found.upstream_id || found.id;
                    } else {
                        cat = targetName;
                    }
                }
                // 3. Fallback to path matching
                if (!cat) {
                    const src = (f.from || '').toLowerCase();
                    for (const u of upstreams) {
                        const uname = u.project_name || u.name || '';
                        const cleanName = uname.toLowerCase().replace(/^[._]/, '');
                        if (uname && (src.includes(cleanName) || src.includes(uname.toLowerCase()))) {
                            cat = uname;
                            if (!f.upstream_id) f.upstream_id = u.upstream_id || u.id;
                            break;
                        }
                    }
                }
                if (!cat) cat = 'other';
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
