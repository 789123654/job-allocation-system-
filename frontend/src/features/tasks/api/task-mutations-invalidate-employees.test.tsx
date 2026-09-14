import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSession } from "@/stores/session-store";
import {
  resetEmployeesFixture,
  resetTasksFixture,
  resetIssuesFixture,
} from "@/testing/mocks/handlers";
import { useEmployees } from "@/features/employees/api/get-employees";
import { useCreateTask } from "./create-task";
import { useSubmitTask } from "./submit-task";
import { useMarkTaskBilled } from "./mark-task-billed";
import { useCreateTaskReview } from "./create-task-review";
import { useResolveIssue } from "./resolve-issue";

vi.mock("@/stores/session-store", () => ({ useSession: vi.fn() }));

function setup() {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    role: "owner",
    firmId: "firm-1",
    mustChangePassword: false,
    isLoading: false,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

beforeEach(() => {
  resetEmployeesFixture();
  resetTasksFixture();
  resetIssuesFixture();
});

describe("task mutations invalidate the employees cache", () => {
  it("useCreateTask invalidates employees and bumps pendingTaskCount", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ employees: useEmployees(), mutation: useCreateTask() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.employees.isSuccess).toBe(true));
    const baselineCount = result.current.employees.data?.[0].pendingTaskCount;
    const baselineUpdatedAt = result.current.employees.dataUpdatedAt;
    expect(baselineCount).toBe(2);

    await act(async () => {
      await result.current.mutation.mutateAsync({
        title: "New task",
        assignedTo: "e1",
        idempotencyKey: crypto.randomUUID(),
      });
    });

    await waitFor(() =>
      expect(result.current.employees.dataUpdatedAt).toBeGreaterThan(baselineUpdatedAt),
    );
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(3);
  });

  it("useSubmitTask invalidates employees and drops pendingTaskCount", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ employees: useEmployees(), mutation: useSubmitTask() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.employees.isSuccess).toBe(true));
    const baselineUpdatedAt = result.current.employees.dataUpdatedAt;
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(2);

    await act(async () => {
      await result.current.mutation.mutateAsync({
        taskId: "t1",
        idempotencyKey: crypto.randomUUID(),
      });
    });

    await waitFor(() =>
      expect(result.current.employees.dataUpdatedAt).toBeGreaterThan(baselineUpdatedAt),
    );
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(1);
  });

  it("useMarkTaskBilled invalidates employees and drops pendingTaskCount", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ employees: useEmployees(), mutation: useMarkTaskBilled() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.employees.isSuccess).toBe(true));
    const baselineUpdatedAt = result.current.employees.dataUpdatedAt;
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(2);

    await act(async () => {
      await result.current.mutation.mutateAsync({
        taskId: "t2",
        idempotencyKey: crypto.randomUUID(),
      });
    });

    await waitFor(() =>
      expect(result.current.employees.dataUpdatedAt).toBeGreaterThan(baselineUpdatedAt),
    );
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(1);
  });

  it("useCreateTaskReview invalidates employees and bumps pendingTaskCount", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ employees: useEmployees(), mutation: useCreateTaskReview() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.employees.isSuccess).toBe(true));
    const baselineUpdatedAt = result.current.employees.dataUpdatedAt;
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(2);

    await act(async () => {
      await result.current.mutation.mutateAsync({
        taskId: "t3",
        idempotencyKey: crypto.randomUUID(),
        outcome: "reassigned",
        remainingWorkDescription: "still needs docs",
      });
    });

    await waitFor(() =>
      expect(result.current.employees.dataUpdatedAt).toBeGreaterThan(baselineUpdatedAt),
    );
    expect(result.current.employees.data?.[0].pendingTaskCount).toBe(3);
  });

  it("useResolveIssue invalidates employees (regression guard)", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ employees: useEmployees(), mutation: useResolveIssue() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.employees.isSuccess).toBe(true));
    const baselineUpdatedAt = result.current.employees.dataUpdatedAt;

    await act(async () => {
      await result.current.mutation.mutateAsync({
        issueId: "i1",
        idempotencyKey: crypto.randomUUID(),
        resolutionType: "deadline_adjusted",
        newDeadline: "2026-12-01T00:00:00Z",
      });
    });

    // No clean count-delta for this path (t1's status is unchanged) — the dataUpdatedAt bump is
    // the only assertion here, and it's meaningful: this hook was already correct before the
    // shared-helper fix, so this case guards against a future regression, not new behavior.
    await waitFor(() =>
      expect(result.current.employees.dataUpdatedAt).toBeGreaterThan(baselineUpdatedAt),
    );
  });
});
