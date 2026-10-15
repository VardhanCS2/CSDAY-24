# GitHub Branch Protection & Required Status Checks Guide

This document outlines the branch protection strategy and exact configuration steps for the **Common Goods E-Commerce** repository to ensure zero regressions, code quality enforcement, and secure deployments.

---

## 1. Objectives

1. **Prevent Unvalidated Merges**: Disallow direct pushes to production branches (`main` / `master`).
2. **Enforce Automated Verification**: Require all CI pipeline checks (tests, linters, and Docker image builds) to pass before pull requests can be merged.
3. **Mandate Code Review**: Require at least one peer approval before code integration.
4. **Prevent History Rewriting**: Block force pushes (`git push --force`) and branch deletions.

---

## 2. Step-by-Step GitHub Setup

### Step 1: Navigate to Branch Protection Settings
1. Open your repository on GitHub.
2. Click on **Settings** (top navigation tab).
3. In the left sidebar, click **Branches** under the *Code and automation* section.
4. Under **Branch protection rules**, click **Add branch protection rule** (or **Add rule**).

### Step 2: Define Branch Pattern
- **Branch name pattern**: `main` (and create a duplicate rule for `master` if used).

### Step 3: Configure Protection Rules

Enable the following checkboxes:

1. ✅ **Require a pull request before merging**
   - ✅ *Require approvals*: Set to `1` (or more).
   - ✅ *Dismiss stale pull request approvals when new commits are pushed*: Checked (ensures any new commit invalidates previous approval).
   - ✅ *Require review from Code Owners* (optional).

2. ✅ **Require status checks to pass before merging**
   - ✅ *Require branches to be up to date before merging*: Checked (ensures code is tested against the latest target branch).
   - In the search box, search and select the exact job names from `.github/workflows/ci.yml`:
     - `Frontend Lint, Test & Build` (runs oxlint, TypeScript build, Vitest unit tests, Playwright e2e)
     - `Backend Test & Migrations` (runs Alembic migrations, PostgreSQL, Redis, and Pytest)
     - `Validate Docker Images` (verifies multi-stage Docker builds for backend & frontend)

3. ✅ **Require conversation resolution before merging**
   - Ensures all reviewer comments, questions, and tasks are resolved before code is merged.

4. ✅ **Do not allow bypassing the above settings**
   - Ensures rules apply even to repository administrators.

5. ✅ **Block force pushes**
   - Prevents accidental `git push --force` which can erase commit history.

6. ✅ **Block deletions**
   - Protects the `main` branch from accidental deletion.

### Step 4: Save Changes
- Click **Create** or **Save changes** at the bottom of the page.
- Enter your GitHub password or confirm 2FA if prompted.

---

## 3. Workflow Integration Summary

```
Developer Feature Branch ➔ git push ➔ Open Pull Request to main
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
            [Automated CI Workflow]                     [Peer Review Required]
         ├── Frontend: oxlint, Vitest, e2e                 └── 1+ Approval
         ├── Backend: Migrations & Pytest
         └── Docker: Multi-stage Build Validation
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             ▼
                                  [All Status Checks GREEN]
                                             │
                                             ▼
                                       [Merge to main]
                                             │
                                             ▼
                                 [Docker Build & Push]
                                └── Publishes to ghcr.io
```
