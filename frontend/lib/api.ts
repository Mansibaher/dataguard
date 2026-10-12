export interface Rule {
  name: string;
  type: "string" | "number" | "integer" | "date";
  required: boolean;
  non_null: boolean;
  minimum: number | null;
  maximum: number | null;
  allowed: string[];
  date_format: string;
}
export interface Rules {
  columns: Rule[];
  unique_keys: string[];
  unexpected: "warn" | "reject" | "allow";
  max_failure_rate: number;
}
export interface Configuration {
  id: string;
  version: number;
  rules: Rules;
}
export interface Dataset {
  id: string;
  name: string;
  source: string;
  provenance: Record<string, unknown>;
  content_hash: string;
  columns: string[];
  row_count: number;
  created_at: string;
  configurations?: Configuration[];
}
export interface Failure {
  rule: string;
  field: string;
  message: string;
}
export interface Run {
  id: string;
  dataset_id: string;
  configuration_id: string;
  kind: string;
  state: string;
  total: number;
  processed: number;
  accepted: number;
  rejected: number;
  failures: Record<string, number>;
  warnings: Failure[];
  error: string | null;
  error_kind: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  lease_until: string | null;
  duration_seconds: number;
  rows_per_second: number;
  configuration?: Configuration;
  replay_outcomes?: {
    quarantine_id: string;
    outcome: string;
    failures: Failure[];
  }[];
}
export interface Rejected {
  id: string;
  dataset_id: string;
  run_id: string;
  configuration_id: string;
  row_number: number;
  original: Record<string, unknown>;
  corrected: Record<string, unknown> | null;
  failures: Failure[];
  status: string;
  created_at: string;
}
export interface RecordRow {
  id: string;
  dataset_id: string;
  run_id: string;
  row_number: number;
  values: Record<string, unknown>;
  created_at: string;
}
export interface Audit {
  id: string;
  dataset_id: string;
  run_id: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}
export interface Overview {
  datasets: number;
  accepted: number;
  quarantined: number;
  runs: number;
  active: number;
  recent_runs: Run[];
  failures: Record<string, number>;
}
const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
let accessToken = "";
export function setToken(value: string) {
  accessToken = value;
}
async function request<T>(
  route: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (accessToken) headers.set("Authorization", "Bearer " + accessToken);
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !(options.body instanceof URLSearchParams)
  )
    headers.set("Content-Type", "application/json");
  const response = await fetch(base + route, { ...options, headers });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: "Cannot reach the API" }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json() as Promise<T>;
}
export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username: email, password }),
    }),
  me: () => request<{ email: string; local_demo: boolean }>("/auth/me"),
  overview: () => request<Overview>("/overview"),
  datasets: (page = 1) => request<Page<Dataset>>("/datasets?page=" + page),
  dataset: (id: string) => request<Dataset>("/datasets/" + id),
  preview: (id: string, page = 1) =>
    request<Page<{ number: number; values: Record<string, unknown> }>>(
      "/datasets/" + id + "/preview?page=" + page,
    ),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Dataset>("/datasets/upload", { method: "POST", body: form });
  },
  sources: () => request<{ items: string[] }>("/sources"),
  connector: (source: string, page_size: number, max_pages: number) =>
    request<Dataset>("/datasets/connector", {
      method: "POST",
      body: JSON.stringify({ source, page_size, max_pages }),
    }),
  configure: (id: string, rules: Rules) =>
    request<Configuration>("/datasets/" + id + "/configurations", {
      method: "POST",
      body: JSON.stringify(rules),
    }),
  start: (id: string, configuration_id: string) =>
    request<Run>("/datasets/" + id + "/runs", {
      method: "POST",
      body: JSON.stringify({ configuration_id }),
    }),
  runs: (page = 1) => request<Page<Run>>("/runs?page=" + page),
  run: (id: string) => request<Run>("/runs/" + id),
  action: (id: string, action: "cancel" | "recover") =>
    request<Run>("/runs/" + id + "/" + action, { method: "POST" }),
  records: (page = 1, dataset = "") =>
    request<Page<RecordRow>>(
      "/records?page=" + page + (dataset ? "&dataset_id=" + dataset : ""),
    ),
  quarantine: (page = 1, reason = "", dataset = "") =>
    request<Page<Rejected>>(
      "/quarantine?page=" +
        page +
        (reason ? "&reason=" + reason : "") +
        (dataset ? "&dataset_id=" + dataset : ""),
    ),
  correct: (id: string, values: Record<string, unknown>) =>
    request<{ valid: boolean; failures: Failure[] }>(
      "/quarantine/" + id + "/correction",
      { method: "PUT", body: JSON.stringify({ values }) },
    ),
  replay: (ids: string[]) =>
    request<Run>("/quarantine/replay", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  audit: (page = 1) => request<Page<Audit>>("/audit?page=" + page),
  original: async (id: string) => {
    const response = await fetch(base + "/datasets/" + id + "/original", {
      headers: { Authorization: "Bearer " + accessToken },
    });
    if (!response.ok) throw new Error("Original file unavailable");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "dataguard-original";
    a.click();
    URL.revokeObjectURL(url);
  },
};
