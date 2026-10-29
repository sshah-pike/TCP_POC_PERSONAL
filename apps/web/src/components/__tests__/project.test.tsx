import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Meta, Project, ProjectLocation, ProjectSummary, RunState, RunSummary } from "../../types";

// The API module is mocked: no server, no network. ApiError stays the real class.
vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    createProject: vi.fn(), getProject: vi.fn(), setProjectInputs: vi.fn(), runProject: vi.fn(), approveZoneCap: vi.fn(),
  };
});

import * as api from "../../api";
import NewProjectForm from "../NewProjectForm";
import ProjectView, { EMPTY_DRAFT, missingByLocation, toDraft, toFields } from "../ProjectView";
import RunHistory from "../RunHistory";
import ServiceErrorBadge from "../ServiceErrorBadge";
import Summary from "../Summary";
import { locationName } from "../../format";

const META = {
  app_version: "t", offline_scenarios: ["supported"], offline_aliases: {}, map_providers: ["azure_maps"], ai_providers: ["foundry"],
  dwt_modes: ["PLAN"], dwt_config_present: false, road_types: ["URBAN_LOW_SPEED", "RURAL"], supported_road_types: ["RURAL"],
  start_fields: ["road_type", "posted_speed_mph", "traffic_volume", "lane_closure"], traffic_volumes: ["HIGH", "LOW"],
  ta_choices: ["AUTO", "TA-1", "TA-6", "TA-10", "TA-33"], max_zones: 3, max_parallel_zone_runs: 3,
  rule_pack: null, rule_pack_error: null, pricing_source: null, foundry_profiles: [], resume_stages: [],
} as unknown as Meta;

const loc = (n: number, label: string | null, extra: Partial<ProjectLocation> = {}): ProjectLocation => ({
  location_id: `LOC-${n}`, ordinal: n - 1, display_label: label, reject_reasons: [],
  geometry: { type: "POINT", coords: [41.4 + n / 100, -71.7] }, ...extra,
});

function project(over: Partial<Project> = {}): Project {
  const locations = over.locations ?? [loc(1, "P1"), loc(2, null), loc(3, "  ")];
  return {
    project_id: "PRJ-abc", name: "three.kml", created_at: "2026-10-29T10:00:00+00:00", status: "INPUTS_REQUIRED",
    source: { kind: "KML" }, locations, labels: {}, inputs: [{ uri: "k", sha256: "a".repeat(64), size: 1, media_type: "x", uploaded_at: "2026-10-29T10:00:00+00:00" }],
    start_fields: { project: { road_type: null, posted_speed_mph: null, traffic_volume: null, lane_closure: null }, per_location: {} },
    ta_hypothesis: { project: "AUTO", per_location: {} }, zones: [], zone_runs: {},
    missing_fields: {}, max_zones: 3, cap_cleared: true, cap_approval: null, ...over,
  };
}

const zone = (n: number, runId: string | null = null) => ({
  zone_id: `ZONE-${n}`, version: 1, location_ids: [`LOC-${n}`], status: "PENDING", lineage_key: `k${n}`,
  ta: { value: "AUTO", source: "UI", status: "HYPOTHESIS" }, current_run_id: runId, run_ids: runId ? [runId] : [],
});

const mocked = vi.mocked(api);
const user = () => userEvent.setup();

async function show(p: Project, onOpenRun = vi.fn(), onChanged = vi.fn()) {
  mocked.getProject.mockResolvedValue(p);
  render(<ProjectView projectId={p.project_id} meta={META} onOpenRun={onOpenRun} onChanged={onChanged} />);
  await screen.findByTestId("project-status");
  return { onOpenRun, onChanged };
}

/** Type the four project-row values (all of them: nothing is filled in for you). */
async function typeProjectRow(u: ReturnType<typeof user>, skip: string[] = []) {
  if (!skip.includes("road")) await u.selectOptions(screen.getByLabelText("project road type"), "RURAL");
  if (!skip.includes("speed")) await u.type(screen.getByLabelText("project speed"), "25");
  if (!skip.includes("volume")) await u.selectOptions(screen.getByLabelText("project traffic volume"), "LOW");
  if (!skip.includes("closure")) await u.selectOptions(screen.getByLabelText("project lane closure"), "no");
}

beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// ---------------------------------------------------------------------------------------------------------------
describe("start-field helpers", () => {
  it("an empty cell sends null, never a default", () => {
    expect(toFields(EMPTY_DRAFT)).toEqual({ road_type: null, posted_speed_mph: null, traffic_volume: null, lane_closure: null });
    expect(toDraft(undefined)).toEqual(EMPTY_DRAFT);
    expect(toDraft({ lane_closure: false, posted_speed_mph: 25, road_type: "RURAL", traffic_volume: "LOW" }))
      .toEqual({ road_type: "RURAL", posted_speed_mph: "25", traffic_volume: "LOW", lane_closure: "no" });
  });

  it("the speed must be a positive whole number", () => {
    for (const bad of ["0", "-5", "25.5", "abc", "", " "]) expect(toFields({ ...EMPTY_DRAFT, posted_speed_mph: bad }).posted_speed_mph).toBeNull();
    expect(toFields({ ...EMPTY_DRAFT, posted_speed_mph: " 120 " }).posted_speed_mph).toBe(120);
  });

  it("a point's own cell wins, lane closure No counts as typed, and rejected or line locations need nothing", () => {
    const line = loc(4, "L", { geometry: { type: "LINESTRING", coords: [] } });
    const dup = loc(5, "D", { reject_reasons: ["DUPLICATE_OF:LOC-1"] });
    const locations = [loc(1, "P1"), loc(2, "P2"), line, dup];
    const project: typeof EMPTY_DRAFT = { road_type: "RURAL", posted_speed_mph: "25", traffic_volume: "", lane_closure: "no" };
    expect(missingByLocation(locations, project, {})).toEqual({ "LOC-1": ["traffic_volume"], "LOC-2": ["traffic_volume"] });
    expect(missingByLocation(locations, project, { "LOC-1": { ...EMPTY_DRAFT, traffic_volume: "HIGH" } }))
      .toEqual({ "LOC-2": ["traffic_volume"] });
    expect(missingByLocation(locations, EMPTY_DRAFT, {})["LOC-1"]).toEqual(["road_type", "posted_speed_mph", "traffic_volume", "lane_closure"]);
  });

  it("placemark names are display labels with a Location n fallback", () => {
    const p = project();
    expect(p.locations.map((l) => locationName(p, l))).toEqual(["P1", "Location 2", "Location 3"]);
    expect(locationName({ labels: { "LOC-2": { text: "Renamed", input_sha256: "x", input_key: "k" } } }, p.locations[1])).toBe("Renamed");
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe("new project form", () => {
  const open = () => userEvent.click(screen.getByRole("button", { name: /New Project/ }));

  it("has no road type, speed, traffic volume or lane closure input: those are typed on the project", async () => {
    render(<NewProjectForm meta={META} onCreated={vi.fn()} />);
    await open();
    for (const name of [/road type/i, /speed/i, /traffic volume/i, /lane closure/i, /Select TA/i]) {
      expect(screen.queryByRole("combobox", { name })).toBeNull();
      expect(screen.queryByRole("textbox", { name })).toBeNull();
    }
    expect(screen.getByText(/typed on the project, per location, before Run/)).toBeTruthy();
  });

  it("Create stays disabled until a KML is chosen, then creates the project", async () => {
    const onCreated = vi.fn();
    mocked.createProject.mockResolvedValue(project());
    const u = user();
    render(<NewProjectForm meta={META} onCreated={onCreated} />);
    await open();
    const create = screen.getByRole("button", { name: "CREATE PROJECT" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    await u.upload(screen.getByLabelText("KML file"), new File(["<kml/>"], "three.kml", { type: "application/vnd.google-earth.kml+xml" }));
    expect(create.disabled).toBe(false);
    await u.click(create);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("PRJ-abc"));
    const payload = mocked.createProject.mock.calls[0][0];
    expect(payload.input_type).toBe("kml");
    expect(payload.kml?.filename).toBe("three.kml");
    expect(payload).not.toHaveProperty("operator");               // no start field travels with the KML
  });

  it("shows why a KML gave no project: every location with its rejection reasons", async () => {
    mocked.createProject.mockRejectedValue(new api.ApiError(422, {
      error: "no usable work location in the input; every location was rejected", error_code: "NO_USABLE_LOCATION", file_reasons: [],
      locations: [{ location_id: "a", ordinal: 0, label: "nothing", type: null, reject_reasons: ["EMPTY"] },
                  { location_id: "b", ordinal: 1, label: null, type: "POINT", reject_reasons: ["INVALID_GEOMETRY"] }],
    }, "Unprocessable"));
    const u = user();
    render(<NewProjectForm meta={META} onCreated={vi.fn()} />);
    await open();
    await u.upload(screen.getByLabelText("KML file"), new File(["x"], "bad.kml"));
    await u.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    const box = await screen.findByTestId("no-usable-location");
    expect(within(box).getByText("EMPTY")).toBeTruthy();
    expect(within(box).getByText("INVALID_GEOMETRY")).toBeTruthy();
    expect(within(box).getByText("nothing")).toBeTruthy();
    expect(within(box).getByText("Location 2")).toBeTruthy();       // no placemark name: the fallback
    expect(box.textContent).toContain("No project was created");
  });

  it("shows the file-level reason when the KML could not be read at all", async () => {
    mocked.createProject.mockRejectedValue(new api.ApiError(422, {
      error: "root element is not <kml>", error_code: "NO_USABLE_LOCATION", file_reasons: ["INVALID_KML"], locations: [],
    }, ""));
    const u = user();
    render(<NewProjectForm meta={META} onCreated={vi.fn()} />);
    await open();
    await u.upload(screen.getByLabelText("KML file"), new File(["x"], "bad.kml"));
    await u.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(within(await screen.findByTestId("no-usable-location")).getByText("INVALID_KML")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe("project view: start fields", () => {
  it("starts with every start field empty, no default selected, Select TA on Auto, and Run disabled", async () => {
    await show(project());
    for (const who of ["project", "P1", "Location 2", "Location 3"]) {
      expect((screen.getByLabelText(`${who} road type`) as HTMLSelectElement).value).toBe("");
      expect((screen.getByLabelText(`${who} speed`) as HTMLInputElement).value).toBe("");
      expect((screen.getByLabelText(`${who} traffic volume`) as HTMLSelectElement).value).toBe("");
      expect((screen.getByLabelText(`${who} lane closure`) as HTMLSelectElement).value).toBe("");
    }
    expect((screen.getByLabelText("project Select TA") as HTMLSelectElement).value).toBe("AUTO");
    expect((screen.getByLabelText("P1 Select TA") as HTMLSelectElement).value).toBe("");       // follows the project
    const run = screen.getByRole("button", { name: "RUN PROJECT" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    expect(screen.getByText(/Run is disabled: 3 locations still need road type, speed, traffic volume, lane closure/)).toBeTruthy();
    expect(mocked.setProjectInputs).not.toHaveBeenCalled();                                    // nothing was sent or saved
  });

  it("labels: the placemark name, else Location n", async () => {
    await show(project());
    const rows = screen.getAllByTestId("location-row");
    expect(rows.map((r) => r.querySelector("th div")?.textContent)).toEqual(["P1", "Location 2", "Location 3"]);
  });

  it("Run turns on only when all four are typed for every location", async () => {
    const u = user();
    await show(project());
    const run = screen.getByRole("button", { name: "RUN PROJECT" }) as HTMLButtonElement;
    await typeProjectRow(u, ["closure"]);
    expect(run.disabled).toBe(true);                                                           // lane closure still empty
    expect(screen.getByText(/3 locations still need lane closure/)).toBeTruthy();
    await u.selectOptions(screen.getByLabelText("project lane closure"), "no");               // typing "No" counts as typed
    expect(run.disabled).toBe(false);
    await u.selectOptions(screen.getByLabelText("project road type"), "");                    // clearing it turns Run off again
    expect(run.disabled).toBe(true);
  });

  it("a point's own cell can complete a field the project row leaves empty", async () => {
    const u = user();
    await show(project({ locations: [loc(1, "P1"), loc(2, "P2")] }));
    await typeProjectRow(u, ["volume"]);
    const run = screen.getByRole("button", { name: "RUN PROJECT" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    await u.selectOptions(screen.getByLabelText("P1 traffic volume"), "HIGH");
    expect(run.disabled).toBe(true);                                                           // P2 still has none
    await u.selectOptions(screen.getByLabelText("P2 traffic volume"), "LOW");
    expect(run.disabled).toBe(false);
  });

  it("an invalid speed is flagged and does not count as typed", async () => {
    const u = user();
    await show(project({ locations: [loc(1, "P1")] }));
    await typeProjectRow(u, ["speed"]);
    await u.type(screen.getByLabelText("project speed"), "0");
    expect(screen.getByText("whole number above 0")).toBeTruthy();
    expect((screen.getByRole("button", { name: "RUN PROJECT" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Run saves exactly what was typed, then runs", async () => {
    const u = user();
    const p = project({ locations: [loc(1, "P1"), loc(2, "P2")] });
    mocked.setProjectInputs.mockResolvedValue(p);
    mocked.runProject.mockResolvedValue({ ...p, status: "RUNNING" });
    const { onChanged } = await show(p);
    await typeProjectRow(u);
    await u.selectOptions(screen.getByLabelText("project Select TA"), "TA-6");
    await u.type(screen.getByLabelText("P2 speed"), "40");
    await u.selectOptions(screen.getByLabelText("P2 Select TA"), "TA-33");
    await u.click(screen.getByRole("button", { name: "RUN PROJECT" }));
    await waitFor(() => expect(mocked.runProject).toHaveBeenCalledWith("PRJ-abc"));
    const [id, payload] = mocked.setProjectInputs.mock.calls[0];
    expect(id).toBe("PRJ-abc");
    expect(payload.project).toEqual({ road_type: "RURAL", posted_speed_mph: 25, traffic_volume: "LOW", lane_closure: false });
    expect(payload.per_location).toEqual({
      "LOC-1": { road_type: null, posted_speed_mph: null, traffic_volume: null, lane_closure: null },
      "LOC-2": { road_type: null, posted_speed_mph: 40, traffic_volume: null, lane_closure: null },
    });
    expect(payload.ta_project).toBe("TA-6");
    expect(payload.ta_per_location).toEqual({ "LOC-1": null, "LOC-2": "TA-33" });
    expect(mocked.setProjectInputs.mock.invocationCallOrder[0]).toBeLessThan(mocked.runProject.mock.invocationCallOrder[0]);
    expect(onChanged).toHaveBeenCalled();
  });

  it("Apply to all points applies the project row and clears the points' own cells for those fields", async () => {
    const u = user();
    const p = project({ locations: [loc(1, "P1"), loc(2, "P2")] });
    mocked.setProjectInputs.mockResolvedValue(p);
    await show(p);
    await u.type(screen.getByLabelText("P1 speed"), "40");
    await u.selectOptions(screen.getByLabelText("P2 traffic volume"), "HIGH");
    await u.type(screen.getByLabelText("project speed"), "25");
    await u.click(screen.getByRole("button", { name: "Apply to all points" }));
    await waitFor(() => expect(mocked.setProjectInputs).toHaveBeenCalledTimes(1));
    expect(mocked.setProjectInputs.mock.calls[0][1]).toEqual({
      project: { road_type: null, posted_speed_mph: 25, traffic_volume: null, lane_closure: null }, apply_to_all: true });
    await waitFor(() => expect((screen.getByLabelText("P1 speed") as HTMLInputElement).value).toBe(""));
    expect((screen.getByLabelText("P2 traffic volume") as HTMLSelectElement).value).toBe("HIGH");   // not a typed project field
    expect(mocked.runProject).not.toHaveBeenCalled();
  });

  it("shows values the SME saved earlier, and nothing else", async () => {
    await show(project({
      start_fields: { project: { road_type: "RURAL", posted_speed_mph: 30, traffic_volume: "HIGH", lane_closure: true },
                      per_location: { "LOC-2": { posted_speed_mph: 45 } } },
      ta_hypothesis: { project: "TA-6", per_location: { "LOC-3": "TA-10" } },
    }));
    expect((screen.getByLabelText("project road type") as HTMLSelectElement).value).toBe("RURAL");
    expect((screen.getByLabelText("project lane closure") as HTMLSelectElement).value).toBe("yes");
    expect((screen.getByLabelText("Location 2 speed") as HTMLInputElement).value).toBe("45");
    expect((screen.getByLabelText("P1 speed") as HTMLInputElement).value).toBe("");           // the project value is only a hint
    expect((screen.getByLabelText("P1 speed") as HTMLInputElement).placeholder).toBe("project: 30");
    expect((screen.getByLabelText("project Select TA") as HTMLSelectElement).value).toBe("TA-6");
    expect((screen.getByLabelText("Location 3 Select TA") as HTMLSelectElement).value).toBe("TA-10");
  });

  it("lists rejected locations with their reasons and keeps lines and polygons out of the start fields", async () => {
    const dup = loc(4, "Dup", { reject_reasons: ["DUPLICATE_OF:LOC-1"] });
    const line = loc(5, "Line", { geometry: { type: "LINESTRING", coords: [[1, 2], [3, 4]] } });
    await show(project({ locations: [loc(1, "P1"), dup, line] }));
    const rejected = screen.getByTestId("rejected");
    expect(rejected.textContent).toContain("Dup:");
    expect(within(rejected).getByText("DUPLICATE_OF:LOC-1")).toBeTruthy();
    expect(screen.queryByLabelText("Dup road type")).toBeNull();
    expect(screen.queryByLabelText("Line road type")).toBeNull();
    expect(screen.getByText(/zone does not run until S14/)).toBeTruthy();
    expect(screen.getByText(/Run is disabled: 1 location still needs/)).toBeTruthy();         // only P1 counts
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe("project view: cap and zones", () => {
  it("the zone cap blocks Run and one click approves it", async () => {
    const u = user();
    const p = project({
      status: "ZONE_CAP_APPROVAL_REQUIRED", cap_cleared: false,
      locations: [loc(1, "P1"), loc(2, "P2"), loc(3, "P3"), loc(4, "P4")], zones: [1, 2, 3, 4].map((n) => zone(n)),
      start_fields: { project: { road_type: "RURAL", posted_speed_mph: 25, traffic_volume: "LOW", lane_closure: false }, per_location: {} },
    });
    mocked.approveZoneCap.mockResolvedValue({ ...p, status: "RUNNING" });
    await show(p);
    const banner = screen.getByTestId("cap-banner");
    expect(banner.textContent).toContain("4 zones, the limit is 3");
    expect(banner.textContent).toContain("Nothing runs until you approve");
    expect((screen.getByRole("button", { name: "RUN PROJECT" }) as HTMLButtonElement).disabled).toBe(true);
    await u.type(screen.getByLabelText("Approved by"), "Jane SME");
    await u.click(screen.getByRole("button", { name: "Approve and run" }));
    await waitFor(() => expect(mocked.approveZoneCap).toHaveBeenCalledWith("PRJ-abc", "Jane SME"));
  });

  it("an approval is shown as not verified", async () => {
    await show(project({ cap_approval: { approved_by: "UI click", approved_at: "2026-10-29T10:00:00+00:00", zone_count: 4, verified: false } }));
    expect(screen.getByText(/approved for 4 zones by UI click \(not verified\)/)).toBeTruthy();
  });

  it("the zone list shows each run, its decision, the service badge and whether a draft exists", async () => {
    const onOpenRun = vi.fn();
    const p = project({
      status: "REVIEW_REQUIRED", locations: [loc(1, "P1"), loc(2, "P2"), loc(3, "P3")],
      zones: [zone(1, "R1"), zone(2, "R2"), zone(3, null)],
      zone_runs: {
        R1: { state: "FINISHED", draft_available: true, decision: "SUPPORTED_AUTO" },
        R2: { state: "FINISHED", draft_available: false, decision: "REVIEW_REQUIRED", service_error: ["OSM_CONTEXT_UNAVAILABLE"] },
      },
    });
    await show(p, onOpenRun);
    const rows = screen.getAllByTestId("zone-row");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain("SUPPORTED_AUTO"); expect(rows[0].textContent).toContain("available");
    expect(rows[1].textContent).toContain("REVIEW_REQUIRED"); expect(rows[1].textContent).toContain("none");
    expect(within(rows[1]).getByTestId("service-error").getAttribute("title")).toContain("OSM_CONTEXT_UNAVAILABLE");
    expect(within(rows[0]).queryByTestId("service-error")).toBeNull();
    expect(rows[2].textContent).toContain("not started");
    await userEvent.click(within(rows[1]).getByRole("button", { name: "R2" }));
    expect(onOpenRun).toHaveBeenCalledWith("R2");
    expect(screen.getByTestId("project-status").textContent).toBe("REVIEW_REQUIRED");
  });
});

// ---------------------------------------------------------------------------------------------------------------
describe("service error badge", () => {
  it("shows next to the decision only when a service call failed", () => {
    const { container, rerender } = render(<ServiceErrorBadge codes={null} />);
    expect(container.textContent).toBe("");
    rerender(<ServiceErrorBadge codes={false} />); expect(container.textContent).toBe("");
    rerender(<ServiceErrorBadge codes={["AI_CALL2_UNAVAILABLE", "CROPS_UNAVAILABLE"]} />);
    expect(screen.getByTestId("service-error").textContent).toBe("service error");
    expect(screen.getByTestId("service-error").getAttribute("title")).toBe("Service problem: AI_CALL2_UNAVAILABLE, CROPS_UNAVAILABLE");
    rerender(<ServiceErrorBadge codes={true} />); expect(screen.getByTestId("service-error")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------------------------------------------
const run = (id: string, over: Partial<RunSummary> = {}): RunSummary => ({
  run_id: id, created_at: "2026-10-29T10:00:00+00:00", input: `Zone ZONE-${id}`, state: "FINISHED", decision: "REVIEW_REQUIRED",
  service_error: false, project_id: null, zone_id: null, zone_version: null, runtime_ms: 1000, rule_pack: null,
  estimated_cost_usd: null, parent_run_id: null, requested_stage: null, comparison_id: null, ...over,
});
const summary = (id: string, status: ProjectSummary["status"], zones: number): ProjectSummary => ({
  project_id: id, name: `${id}.kml`, created_at: "2026-10-29T10:00:00+00:00", status, zones });

describe("run history grouped by project", () => {
  it("lists projects with their zone runs inside, and other runs apart", async () => {
    const u = user();
    const onSelect = vi.fn();
    render(<RunHistory projects={[summary("PRJ-1", "PARTIAL", 2), summary("PRJ-2", "READY", 1)]}
                       runs={[run("A1", { project_id: "PRJ-1" }), run("A2", { project_id: "PRJ-1", service_error: true }),
                              run("OLD", { input: "Offline: supported" })]}
                       comparisons={[]} selected={null} onSelect={onSelect} />);
    const groups = screen.getAllByTestId("history-project");
    expect(groups).toHaveLength(2);
    expect(groups[0].textContent).toContain("PARTIAL");
    expect(groups[1].textContent).toContain("READY");
    expect(screen.queryByText("↳ A1")).toBeNull();                     // collapsed until opened
    expect(screen.getByText("OLD")).toBeTruthy();                      // a run with no project stays visible
    expect(screen.getByText("Other runs")).toBeTruthy();
    await u.click(within(groups[0]).getByTitle("Expand"));
    expect(screen.getByText("↳ A1")).toBeTruthy();
    expect(screen.getByText("↳ A2")).toBeTruthy();
    expect(within(screen.getByText("↳ A2").closest("button")!).getByTestId("service-error")).toBeTruthy();
    expect(within(screen.getByText("↳ A1").closest("button")!).queryByTestId("service-error")).toBeNull();
    await u.click(within(groups[1]).getByText("PRJ-2.kml"));
    expect(onSelect).toHaveBeenCalledWith({ kind: "project", id: "PRJ-2" });
  });

  it("opens the project of the selected run", () => {
    render(<RunHistory projects={[summary("PRJ-1", "ALL_DRAFTED", 1)]} runs={[run("A1", { project_id: "PRJ-1" })]}
                       comparisons={[]} selected={{ kind: "run", id: "A1" }} onSelect={vi.fn()} />);
    expect(screen.getByText("↳ A1")).toBeTruthy();                        // its project group is open
  });

  it("shows a REVIEW_REQUIRED run as REVIEW_REQUIRED even when a service call failed", () => {
    render(<RunHistory projects={[]} runs={[run("R9", { decision: "REVIEW_REQUIRED", service_error: true })]} comparisons={[]}
                       selected={null} onSelect={vi.fn()} />);
    const row = screen.getByText("R9").closest("button")!;
    expect(row.textContent).toContain("REVIEW_REQUIRED");
    expect(row.textContent).not.toContain("ERROR");
    expect(within(row).getByTestId("service-error")).toBeTruthy();
  });

  it("says so when there is nothing yet", () => {
    render(<RunHistory projects={[]} runs={[]} comparisons={[]} selected={null} onSelect={vi.fn()} />);
    expect(screen.getByText("No projects or runs yet.")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------------------------------------------
function runState(request: Record<string, unknown>, over: Record<string, unknown> = {}): RunState {
  return {
    run_id: "R1", request, state: "FINISHED", decision: "REVIEW_REQUIRED", exit_code: 3, started_at: null, ended_at: null,
    created_at: "2026-10-29T10:00:00+00:00", runtime_ms: 1, span_total_ms: 1, tls: null, rule_pack: null, selected_ta: null,
    error: null, stages: [], lineage: null, service_error: null,
    cost: { ai: { models: [], calls: 0, usage: null, new_api_call: false, reused_from: [], provider_reported_cost_usd: null,
                  estimated_cost_usd: null, note: null }, services: [], total_cost_usd: null, total_note: "", pricing_source: null },
    ...over,
  } as unknown as RunState;
}
const kmlRequest = (extra: Record<string, unknown>) => ({
  input_type: "kml", kml_filename: "a.kml", kml_size_bytes: 10, operator: { road_type: "RURAL", speed: 25, requires_lane_closure: false, options: [] },
  advanced: { map_provider: null, ai_provider: null, dwt_mode: null, no_dwt: false }, ...extra });

describe("run summary", () => {
  it("shows the stored upload as Input key (and still reads the S2 name)", () => {
    const { rerender } = render(<Summary run={runState(kmlRequest({ kml_key: "R1/input/site.kml" }))} />);
    expect(screen.getByText("Input key")).toBeTruthy();
    expect(screen.getByText("R1/input/site.kml")).toBeTruthy();
    expect(screen.queryByText("Saved at")).toBeNull();
    rerender(<Summary run={runState(kmlRequest({ kml_saved_path: "OLD/input/site.kml" }))} />);
    expect(screen.getByText("OLD/input/site.kml")).toBeTruthy();
    expect(screen.getByText("Input key")).toBeTruthy();
  });

  it("shows the project, zone, traffic volume and Select TA of a zone run, and the service badge", () => {
    render(<Summary run={runState({
      input_type: "zone", project: { project_id: "PRJ-1", zone_id: "ZONE-9", zone_version: 2, lineage_key: "abcd" },
      operator: { road_type: "RURAL", speed: 25, requires_lane_closure: false, options: [], traffic_volume: "LOW", ta_hypothesis: "AUTO" },
      advanced: { map_provider: null, ai_provider: null, dwt_mode: null, no_dwt: true } }, { service_error: ["MAP_CONTEXT_UNAVAILABLE"] })} />);
    expect(screen.getByText("Project zone")).toBeTruthy();
    expect(screen.getByText("PRJ-1")).toBeTruthy();
    expect(screen.getByText("ZONE-9 v2")).toBeTruthy();
    expect(screen.getByText("LOW")).toBeTruthy();
    expect(screen.getByText("Auto")).toBeTruthy();
    expect(screen.getByTestId("service-error")).toBeTruthy();
    expect(screen.getByText("REVIEW_REQUIRED")).toBeTruthy();
  });
});
