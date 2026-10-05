import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useEditTask, type TaskEditChanges } from "@/features/tasks/api/edit-task";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/utils/cn";

// Owner edit before the employee starts (contract: edit-task-screen-contract.md, amended by
// edit-task-screen-contract-amendment-1.md). The dialog does NOT decide who may edit or whether the
// task is still editable — the task page does that before it opens this dialog. The server is the
// real control either way.

const MAX_TITLE = 300;
const MAX_DESCRIPTION = 5000;

const ERR_409 = "This task can't be edited from its current status. Refresh and try again.";
const ERR_404 = "Could not load this task.";
const ERR_422 = "That employee can't be assigned. Choose another.";
const ERR_GENERIC = "Something went wrong. Try again.";

export interface EditableTask {
  id: string;
  title: string;
  description: string | null;
  assignedTo: string | null;
  status: string;
}

export interface EmployeeOption {
  id: string;
  fullName: string;
  isActive: boolean;
}

type FieldErrors = Partial<Record<"title" | "description" | "assignedTo", string>>;

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return ERR_409;
    if (error.status === 404) return ERR_404;
    if (error.status === 422) return ERR_422;
  }
  // Never render error.problem / error.message here: they can carry server internals.
  return ERR_GENERIC;
}

function fieldClass(hasError: boolean) {
  return cn(hasError && "border-(--color-ledger-danger)");
}

export function EditTaskDialog({
  task,
  employees,
  open,
  onOpenChange,
}: {
  task: EditableTask;
  employees: EmployeeOption[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description ?? "");
  const [assignedTo, setAssignedTo] = useState(task.assignedTo ?? "");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  // Synchronous guard: a second click that lands before React re-renders must not send a second
  // PATCH. isPending alone is too late for that.
  const inFlight = useRef(false);
  const editTask = useEditTask();

  // Reset to the task's current values each time the dialog OPENS (not when it closes), so a
  // successful save does not blank the form under the owner, and a reopen never shows stale edits.
  // Done during render with a stored previous-open flag, the React-documented alternative to an
  // effect: no extra render pass, and a parent re-render while open never wipes what was typed.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setTitle(task.title);
      setDescription(task.description ?? "");
      setAssignedTo(task.assignedTo ?? "");
      setFieldErrors({});
      setServerError(null);
    }
  }

  // Inactive employees are never offered as a new assignee (contract item 6). The task's current
  // assignee is still shown, disabled, if they were deactivated after assignment, so the select
  // keeps a real value instead of silently showing the first option.
  const activeOptions = employees.filter((e) => e.isActive);
  const currentInactive = employees.find((e) => e.id === task.assignedTo && !e.isActive);

  function save() {
    if (inFlight.current) return;

    const nextErrors: FieldErrors = {};
    if (title.trim() === "") nextErrors.title = "Title is required.";
    else if (title.length > MAX_TITLE) nextErrors.title = `Title must be ${MAX_TITLE} characters or fewer.`;
    if (description.length > MAX_DESCRIPTION)
      nextErrors.description = `Description must be ${MAX_DESCRIPTION} characters or fewer.`;
    if (assignedTo === "") nextErrors.assignedTo = "Choose an employee.";
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    // Only changed fields are sent. A key that is absent means "leave it alone".
    const changes: TaskEditChanges = {};
    if (title !== task.title) changes.title = title;
    if (description !== (task.description ?? "")) changes.description = description === "" ? null : description;
    if (assignedTo !== (task.assignedTo ?? "")) changes.assigned_to = assignedTo;

    if (Object.keys(changes).length === 0) {
      onOpenChange(false);
      return;
    }

    inFlight.current = true;
    setServerError(null);
    editTask.mutate(
      { taskId: task.id, changes },
      {
        onSuccess: () => {
          inFlight.current = false;
          onOpenChange(false);
        },
        onError: (error) => {
          inFlight.current = false;
          setServerError(messageFor(error));
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Edit task</DialogTitle>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
          className="flex flex-col gap-4"
        >
          <div>
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              aria-invalid={fieldErrors.title ? "true" : undefined}
              className={fieldClass(Boolean(fieldErrors.title))}
            />
            {fieldErrors.title && (
              <p role="alert" className="mt-1 text-sm text-(--color-ledger-danger)">
                {fieldErrors.title}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              aria-invalid={fieldErrors.description ? "true" : undefined}
              className={fieldClass(Boolean(fieldErrors.description))}
            />
            {fieldErrors.description && (
              <p role="alert" className="mt-1 text-sm text-(--color-ledger-danger)">
                {fieldErrors.description}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="assignedTo">Assignee</Label>
            <select
              id="assignedTo"
              value={assignedTo}
              onChange={(event) => setAssignedTo(event.target.value)}
              aria-invalid={fieldErrors.assignedTo ? "true" : undefined}
              className={cn(
                "w-full rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) px-3 py-2 text-sm",
                fieldClass(Boolean(fieldErrors.assignedTo)),
              )}
            >
              {assignedTo === "" && (
                <option value="" disabled>
                  Choose an employee
                </option>
              )}
              {currentInactive && (
                <option value={currentInactive.id} disabled>
                  {`${currentInactive.fullName} (inactive)`}
                </option>
              )}
              {activeOptions.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.fullName}
                </option>
              ))}
            </select>
            {fieldErrors.assignedTo && (
              <p role="alert" className="mt-1 text-sm text-(--color-ledger-danger)">
                {fieldErrors.assignedTo}
              </p>
            )}
          </div>
          {serverError && (
            <p role="alert" className="text-sm text-(--color-ledger-danger)">
              {serverError}
            </p>
          )}
          {/* The label stays "Save changes" while busy: the contract requires the save control's
              accessible name to contain "Save". The busy state is shown with aria-busy instead. */}
          <Button type="submit" disabled={editTask.isPending} aria-busy={editTask.isPending}>
            Save changes
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
