# GitManager — Usage Guide

## Table of Contents

1. [First Launch](#1-first-launch)
2. [Creating a Project](#2-creating-a-project)
3. [Adding Upstreams](#3-adding-upstreams)
4. [Defining Path Forwards](#4-defining-path-forwards)
5. [Configuring Git Settings](#5-configuring-git-settings)
6. [Running the Sync Worker](#6-running-the-sync-worker)
7. [Understanding the Toolbar](#7-understanding-the-toolbar)
8. [Data Storage](#8-data-storage)
9. [Environment Variables](#9-environment-variables)

---

## 1. First Launch

Start the server:

```bash
python main.py
```

Open `http://localhost:8000` in your browser. You will see the login page.

> GitManager automatically kills any stale process on port `8000` before starting — no manual cleanup needed if you left a session running in the background.

Enter the credentials you set in `.env`:

```dotenv
GM_USERNAME=admin
GM_PASSWORD=your_password
```

After login, you land directly on the dashboard. Your session is stored as an HMAC-signed cookie that survives server restarts — you will stay logged in until you explicitly click **Exit**.

---

## 2. Creating a Project

Click the **+** button at the top-right of the sidebar.

Fill in:
- **Project Name** — a human-readable label (e.g. `human-skills`)
- **Project Path** — the absolute path to your local Git repository (e.g. `/home/user/human-skills`)

Click **Create**. The project appears in the sidebar and is immediately selected.

> Your project directory must already be a Git repository (`git init` or cloned). GitManager does not initialize Git repos for you.

---

## 3. Adding Upstreams

Click **+ Upstream** in the toolbar. A new empty row appears in the **Upstreams** section.

Fill in each field:

| Field | Description | Example |
|---|---|---|
| **Name** | Identifier for this upstream | `claude-skills` |
| **URL** | GitHub clone URL (optional if path already exists) | `https://github.com/user/repo.git` |
| **Branch** | Which branch to track | `main` or `master` |
| **Path** | Where to clone/pull the upstream repo | `/home/user/.claude-skills` |
| **Toggle** | Enable or disable pulling this upstream | ON |

**Auto-Clone:** If the path does not exist and a URL is provided, GitManager will run `git clone -b <branch> <url> <path>` on the first sync.

**Branch Sync Strategy:** GitManager uses `git fetch origin <branch>` + `git reset --hard origin/<branch>` instead of plain `git pull`. This guarantees a clean sync even if the upstream had a force-push, without merge conflicts.

**Multiple Upstreams:** You can add as many upstreams as you need. Each one is pulled independently.

---

## 4. Defining Path Forwards

Path Forwards define which files or directories from an upstream get copied into your project.

Click **+ Forward** in the toolbar. A new row appears in the **Path Forwards** section.

| Field | Description | Example |
|---|---|---|
| **From** | Source path (inside the upstream clone) | `/home/user/.claude-skills/skills/python-patterns` |
| **To** | Destination path (inside your project) | `/home/user/my-project/skills/python-patterns` |
| **Toggle** | Enable or disable this forward rule | ON |

Forwards are grouped by upstream name in the UI for easy navigation.

**Rules:**
- If `From` is a **directory**, the entire directory is copied recursively.
- If `From` is a **file**, only that file is copied.
- Multiple forwards can safely write to the same destination directory (Wipe-Once Merge Strategy).
- Set a forward to **OFF** to temporarily pause it without deleting the rule.

You can use `{REPO_ROOT}` as a placeholder for your project's root path in the path fields — GitManager resolves it automatically.

---

## 5. Configuring Git Settings

In the **Manual Commit Template** section, customize the commit message format.

Available placeholders:
- `{count}` — number of files changed
- `{datetime}` — timestamp of the sync

In the **Toolbar**, you can also configure:
- **Branch** — the Git branch to commit and push to (default: `main`)
- **Push** toggle — enable or disable auto-push after each commit

Per-upstream commit messages can be configured in the **commit** row below each upstream entry.

---

## 6. Running the Sync Worker

Once your upstreams and forwards are configured, click **Save** to persist the configuration. Then click **Run**.

What happens on each sync cycle:
1. Pull (or clone) all enabled upstreams
2. Copy all enabled path forwards into the project
3. Stage all changes (`git add .`)
4. Commit with the configured message template
5. Push to remote (if **Push** is enabled)

The status badge in the sidebar and toolbar updates in real-time:
- `idle` — worker is not running
- `running` — worker is active, syncing on schedule
- `error` — last sync failed (check logs)

Click **Stop** to gracefully stop the background worker.

**Interval:** Set the sync frequency in the **Interval** field (in minutes). The worker sleeps between cycles and re-reads your config on each wake — so you can update settings while the worker is running without restarting it.

---

## 7. Understanding the Toolbar

The toolbar at the top of the main panel shows live project information:

| Element | Description |
|---|---|
| **Path** | Project path (username is masked for privacy) |
| **Status badge** | Current worker status |
| **Branch** | Editable Git branch name |
| **Interval** | Sync frequency in minutes (editable) |
| **Push** | Toggle for auto-push |
| **+ Upstream** | Add a new upstream row |
| **+ Forward** | Add a new path forward row |
| **Save** | Persist all changes to disk |
| **Run / Stop** | Start or stop the background worker |
| **GitHub** | Open the GitManager GitHub repository |
| **Docs** | Open this usage documentation |

---

## 8. Data Storage

All project data is stored as JSON files under `data/`:

```
data/
├── projects.json          # Global project registry (id, name, path, status)
└── projects/
    └── <project-id>/
        ├── upstream.json  # Upstream configurations
        ├── forward.json   # Path forward rules
        ├── automation.json # Git + schedule settings
        └── memory.json    # Last sync result
```

All writes use a `threading.Lock` to prevent race conditions when the background worker and the API handle requests simultaneously.

---

## 9. Environment Variables

All configuration lives in `.env`. Copy `.env.example` to get started:

```bash
cp .env.example .env
```

| Variable | Required | Description | Default |
|---|---|---|---|
| `GM_USERNAME` | ✅ | Dashboard login username | — |
| `GM_PASSWORD` | ✅ | Dashboard login password | — |
| `GM_SECRET_KEY` | ✅ | HMAC signing key for session tokens | — |
| `API_HOST` | ❌ | Bind address | `127.0.0.1` |
| `API_PORT` | ❌ | Server port | `8000` |
| `DATA_DIR` | ❌ | Data storage directory | `data` |
| `LOG_DIR` | ❌ | Log output directory | `logs` |
| `APP_ENV` | ❌ | `development` enables hot-reload | `development` |

> **Security:** Never commit `.env` to version control. It is already included in `.gitignore`.
