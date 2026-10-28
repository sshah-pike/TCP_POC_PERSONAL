import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ME, api, attention, finding, routesFor, summary, view } from "./fixtures";

vi.mock("../api", async () => (await import("./fixtures")).mockApiModule());

import AssistantDock, { launcherText } from "../AssistantDock";
import ChatFlow, { InlineForm, PlacementResult } from "../ChatFlow";
import ReviewSections from "../ReviewSections";

const RUNS = [{ run_id: "R1", decision: "REVIEW_REQUIRED" }, { run_id: "R2", decision: "SUPPORTED_AUTO" }];
const dock = (runId: string | null = "R1") => <AssistantDock runId={runId} runs={RUNS} me={ME} onOpenRun={() => undefined} mode="full" />;
const chatDock = (runId: string | null = "R1") => <AssistantDock runId={runId} runs={RUNS} me={ME} onOpenRun={() => undefined} />;

beforeEach(() => { api.calls.length = 0; window.localStorage.clear(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("floating launcher states", () => {
  it("formats blocking / pending / running / complete", () => {
    expect(launcherText({ BLOCKING: 2, PENDING: 3 } as never, false, true)).toBe("2 blocking");
    expect(launcherText({ BLOCKING: 0, PENDING: 3 } as never, false, true)).toBe("3 pending");
    expect(launcherText({ BLOCKING: 0, PENDING: 0 } as never, false, true)).toBe("Review complete");
    expect(launcherText(undefined, true, false)).toBe("running");
  });

  it("non-blocking items update the badge without opening the assistant", async () => {
    routesFor("R1", null, summary("R1", attention([], 3)));
    render(dock());
    expect(await screen.findByRole("button", { name: "SME Assistant, 3 pending" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("auto-open", () => {
  it("opens automatically for a blocking item and announces it", async () => {
    routesFor("R1", null, summary("R1", attention(["F-1"])));
    render(dock());
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByText(/No review session for this run yet/)).toBeTruthy();
    expect(screen.getAllByRole("status").some((s) => /SME decision required: Finding F-1/.test(s.textContent ?? ""))).toBe(true);
  });

  it("respects manual close for the same item and reopens for a new blocker", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routesFor("R1", null, summary("R1", attention(["F-1"])));
    render(dock());
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Close assistant" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.parse(window.localStorage.getItem("tcp.sme.ack.R1")!)).toEqual(["F-1"]);
    await act(async () => { vi.advanceTimersByTime(10500); });              // poll: same blocker -> stays closed
    expect(screen.queryByRole("dialog")).toBeNull();
    routesFor("R1", null, summary("R1", attention(["F-1", "F-2"])));        // a NEW blocking item appears
    await act(async () => { vi.advanceTimersByTime(10500); });
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});

describe("blocking priority, menu and keyboard", () => {
  it("shows the blocking question first instead of the menu", async () => {
    const conv = view("C1", "R1", { findings: [finding("F-1")] });
    routesFor("R1", "C1", summary("R1", attention(["F-1"]), "C1"), conv);
    render(dock());
    const blocking = await screen.findByRole("region", { name: "Decisions required" });
    expect(within(blocking).getByText("Fact F-1")).toBeTruthy();                        // first, with its controls
    expect(within(blocking).getByRole("button", { name: "RURAL" })).toBeTruthy();
    expect(screen.getAllByText("Fact F-1").length).toBeGreaterThan(1);                   // also visible in its section
    expect(screen.queryByRole("navigation", { name: "How can I help with this TCP?" })).toBeNull();
  });

  it("manual open without blockers shows context and the four-option menu; Ask uses templates", async () => {
    const conv = view("C1", "R1");
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), conv);
    api.routes["POST conversations/C1/ask"] = () => ({ answer: "No.", model_call: false });
    const user = userEvent.setup();
    render(dock());
    await user.click(await screen.findByRole("button", { name: "SME Assistant, Review complete" }));
    const nav = await screen.findByRole("navigation", { name: "How can I help with this TCP?" });
    for (const t of ["Review & Resolve Issues", "Revise the Draft TCP", "Ask About This Draft", "Review Image & Annotations"])
      expect(within(nav).getByText(t)).toBeTruthy();
    expect(within(nav).getByRole("button", { name: "Move an existing object" })).toBeTruthy();
    expect(screen.getByLabelText("Change run")).toBeTruthy();
    expect(screen.getByText("machine:SITE-X")).toBeTruthy();
    await user.click(within(nav).getByText("Ask About This Draft"));
    await user.click(screen.getByRole("button", { name: "Will Azure Maps be called?" }));
    expect(api.calls.some(([m, p, b]) => m === "POST" && p === "conversations/C1/ask" && b.question_id === "AZURE_CALLED")).toBe(true);
  });

  it("Escape closes the panel and Ctrl+Enter sends the message", async () => {
    const conv = view("C1", "R1");
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), conv);
    api.routes["POST conversations/C1/messages"] = () => ({ status: "ANSWERED" });
    const user = userEvent.setup();
    render(dock());
    await user.click(await screen.findByRole("button", { name: /SME Assistant/ }));
    const box = await screen.findByLabelText("Describe a draft change");
    await user.type(box, "Move s1 100ft");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(api.calls.some(([, p, b]) => p === "conversations/C1/messages" && b.text === "Move s1 100ft")).toBe(true));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("run switching", () => {
  it("warns about unconfirmed staged changes and stays on the run if cancelled", async () => {
    const conv = view("C1", "R1", { staged: [{ key: "ADJUST:S1", action: "MOVE_DEVICE" }] });
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), conv);
    const user = userEvent.setup();
    const { rerender } = render(dock("R1"));
    await user.click(await screen.findByRole("button", { name: /SME Assistant/ }));
    await screen.findByText("machine:SITE-X");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    rerender(dock("R2"));
    expect(confirm).toHaveBeenCalled();
    expect((screen.getByLabelText("Change run") as HTMLSelectElement).value).toBe("R1");
    confirm.mockReturnValue(true);
    api.routes["GET runs/R2/assistant-summary"] = () => summary("R2", attention([], 0));
    fireEvent.change(screen.getByLabelText("Change run"), { target: { value: "R2" } });
    await waitFor(() => expect((screen.getByLabelText("Change run") as HTMLSelectElement).value).toBe("R2"));
    expect(await screen.findByText(/No review session for this run yet/)).toBeTruthy();   // R1's conversation not applied
  });
});

describe("chat flow and inline form", () => {
  const h = { act: vi.fn(async () => ({})), canDecide: true };
  it("renders the continuous flow in order with chat types", () => {
    const msgs = [
      { message_id: "1", role: "assistant", kind: "SUMMARY", created_at: "2026-10-21T10:00:00Z", body: { title: "Site review", text: "2 items" } },
      { message_id: "2", role: "user", kind: "USER_TEXT", created_at: "2026-10-21T10:01:00Z", text: "Move s1 100ft", body: {} },
      { message_id: "3", role: "assistant", kind: "INTERPRETATION", created_at: "2026-10-21T10:01:01Z", body: { status: "NEEDS_CLARIFICATION",
        interpretation: { intent: "MODIFY_OBJECT" }, operations: [] } },
      { message_id: "4", role: "assistant", kind: "FINAL_REVIEW", created_at: "2026-10-21T10:02:00Z", body: { title: "Full change review ready", blocked: false } },
      { message_id: "5", role: "assistant", kind: "VERSION_RESULT", created_at: "2026-10-21T10:03:00Z", body: { title: "Versions created" } },
    ];
    const { container } = render(<ChatFlow messages={msgs} findings={[]} staged={[]} h={h} />);
    expect([...container.querySelectorAll("[data-type]")].map((e) => e.getAttribute("data-type")))
      .toEqual(["PIPELINE_REQUEST", "SME_MESSAGE", "AI_INTERPRETATION", "FINAL_REVIEW", "VERSION_RESULT"]);
    expect(container.querySelectorAll("details[open]").length).toBe(0);                 // technical details collapsed
  });

  it("inline clarification form is keyboard usable and submits structured values", async () => {
    const onSubmit = vi.fn();
    const form = { title: "Complete movement request", target: "placements/evaluate", submit_label: "Validate proposed movement",
                   known: { object_id: "S1", distance: 100, unit: "FT" }, fields: [
                     { name: "direction", label: "Direction", type: "choice", required: true, options: [{ value: "UPSTREAM", label: "Upstream" }, { value: "DOWNSTREAM", label: "Downstream" }] },
                     { name: "preserve_lateral_offset", label: "Preserve lateral offset", type: "choice", required: true, default: true,
                       options: [{ value: true, label: "Yes (recommended)" }, { value: false, label: "No" }] }] };
    const user = userEvent.setup();
    render(<InlineForm form={form} onSubmit={onSubmit} />);
    expect(screen.getByText("S1")).toBeTruthy();
    const submit = screen.getByRole("button", { name: "Validate proposed movement" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.tab(); await user.keyboard(" ");                                            // first radio via keyboard
    await user.click(screen.getByRole("radio", { name: "Upstream" }));
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({ direction: "UPSTREAM", preserve_lateral_offset: true });
  });

  it("placement conflict shows deterministic actions; candidates never auto-apply", async () => {
    const act = vi.fn(async () => ({}));
    const b = { title: "Placement conflict detected", requested: "Move S1 100 ft upstream", object_id: "S1", plan_outcome: "BLOCKED",
                current_station_m: 627, proposed_station_m: 549, along_m: 78, along_ft: 256, straight_m: 78, offset_preserved: true,
                proposed: { offset_m: -5.4 }, conflicts: [{ relationship: "PROPOSED_POINT_INSIDE", severity: "BLOCKING", type: "DRIVEWAY", feature: "osm:d:1" }],
                rule_impact: [{ check_id: "VAL-SPACING", current: "COMPLIANT", proposed: "CONFLICT" }], ta: { current_ta: "TA-1", remains_applicable: true, candidate_tas: [] },
                candidates: [{ kind: "ORIGINAL", station_m: 627 }, { kind: "BEFORE_FEATURE", label: "Place before driveway", station_m: 533 }],
                stage_payload: { object_id: "S1", station_m: 549 } };
    const user = userEvent.setup();
    render(<PlacementResult b={b} h={{ act, canDecide: true }} />);
    expect(screen.getByText(/Blocking/)).toBeTruthy();
    expect(act).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Place before driveway/ }));
    expect(act).toHaveBeenCalledWith("placements/evaluate", { object_id: "S1", station_m: 533, candidate_kind: "BEFORE_FEATURE" });
  });
});

describe("three accordion sections", () => {
  const base = { cid: "C1", canDecide: true, act: vi.fn(), reload: vi.fn(), onChooseFinding: () => () => undefined,
                 finalOpen: false, setFinalOpen: vi.fn(), preview: null };
  beforeEach(() => { api.routes = { "GET conversations/C1/preview": () => ({ preview: null }) }; });

  it("are collapsed by default when nothing needs attention and toggle manually", async () => {
    render(<ReviewSections {...base} view={view("C1", "R1")} attention={attention([], 0)} />);
    const btns = ["Site Evidence & Understanding", "Pending Engineering Review", "Change Set & Decisions"]
      .map((t) => screen.getByRole("button", { name: new RegExp(t.replace("&", "&")) }));
    btns.forEach((b) => expect(b.getAttribute("aria-expanded")).toBe("false"));
    fireEvent.click(btns[1]);
    expect(btns[1].getAttribute("aria-expanded")).toBe("true");
  });

  it("auto-open: site section for a blocking site item, change section for staged changes", () => {
    render(<ReviewSections {...base} view={view("C1", "R1", { findings: [finding("F-1")], staged: [{ key: "FACT:x", action: "CORRECT" }] })}
                           attention={attention(["F-1"], 2)} />);
    expect(screen.getByRole("button", { name: /Site Evidence/ }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: /Change Set/ }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: /Pending Engineering Review/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByLabelText("2 items")).toBeTruthy();                                // pending count badge
  });
});


describe("chat-only mode (default)", () => {
  const msgs = [
    { message_id: "1", role: "assistant", kind: "SUMMARY", created_at: "2026-10-21T10:00:00Z", body: { title: "Site review", text: "x" } },
    { message_id: "2", role: "assistant", kind: "REVIEW_CARD", created_at: "2026-10-21T10:00:01Z", body: { finding_id: "F-1" } },
    { message_id: "3", role: "user", kind: "USER_TEXT", created_at: "2026-10-21T10:01:00Z", text: "Move S1 100 ft upstream", body: {} },
  ];

  it("shows only the Describe-a-change chat: no menu, sections, blocking panel or mode switch", async () => {
    const conv = view("C1", "R1", { findings: [finding("F-1")], messages: msgs });
    routesFor("R1", "C1", summary("R1", attention(["F-1"], 2), "C1"), conv);
    const user = userEvent.setup();
    render(chatDock());
    const launcher = await screen.findByRole("button", { name: "SME Assistant" });   // site findings do not auto-open or badge
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(launcher);
    await screen.findByLabelText("Describe a draft change");
    expect(screen.queryByRole("navigation", { name: "How can I help with this TCP?" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Decisions required" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Site Evidence/ })).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Message type" })).toBeNull();
    expect(screen.getByLabelText("Change run")).toBeTruthy();                           // run switching is in the chat window
    const types = [...document.querySelectorAll("[data-type]")].map((e) => e.getAttribute("data-type"));
    expect(types).toEqual(["SME_MESSAGE"]);                                              // pipeline cards hidden
  });

  it("staged change shows Review & confirm, which opens the final review in the chat", async () => {
    const conv = view("C1", "R1", { staged: [{ key: "ADJUST:S1", action: "MOVE_DEVICE" }] });
    const att = { items: [{ id: "CONFIRM:x", kind: "CONFIRMATION_REQUIRED", category: "BLOCKING", label: "Decision required",
                            title: "Staged change awaits final review", section: "CHANGE" }],
                  counts: { BLOCKING: 1, PENDING: 0, WARNING: 0, INFO: 0, DONE: 0 }, blocking_ids: ["CONFIRM:x"], running: false };
    routesFor("R1", "C1", summary("R1", att, "C1"), conv, att);
    api.routes["GET conversations/C1/review"] = () => ({ review_sha256: "abc", review: {
      blocking: [], request: { structured_actions: [{ key: "ADJUST:S1", action: "MOVE_DEVICE" }], messages: [] },
      versions: { proposed_status: "PROPOSED_REVISION", expected_status_after_regeneration: "DRAFT_WITH_ENGINEERING_EXCEPTION" },
      exceptions: [], modes: { CONFIRM_AND_REGENERATE: { available: true }, SAVE_PROPOSED_REVISION: { available: true }, SAVE_SITE_FACTS_ONLY: { available: false } },
      site: { facts: [], rejected_features: [], superseded_conflicts: [] }, plan_outcome: { status: "DRAFT_WITH_ENGINEERING_EXCEPTION" },
      rules: [], geometry: { movements: [], placement: [], spatial_conflicts: [] }, ta: { current: { ta_id: "TA-1" }, proposed: { applicable: true, message: "TA-1 remains applicable." }, changed_conditions: [], approved_candidates_found: [] },
      expected_calls: { ai_text: 0, azure_maps: 0, osm: 0, foundry_vision: 0 },
      artifacts: { reused: [], regenerated: [], new: [], invalidated_for_child: [] },
      resume: { allowed_choices: [{ stage: "fusion", allowed: true, recommended: true }], reused: [], rerun: [] },
      rule_pack: { id: "RP", version: "1", hash: "h" }, policy: { id: "P", version: "1", sha256: "s" } } });
    const user = userEvent.setup();
    render(chatDock());
    await screen.findByRole("dialog");                                                    // change-flow decision auto-opens
    await user.click(await screen.findByRole("button", { name: "Review & confirm" }));
    expect(await screen.findByText(/Full change review/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Confirm changes and regenerate/ })).toBeTruthy();
  });
});


describe("chat window controls and layout", () => {
  it("change run, new session, delete session (archive after confirmation) from the chat window", async () => {
    const conv = view("C1", "R1");
    const sum = { ...summary("R1", attention([], 0), "C1"), conversations: [
      { conversation_id: "C1", run_id: "R1", created_at: "2026-10-21T10:00:00Z" }, { conversation_id: "C0", run_id: "R1", created_at: "2026-10-20T10:00:00Z" }] };
    routesFor("R1", "C1", sum, conv);
    api.routes["POST conversations"] = () => ({ conversation: { conversation_id: "C2" } });
    api.routes["POST conversations/C1/archive"] = () => ({ archived: { at: "now" } });
    const user = userEvent.setup();
    render(chatDock());
    await user.click(await screen.findByRole("button", { name: "SME Assistant" }));
    expect(await screen.findByLabelText("Change run")).toBeTruthy();
    expect((screen.getByLabelText("Switch session") as HTMLSelectElement).options.length).toBe(2);
    await user.click(screen.getByRole("button", { name: "New session" }));
    expect(api.calls.some(([m, p, b]) => m === "POST" && p === "conversations" && b.run_id === "R1")).toBe(true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    api.calls.length = 0;
    await user.click(await screen.findByRole("button", { name: "Delete session" }));
    expect(confirm).toHaveBeenCalled();
    expect(api.calls.some(([, p]) => p.endsWith("/archive"))).toBe(false);                 // cancelled: nothing deleted
  });

  it("delete confirmed archives the session", async () => {
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), view("C1", "R1"));
    api.routes["POST conversations/C1/archive"] = () => ({ archived: { at: "now" } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(chatDock());
    await user.click(await screen.findByRole("button", { name: "SME Assistant" }));
    await user.click(await screen.findByRole("button", { name: "Delete session" }));
    await waitFor(() => expect(api.calls.some(([m, p]) => m === "POST" && p === "conversations/C1/archive")).toBe(true));
  });

  it("single scroll region, composer pinned with a send button, Enter sends", async () => {
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), view("C1", "R1"));
    api.routes["POST conversations/C1/messages"] = () => ({ status: "READY" });
    const user = userEvent.setup();
    const { container } = render(chatDock());
    await user.click(await screen.findByRole("button", { name: "SME Assistant" }));
    const box = await screen.findByLabelText("Describe a draft change");
    expect(container.ownerDocument.querySelector(".sme-panel-body.chatmode")).toBeTruthy();
    expect(container.ownerDocument.querySelectorAll(".sme-chatwrap.fill .sme-chatbox").length).toBe(1);
    const send = screen.getByRole("button", { name: "Send" });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    expect(box.closest("form")?.className).toBe("sme-chatcomposer");
    await user.type(box, "Move S1 100 ft upstream{Enter}");
    await waitFor(() => expect(api.calls.some(([, p, b]) => p === "conversations/C1/messages" && b.text === "Move S1 100 ft upstream")).toBe(true));
  });
});

describe("read-only identity", () => {
  it("explains why there is no message box instead of hiding it silently", async () => {
    routesFor("R1", "C1", summary("R1", attention([], 0), "C1"), view("C1", "R1"));
    const auditor = { identity: { subject_id: "auditor.1", display_name: "Auditor 1", roles: ["AUDITOR"] }, permissions: ["review:read", "audit:read"] };
    const user = userEvent.setup();
    render(<AssistantDock runId="R1" runs={RUNS} me={auditor as never} onOpenRun={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "SME Assistant" }));
    expect(await screen.findByRole("note")).toBeTruthy();
    expect(screen.getByText(/read-only\. To type changes, choose an/)).toBeTruthy();
    expect(screen.queryByLabelText("Describe a draft change")).toBeNull();
    expect(screen.getByText("Auditor 1 · read-only")).toBeTruthy();
  });
});
