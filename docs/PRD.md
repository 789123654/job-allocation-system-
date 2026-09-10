# CA Firm Practice Management Tool — Product Requirements Document (v2)

Single firm deployment · ~10 users · Schema designed tenant-ready, multi-tenancy not enforced or exposed this phase

> Supersedes the original PRD (prepared prior to 2026-08-31). Section numbers below intentionally mirror the original where content carries over, so changes are easy to trace back.

## 1. Overview

The firm currently allocates work using a physical whiteboard, alongside separate software with no project-management or job-tracking layer. This product replaces that whiteboard with a job allocation system, distributed as an **installed desktop application** (not browser-accessed — see §8 Technical Direction), covering two roles: **Owner** and **Employee**. The system must not depend on the owner remembering to check on jobs manually — it tracks deadlines, surfaces overdue work, and notifies the owner when action is needed.

This is a complete, usable product the firm will run day-to-day — not a disposable prototype — even though the initial footprint is small (one firm, roughly 10 users). The data model is designed so scaling to a multi-tenant SaaS later does not require a schema rebuild, even though multi-tenant enforcement/UI is out of scope for this phase (§6).

### 1.1 Job Type Templates

Job categories (e.g. GST, Income Tax, Bookkeeping, Legal, Company Law) are **not hardcoded**. They're owner-managed templates — created, edited, or deleted by the Owner as a standalone setup action, then selected from when creating a task. This keeps the product from being locked to the CA industry specifically, so it can be adapted to other industries later without a rebuild.

- Owner can create a new job-type template (name, and any fields the firm wants to track per job type).
- Owner can delete a job-type template no longer in use.
- Task creation selects from existing templates rather than a hardcoded enum.

### 1.2 Roles in the System

**Billing Associate is dropped as a dedicated role.** Many small/mid CA firms don't have one — billing responsibility is typically shared among employees. Billing is now a task, assignable to any employee, not a separate lane.

| Role | Purpose |
|---|---|
| Owner | Runs the firm. Creates and assigns work, manages job-type templates, tracks progress, reviews submissions, initiates billing. |
| Employee | Executes assigned work (including billing tasks when assigned one), reports completion, raises issues when blocked. |

## 2. Owner — Requirements

### 2.1 Employee Management
- Create and manage employee accounts
- Deactivate employees (removes them from future assignment, preserves history)

### 2.2 Job-Type Template Management (new)
- Create, edit, and delete job-type templates (§1.1)

### 2.3 Task Management
- Create tasks, tagged under a job-type template
- Assign tasks to a chosen employee, with a deadline
- Change task deadlines after assignment

### 2.4 Visibility & Dashboard
- Dashboard with totals: total / pending / completed jobs
- See each employee's current workload (pending-job count), to support load-balancing at assignment time
- See pending tasks across the firm
- See tasks with approaching deadlines
- See completed tasks
- View employee performance *(metric definition still open — see §9)*
- See in-flight billing tasks across all employees *(open question — see §9)*

### 2.5 Notifications
- Employee marks a task completed (submitted for review)
- Task overdue (past deadline, still not done)
- **Task is exactly 1 day from deadline** — a distinct, visually highlighted warning, separate from the general "approaching deadline" view (new)
- Employee raises an issue on an assigned task

### 2.6 Submission Review Workflow (updated — now three-way)

When an employee submits (marks complete) an assigned task, the owner reviews it and chooses one of three outcomes:

- **Approve** — the task is marked Completed. No further action.
- **Reassign** — the task goes back to the employee with owner-specified changes and a description of the remaining work; returns to an in-progress state, under the same or a different employee (owner's choice).
- **Billing** — the task is marked Completed, **and** a new linked billing task is created (§2.8). This is a deliberate owner action, not automatic — completing a task does not by itself mean it's billable (e.g. "document collection" as a sub-step of an ITR filing is completed work, but not itself a billing event).

### 2.7 Issue Handling

When an employee raises an issue on an assigned task, the owner is notified and can view the issue against that task to resolve it (e.g. clarify scope, adjust deadline, reassign — reassignment from this path also notifies the employee, same as a review-triggered reassignment, see §3.3).

### 2.8 Billing Task Creation (replaces the original "Billing button → Billing Associate queue" flow)

Pressing **Billing** on a reviewed task opens a job-creation form, linked to the original task:

- Assigned to an employee (owner's choice — same or different employee than the original task)
- Deadline set by the owner at creation time
- Description field
- Billing amount
- Billing recipient ("whom" — the client being billed)

The billing task then follows the **employee's normal task flow** (§3), except completion is simpler: the employee marks it **Billed** directly — no owner review cycle (matches the original design intent for billing: lower-stakes than core job work, trust-based). Once marked Billed, its status reflects back on the Owner's dashboard.

### 2.9 Interface

- Desktop only for this phase (mobile explicitly out of scope, see §6)
- Distributed as an installed desktop application, not browser-accessed (see §8)

## 3. Employee — Requirements

### 3.1 Access
- Log in to the system

### 3.2 Task Visibility
- See tasks assigned to them (pending only — completed tasks excluded from this view, to keep it light)
- See new assignments as they arrive (notified individually — Employee A is notified of A's assignments only, never B's, and vice versa)
- See pending work
- See tasks with approaching deadlines
- See own current workload

### 3.3 Task Detail & Actions
- Open a task to see its description and deadline
- Mark a task completed (submits it to the owner for review) — or, for a billing-type task, mark it **Billed** (no owner review step, see §2.8)
- Raise an issue on an assigned task (visible to the owner)
- **See reassigned work explicitly** (new) — a task returned to them shows the owner's changes and remaining-work description clearly, whether the reassignment came from a submission review (§2.6) or from an issue resolution (§2.7). Both are distinct triggers and both must surface.

### 3.4 Notifications
- New task assigned to them (individually targeted, not broadcast to all employees)
- Task reassigned to them — covers both trigger paths (§3.3)
- Task approaching deadline
- **Task not completed by deadline** (new — the original PRD only notified the Owner on overdue; employees now get their own overdue notice on their own tasks too, generated firm-wide so they land whether or not the employee has opened the app — see `API_SPEC.md` Notifications note)

### 3.5 Interface
- Desktop only for this phase (mobile dropped, see §6)

## 4. Core Workflows

### 4.1 Task Lifecycle (updated — three-way review outcome)

Created (Owner) → Assigned to Employee, with deadline → In Progress → Submitted (Employee marks complete) → Owner Review → **Approved** (Completed) *or* **Reassigned** (with changes + remaining work → back to In Progress) *or* **Billing** (Completed + linked billing task created, see §4.2).

### 4.2 Billing Flow (rewritten — no dedicated role)

Owner reviews a submitted task → presses Billing → linked billing task created (assignee, deadline, description, amount, billing recipient set by owner) → billing task appears in that employee's normal task list → Employee marks it **Billed** (no review step) → status reflected on Owner's dashboard.

### 4.3 Issue Flow

Employee raises an issue on an assigned task → Owner notified → Owner views issue against the task → Owner resolves (clarify, adjust deadline, or reassign — reassignment here notifies the employee same as §3.3).

### 4.4 Notification Summary (fully updated)

| Role | Notified When |
|---|---|
| Owner | Task submitted by employee · Task overdue · **Task 1 day from deadline (highlighted)** · Issue raised by employee |
| Employee | New task assigned to them (individually) · Task reassigned to them (post-review or post-issue-resolution) · Task approaching deadline · **Task not completed by their own deadline** |

## 5. Login Flow

Single login page. Credentials are verified server-side; the backend resolves the account's role and routes accordingly — Owner → Owner dashboard, Employee → that specific employee's own dashboard (never another employee's).

**Annotated 2026-09-03, not a scope change:** "the backend" above is Supabase Auth, not FastAPI — `ARCHITECTURE.md`'s Auth Flow section has the frontend call Supabase Auth directly; FastAPI never receives raw credentials, only the resulting JWT, which it independently verifies on every API call. The requirement this section states (credentials checked server-side, role-based routing) is still satisfied — just by a different component than this sentence's wording implies on its own. See `ARCHITECTURE.md` for the actual mechanism.

## 6. Out of Scope for This Phase

- **Multi-tenancy enforcement/UI** — schema is designed tenant-ready (§1 note) so this doesn't require a rebuild later, but no tenant-switching, tenant management, or isolation enforcement ships this phase. Single firm only.
- **Mobile interface** — desktop only for both Owner and Employee this phase (originally planned as an equivalent mobile experience; dropped for now, not abandoned)
- **AI / agentic job creation** (e.g. voice-driven task creation) — deferred to a second stage
- **Voice / TTS input** — dropped for the MVP, typing-only for now
- **Browser-based access** — superseded by the installed-app decision (§8); revisit only if that decision changes

## 7. Technical Direction (for the next planning stage — architecture/data-model docs)

Not final implementation decisions — flagged here so the next planning document starts from the right constraints:

- **Backend:** FastAPI + Supabase (Postgres + Auth) — unchanged from earlier decisions.
- **Frontend/distribution:** Tauri-wrapped installed desktop app. Streamlit (previously the assumed MVP frontend) doesn't fit Tauri's model cleanly — decision made to replace it with a standard web frontend (React or Svelte) inside the Tauri shell. **Specific framework choice (React vs. Svelte) is deferred to the architecture doc**, not decided here.
- **Data model:** tenant-ready from the start (tenant_id/firm_id present in schema per the `postgres-multitenant` skill's patterns), even though only one firm is enforced this phase.
- **Job-type templates:** modeled as data (owned by the firm), not an enum — keeps the schema industry-agnostic per §1.1.

## 8. Open Questions for Implementation

- **In-flight billing visibility:** does the Owner need a consolidated view of all billing tasks currently out across employees (like the original PRD's "Active Billing queue"), or is filtering the normal task list by type sufficient? Leaning toward keeping a consolidated view since the owner lost the billing-associate's dedicated queue as a side effect of dropping that role — needs a decision before the data-model doc.
- **Reassignment target:** can a reassigned task go to a different employee, or does it always return to the same one? Default assumption (carried from original PRD): owner may choose either.
- **Performance metric:** what does "employee performance" consist of — on-time completion rate, task volume, both? Needs a firm-provided definition before implementation.
- **Frontend framework:** React vs. Svelte for the Tauri shell — deferred to the architecture doc (§7).

---

This document reflects the requirements as revised by the firm on 2026-08-31 and is the baseline scope for the initial build. No code or API design proceeds until this — and the technical/data-model documents that follow it — are confirmed.
