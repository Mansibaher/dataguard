"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ShieldCheck,
  LayoutDashboard,
  Database,
  Workflow,
  CheckCheck,
  ScanLine,
  History,
  ArrowUpRight,
  ArrowRight,
  Plus,
  Upload,
  ChevronLeft,
  ChevronRight,
  X,
  RefreshCw,
  Download,
  Play,
  SlidersHorizontal,
  CheckCircle2,
  AlertTriangle,
  Activity,
  LogOut,
  FileText,
  Globe,
  Search,
  Clock,
  Layers,
} from "lucide-react";
import {
  api,
  setToken,
  Dataset,
  Run,
  Rejected,
  RecordRow,
  Audit,
  Overview,
  Rules,
  Page,
  Failure,
} from "../lib/api";
type View =
  | "Overview"
  | "Datasets"
  | "Pipeline runs"
  | "Accepted records"
  | "Quarantine"
  | "Audit trail";
const nav = [
  { name: "Overview", icon: LayoutDashboard },
  { name: "Datasets", icon: Database },
  { name: "Pipeline runs", icon: Workflow },
  { name: "Accepted records", icon: CheckCheck },
  { name: "Quarantine", icon: ScanLine },
  { name: "Audit trail", icon: History },
] as const;
const fmt = (n: number) => n.toLocaleString();
const date = (s: string) =>
  new Date(s + "Z").toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const short = (s: string) => s.slice(0, 8);
function Badge({ state }: { state: string }) {
  return (
    <span className={"badge " + state}>
      <span />
      {state.replaceAll("_", " ")}
    </span>
  );
}
function Pager({
  page,
  total,
  size = 25,
  onChange,
}: {
  page: number;
  total: number;
  size?: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        {total
          ? (page - 1) * size + 1 + "–" + Math.min(page * size, total)
          : "0"}{" "}
        of {fmt(total)} records
      </span>
      <div>
        <button
          className="icon-button"
          aria-label="Previous page"
          disabled={page === 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <span>Page {page}</span>
        <button
          className="icon-button"
          aria-label="Next page"
          disabled={page * size >= total}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty">
      <Layers size={28} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
function ValueTable({
  rows,
  columns,
}: {
  rows: Record<string, unknown>[];
  columns?: string[];
}) {
  const cols = columns || Array.from(new Set(rows.flatMap(Object.keys)));
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{c.replaceAll("_", " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>
                  {r[c] === null || r[c] === "" ? (
                    <span className="null">null</span>
                  ) : (
                    String(r[c] ?? "—")
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export default function Home() {
  const [ready, setReady] = useState(false),
    [email, setEmail] = useState("demo@dataguard.local"),
    [password, setPassword] = useState("dataguard-demo"),
    [user, setUser] = useState("");
  const [view, setView] = useState<View>("Overview"),
    [overview, setOverview] = useState<Overview | null>(null),
    [datasets, setDatasets] = useState<Dataset[]>([]),
    [datasetTotal, setDatasetTotal] = useState(0);
  const [runs, setRuns] = useState<Page<Run> | null>(null),
    [records, setRecords] = useState<Page<RecordRow> | null>(null),
    [quarantine, setQuarantine] = useState<Page<Rejected> | null>(null),
    [audits, setAudits] = useState<Page<Audit> | null>(null);
  const [page, setPage] = useState(1),
    [reason, setReason] = useState(""),
    [filter, setFilter] = useState(""),
    [search, setSearch] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [modal, setModal] = useState<
      "upload" | "dataset" | "run" | "correction" | null
    >(null),
    [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null),
    [rules, setRules] = useState<Rules | null>(null),
    [preview, setPreview] = useState<Page<{
      number: number;
      values: Record<string, unknown>;
    }> | null>(null),
    [previewPage, setPreviewPage] = useState(1);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null),
    [selectedQ, setSelectedQ] = useState<Rejected | null>(null),
    [correction, setCorrection] = useState<Record<string, unknown>>({}),
    [correctionErrors, setCorrectionErrors] = useState<Failure[]>([]),
    [checked, setChecked] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>(["demo"]),
    [connector, setConnector] = useState("demo"),
    [pageSize, setPageSize] = useState(100),
    [maxPages, setMaxPages] = useState(10);
  useEffect(() => {
    const saved = sessionStorage.getItem("dataguard-token");
    if (saved) {
      setToken(saved);
      api
        .me()
        .then((u) => setUser(u.email))
        .catch(() => sessionStorage.removeItem("dataguard-token"));
    }
    setReady(true);
  }, []);
  const load = useCallback(async () => {
    if (!user) return;
    const [o, d] = await Promise.all([
      api.overview(),
      api.datasets(view === "Datasets" ? page : 1),
    ]);
    setOverview(o);
    setDatasets(d.items);
    setDatasetTotal(d.total);
    if (view === "Pipeline runs") setRuns(await api.runs(page));
    if (view === "Accepted records")
      setRecords(await api.records(page, filter));
    if (view === "Quarantine")
      setQuarantine(await api.quarantine(page, reason, filter));
    if (view === "Audit trail") setAudits(await api.audit(page));
  }, [user, view, page, reason, filter]);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);
  useEffect(() => {
    if (!user) return;
    const timer = setInterval(() => {
      load().catch(() => {});
      if (selectedRun && modal === "run")
        api
          .run(selectedRun.id)
          .then(setSelectedRun)
          .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [load, user, modal, selectedRun?.id]);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };
  const go = (v: View) => {
    setView(v);
    setPage(1);
    setSearch("");
    setChecked([]);
    setFilter("");
    setReason("");
  };
  const openDataset = async (d: Dataset) => {
    await act(async () => {
      const detail = await api.dataset(d.id);
      setSelectedDataset(detail);
      setRules(structuredClone(detail.configurations![0].rules));
      setPreview(await api.preview(d.id));
      setPreviewPage(1);
      setModal("dataset");
    });
  };
  const openRun = async (r: Run) => {
    await act(async () => {
      setSelectedRun(await api.run(r.id));
      setModal("run");
    });
  };
  const login = async () => {
    await act(async () => {
      const data = await api.login(email, password);
      setToken(data.access_token);
      sessionStorage.setItem("dataguard-token", data.access_token);
      const u = await api.me();
      setUser(u.email);
    });
  };
  const startRun = async () => {
    if (!selectedDataset) return;
    await act(async () => {
      const config = await api.configure(selectedDataset.id, rules!);
      const run = await api.start(selectedDataset.id, config.id);
      setSelectedRun(await api.run(run.id));
      setModal("run");
      go("Pipeline runs");
      setNotice(
        "Configuration v" +
          config.version +
          " saved. Run queued for processing.",
      );
    });
  };
  const correct = async () => {
    if (!selectedQ) return;
    await act(async () => {
      const result = await api.correct(selectedQ.id, correction);
      setCorrectionErrors(result.failures);
      if (result.valid) {
        setNotice(
          "Correction validated and saved. Original evidence is preserved.",
        );
        setModal(null);
      }
    });
  };
  const replay = async (ids: string[]) => {
    await act(async () => {
      const run = await api.replay(ids);
      setChecked([]);
      setSelectedRun(await api.run(run.id));
      setModal("run");
      setNotice("Replay queued using the original configuration version.");
    });
  };
  const close = () => {
    setModal(null);
    setCorrectionErrors([]);
  };
  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector("[role=dialog]");
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href]",
        ) || [],
      ).filter((el) => el.getClientRects().length > 0);
    focusable()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const nodes = focusable();
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [modal]);
  if (!ready) return <div className="boot">Loading DataGuard…</div>;
  if (!user)
    return (
      <main className="login">
        <div className="login-story">
          <div className="brand">
            <ShieldCheck /> DataGuard<span> / </span>DATA OPERATIONS
          </div>
          <div>
            <span className="eyebrow">TRUST STARTS WITH YOUR DATA</span>
            <h1>
              Every record.
              <br />
              Accounted for.
            </h1>
            <p>
              Understand your data quality. Investigate failures.
              <br />
              Recover your pipelines with confidence.
            </p>
            <div className="login-pills">
              <span>
                <CheckCircle2 size={15} /> Durable processing
              </span>
              <span>
                <History size={15} /> Full audit history
              </span>
            </div>
          </div>
          <small>BUILT FOR RELIABLE DATA · SYNTHETIC DEMO INCLUDED</small>
        </div>
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            login();
          }}
        >
          <span className="eyebrow">YOUR DATA WORKSPACE</span>
          <h2>Welcome to DataGuard</h2>
          <p>Sign in to monitor, validate, and recover.</p>
          <label>
            Email address
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Open workspace"}
            <ArrowRight size={17} />
          </button>
          <div className="demo-note">
            <ShieldCheck size={20} />
            <div>
              <b>Local demo account</b>
              <p>
                Pre-filled credentials. All bundled sales data is synthetic. No
                paid services required.
              </p>
            </div>
          </div>
        </form>
      </main>
    );
  const name = (id: string) =>
    datasets.find((d) => d.id === id)?.name || "Dataset " + short(id);
  const visibleRuns = (runs?.items || []).filter((r) =>
    (name(r.dataset_id) + " " + r.id + " " + r.state)
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const totalProcessed =
    overview?.recent_runs.reduce((sum, r) => sum + r.processed, 0) || 0;
  const totalRejected =
    overview?.recent_runs.reduce((sum, r) => sum + r.rejected, 0) || 0;
  const quality = totalProcessed
    ? ((1 - totalRejected / totalProcessed) * 100).toFixed(1)
    : "—";
  const trend = [...(overview?.recent_runs || [])].reverse();
  return (
    <div className="shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            go("Overview");
          }}
        >
          <span className="brand-icon">
            <ShieldCheck size={22} />
          </span>
          DataGuard
        </a>
        <div className="workspace">
          <span className="workspace-icon">DG</span>
          <div>
            <b>Demo workspace</b>
            <small>Local environment</small>
          </div>
          <span className="dot" />
        </div>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {nav.map(({ name: n, icon: Icon }) => (
            <button
              key={n}
              aria-label={n}
              title={n}
              className={view === n ? "nav-item active" : "nav-item"}
              onClick={() => go(n)}
            >
              <Icon size={18} />
              <span>{n}</span>
              {n === "Quarantine" && !!overview?.quarantined && (
                <span className="nav-count">{overview.quarantined}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="assurance">
            <ShieldCheck size={20} />
            <b>Evidence, preserved.</b>
            <p>
              Original inputs and configuration versions stay with every run.
            </p>
          </div>
          <button
            className="profile"
            title="Sign out"
            onClick={() => {
              sessionStorage.removeItem("dataguard-token");
              setToken("");
              setUser("");
            }}
          >
            <span className="avatar">DE</span>
            <span>
              <b>Demo engineer</b>
              <small>Local demo account</small>
            </span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div>
            Workspace <span>/</span> <b>{view}</b>
          </div>
          <div className="top-right">
            <span className="local-status">
              <span className="dot" />
              Local demo
            </span>
            <span className="separator" />
            <span className="avatar small">DE</span>
          </div>
        </header>
        <main className="content">
          {error && (
            <div className="error global-error" role="alert">
              <AlertTriangle size={18} />
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              <CheckCircle2 size={17} />
              {notice}
              <button
                aria-label="Dismiss message"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">DATA QUALITY & PIPELINE MONITORING</div>
              <h1>{view === "Overview" ? "Your data, at a glance." : view}</h1>
              <p>
                {
                  (
                    {
                      Overview:
                        "A clear picture of pipeline health, quality, and the records that need attention.",
                      Datasets:
                        "Bring your data in. Preview it, define your rules, and start a reliable run.",
                      "Pipeline runs":
                        "Follow every batch from ingestion to completion, with durable checkpoints.",
                      "Accepted records":
                        "Validated records with unique keys and traceable source provenance.",
                      Quarantine:
                        "Investigate failures, correct records, and replay with confidence.",
                      "Audit trail":
                        "An immutable history of processing, corrections, and recovery.",
                    } as Record<View, string>
                  )[view]
                }
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="secondary"
                onClick={() => act(load)}
                disabled={busy}
              >
                <RefreshCw size={15} />
                Refresh
              </button>
              <button
                className="primary"
                onClick={() => {
                  api
                    .sources()
                    .then((s) => setSources(s.items))
                    .catch(() => {});
                  setModal("upload");
                }}
              >
                <Plus size={17} />
                Add dataset
              </button>
            </div>
          </div>
          {view === "Overview" && overview && (
            <>
              <div className="metrics">
                <Metric
                  label="Accepted records"
                  value={fmt(overview.accepted)}
                  icon={<CheckCheck size={19} />}
                  tone="green"
                  sub="Unique, validated records"
                />
                <Metric
                  label="In quarantine"
                  value={fmt(overview.quarantined)}
                  icon={<ScanLine size={19} />}
                  tone="amber"
                  sub="Original rejected records"
                />
                <Metric
                  label="Pipeline runs"
                  value={fmt(overview.runs)}
                  icon={<Workflow size={19} />}
                  tone="purple"
                  sub={overview.active + " active in recent runs"}
                />
                <Metric
                  label="Validation pass rate"
                  value={quality === "—" ? "—" : quality + "%"}
                  icon={<Activity size={19} />}
                  tone="blue"
                  sub="Last 20 runs · row outcomes"
                />
              </div>
              <div className="dashboard-grid">
                <section className="panel trend">
                  <div className="panel-heading">
                    <div>
                      <h2>Data quality over time</h2>
                      <p>Row acceptance across recent runs</p>
                    </div>
                    <span className="chip">Last {trend.length} runs</span>
                  </div>
                  {trend.length ? (
                    <>
                      <div className="chart-legend">
                        <span className="dot" />
                        Acceptance rate
                        <span className="legend-note">
                          Validation failures included
                        </span>
                      </div>
                      <div className="chart">
                        <div className="chart-labels">
                          <span>100%</span>
                          <span>50%</span>
                          <span>0%</span>
                        </div>
                        <svg
                          viewBox="0 0 600 180"
                          preserveAspectRatio="none"
                          role="img"
                          aria-label="Acceptance rate by run"
                        >
                          <defs>
                            <linearGradient
                              id="fill"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="0%"
                                stopColor="#6366f1"
                                stopOpacity=".18"
                              />
                              <stop
                                offset="100%"
                                stopColor="#6366f1"
                                stopOpacity="0"
                              />
                            </linearGradient>
                          </defs>
                          {[15, 85, 155].map((y) => (
                            <line
                              key={y}
                              x1="0"
                              x2="600"
                              y1={y}
                              y2={y}
                              stroke="#e8ebf1"
                              strokeDasharray="4 5"
                            />
                          ))}
                          <path d={chartPath(trend, true)} fill="url(#fill)" />
                          <path
                            d={chartPath(trend, false)}
                            fill="none"
                            stroke="#6366f1"
                            strokeWidth="2.5"
                          />
                          {trend.map((r, i) => (
                            <circle
                              key={r.id}
                              cx={
                                trend.length === 1
                                  ? 300
                                  : 15 + i * (570 / (trend.length - 1))
                              }
                              cy={
                                155 -
                                (r.processed ? r.accepted / r.processed : 0) *
                                  140
                              }
                              r="4"
                              fill="#6366f1"
                            >
                              <title>
                                {short(r.id)}:{" "}
                                {r.processed
                                  ? ((100 * r.accepted) / r.processed).toFixed(
                                      1,
                                    )
                                  : 0}
                                %
                              </title>
                            </circle>
                          ))}
                        </svg>
                      </div>
                      <div className="chart-bottom">
                        <span>{date(trend[0].created_at)}</span>
                        <span>{date(trend[trend.length - 1].created_at)}</span>
                      </div>
                    </>
                  ) : (
                    <Empty
                      title="Your quality story starts here"
                      detail="Start a dataset run to see measured quality trends."
                    />
                  )}
                </section>
                <section className="panel failure-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>What needs attention</h2>
                      <p>Failure counts · last 20 runs</p>
                    </div>
                    <AlertTriangle size={18} />
                  </div>
                  {Object.keys(overview.failures).length ? (
                    <div className="failure-bars">
                      {Object.entries(overview.failures)
                        .sort((a, b) => b[1] - a[1])
                        .map(([key, n]) => (
                          <button
                            key={key}
                            onClick={() => {
                              go("Quarantine");
                              setReason(
                                [
                                  "non_null",
                                  "type",
                                  "minimum",
                                  "maximum",
                                  "allowed",
                                  "unique_key",
                                ].includes(key)
                                  ? key
                                  : "",
                              );
                            }}
                          >
                            <span>
                              {key.replaceAll("_", " ")}
                              <b>{fmt(n)}</b>
                            </span>
                            <div className="bar-track">
                              <i
                                style={{
                                  width:
                                    (n /
                                      Math.max(
                                        ...Object.values(overview.failures),
                                      )) *
                                      100 +
                                    "%",
                                }}
                              />
                            </div>
                          </button>
                        ))}
                    </div>
                  ) : (
                    <Empty
                      title="No failures recorded"
                      detail="Quality checks will appear after your first run."
                    />
                  )}
                  <div className="panel-foot">
                    <button
                      className="text-button"
                      onClick={() => go("Quarantine")}
                    >
                      Review quarantine
                      <ArrowRight size={14} />
                    </button>
                  </div>
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent pipeline runs</h2>
                    <p>Every run, every checkpoint, fully traceable</p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => go("Pipeline runs")}
                  >
                    View all runs
                    <ArrowRight size={14} />
                  </button>
                </div>
                <RunTable
                  rows={overview.recent_runs.slice(0, 5)}
                  name={name}
                  open={openRun}
                />
              </section>
              <div className="bottom-banner">
                <div className="banner-icon">
                  <Database size={23} />
                </div>
                <div>
                  <b>Put your next dataset to the test.</b>
                  <p>
                    Upload a CSV or connect the bundled HTTP source. Your
                    original input is always preserved.
                  </p>
                </div>
                <button className="secondary" onClick={() => go("Datasets")}>
                  Explore datasets
                  <ArrowUpRight size={16} />
                </button>
              </div>
            </>
          )}
          {view === "Datasets" && (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>
                    Dataset library{" "}
                    <span className="count">{datasetTotal}</span>
                  </h2>
                  <p>
                    UTF-8 CSV & allowed HTTP sources · 10 MiB / 100,000 rows
                  </p>
                </div>
              </div>
              <div className="dataset-grid">
                {datasets.map((d) => (
                  <button
                    className="dataset-card"
                    key={d.id}
                    onClick={() => openDataset(d)}
                  >
                    <div className="dataset-card-top">
                      <span className="file-icon">
                        {d.source.startsWith("http") ? (
                          <Globe size={22} />
                        ) : (
                          <FileText size={22} />
                        )}
                      </span>
                      <ArrowUpRight size={17} />
                    </div>
                    <h3>{d.name}</h3>
                    <p>
                      {fmt(d.row_count)} rows <span>·</span> {d.columns.length}{" "}
                      columns
                    </p>
                    <div className="dataset-tags">
                      <span className="chip">
                        {d.source.startsWith("http") ? "HTTP JSON" : "CSV"}
                      </span>
                      {!!d.provenance.synthetic && (
                        <span className="chip green-chip">Synthetic</span>
                      )}
                    </div>
                    <div className="dataset-card-foot">
                      <span>{date(d.created_at)}</span>
                      <span>
                        Configure
                        <ArrowRight size={13} />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
              {!datasets.length && (
                <Empty
                  title="Add your first dataset"
                  detail="Upload sales CSV data or import the offline mock connector."
                />
              )}
              <Pager page={page} total={datasetTotal} onChange={setPage} />
            </section>
          )}
          {view === "Pipeline runs" && (
            <section className="panel">
              <div className="table-toolbar">
                <h2>
                  All runs <span className="count">{runs?.total || 0}</span>
                </h2>
                <label className="search">
                  <Search size={16} />
                  <input
                    aria-label="Search runs on current page"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search this page…"
                  />
                </label>
              </div>
              <RunTable rows={visibleRuns} name={name} open={openRun} />
              <Pager page={page} total={runs?.total || 0} onChange={setPage} />
            </section>
          )}
          {view === "Accepted records" && (
            <section className="panel">
              <div className="table-toolbar">
                <h2>
                  Accepted records{" "}
                  <span className="count">{records?.total || 0}</span>
                </h2>
                <select
                  aria-label="Filter accepted records by dataset"
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">All datasets</option>
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
              {records?.items.length ? (
                <ValueTable
                  rows={records.items.map((r) => ({
                    row: r.row_number,
                    ...r.values,
                    run: short(r.run_id),
                  }))}
                />
              ) : (
                <Empty
                  title="No accepted records yet"
                  detail="Start a run to validate your data. Accepted records appear here."
                />
              )}
              <Pager
                page={page}
                total={records?.total || 0}
                onChange={setPage}
              />
            </section>
          )}
          {view === "Quarantine" && (
            <section className="panel">
              <div className="table-toolbar">
                <h2>
                  Rejected records{" "}
                  <span className="count">{quarantine?.total || 0}</span>
                </h2>
                <div className="toolbar-filters">
                  <select
                    aria-label="Filter quarantine by dataset"
                    value={filter}
                    onChange={(e) => {
                      setFilter(e.target.value);
                      setPage(1);
                      setChecked([]);
                    }}
                  >
                    <option value="">All datasets</option>
                    {datasets.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Filter failure reason"
                    value={reason}
                    onChange={(e) => {
                      setReason(e.target.value);
                      setPage(1);
                      setChecked([]);
                    }}
                  >
                    <option value="">All failure reasons</option>
                    {[
                      "non_null",
                      "type",
                      "minimum",
                      "maximum",
                      "allowed",
                      "unique_key",
                    ].map((r) => (
                      <option value={r} key={r}>
                        {r.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                  <button
                    className="primary"
                    disabled={!checked.length || busy}
                    onClick={() => replay(checked)}
                  >
                    <Play size={14} />
                    Replay {checked.length || ""}
                  </button>
                </div>
              </div>
              {quarantine?.items.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Select</th>
                        <th>Transaction</th>
                        <th>Failure reason</th>
                        <th>Source row</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quarantine.items.map((q) => (
                        <tr key={q.id}>
                          <td>
                            <input
                              aria-label={"Select record " + q.row_number}
                              type="checkbox"
                              checked={checked.includes(q.id)}
                              disabled={
                                !["corrected", "replay_failed"].includes(
                                  q.status,
                                )
                              }
                              onChange={(e) =>
                                setChecked(
                                  e.target.checked
                                    ? [...checked, q.id]
                                    : checked.filter((i) => i !== q.id),
                                )
                              }
                            />
                          </td>
                          <td>
                            <b>
                              {String(
                                q.original.transaction_id || "Missing ID",
                              )}
                            </b>
                            <small className="cell-sub">
                              {name(q.dataset_id)}
                            </small>
                          </td>
                          <td>
                            <div className="failure-tags">
                              {q.failures.map((f, i) => (
                                <span key={i} title={f.message}>
                                  {f.field}: {f.rule.replaceAll("_", " ")}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="mono">#{q.row_number}</td>
                          <td>
                            <Badge state={q.status} />
                          </td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() => {
                                setSelectedQ(q);
                                setCorrection({
                                  ...(q.corrected || q.original),
                                });
                                setCorrectionErrors([]);
                                setModal("correction");
                              }}
                            >
                              Review
                              <ArrowUpRight size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  title="Nothing in quarantine"
                  detail="Rejected rows appear here with their original values and rule failures."
                />
              )}
              <Pager
                page={page}
                total={quarantine?.total || 0}
                onChange={(n) => {
                  setPage(n);
                  setChecked([]);
                }}
              />
            </section>
          )}
          {view === "Audit trail" && (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Activity ledger</h2>
                  <p>
                    Actions and outcomes retained with source and run references
                  </p>
                </div>
                <span className="chip">Evidence preserved</span>
              </div>
              {audits?.items.length ? (
                <div className="audit-list">
                  {audits.items.map((a) => (
                    <div className="audit-event" key={a.id}>
                      <span className="audit-icon">
                        <History size={16} />
                      </span>
                      <div>
                        <b>
                          {a.action.replaceAll(".", " / ").replaceAll("_", " ")}
                        </b>
                        <p>
                          {a.run_id ? "Run " + short(a.run_id) + " · " : ""}
                          {a.dataset_id ? name(a.dataset_id) : ""}
                        </p>
                        <details>
                          <summary>Event details</summary>
                          <pre>{JSON.stringify(a.detail, null, 2)}</pre>
                        </details>
                      </div>
                      <time>{date(a.created_at)}</time>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty
                  title="No activity yet"
                  detail="Upload a dataset to start the audit trail."
                />
              )}
              <Pager
                page={page}
                total={audits?.total || 0}
                onChange={setPage}
              />
            </section>
          )}
          {!overview && (
            <div className="empty" role="status">
              <RefreshCw className="spin" />
              Loading your workspace…
            </div>
          )}
          <footer>
            DataGuard <span>·</span> Reliable by design{" "}
            <span className="footer-right">
              LOCAL DEMO · SYNTHETIC SEEDED DATA
            </span>
          </footer>
        </main>
      </div>
      {modal && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) close();
          }}
        >
          <section
            className={"modal " + (modal === "dataset" ? "wide" : "")}
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "upload"
                ? "Add dataset"
                : modal === "dataset"
                  ? "Configure dataset"
                  : modal === "run"
                    ? "Run details"
                    : "Correct quarantined record"
            }
          >
            <div className="modal-heading">
              <div>
                <span className="eyebrow">
                  {modal === "run"
                    ? "PIPELINE OBSERVABILITY"
                    : modal === "correction"
                      ? "QUARANTINE REVIEW"
                      : "DATASET MANAGEMENT"}
                </span>
                <h2>
                  {modal === "upload"
                    ? "Bring your data in"
                    : modal === "dataset"
                      ? selectedDataset?.name
                      : modal === "run"
                        ? "Run " + short(selectedRun?.id || "")
                        : "Review & correct"}
                </h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close dialog"
                onClick={close}
              >
                <X size={20} />
              </button>
            </div>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {modal === "upload" && (
              <>
                <p className="modal-intro">
                  Preview your input before configuring rules. Original files
                  are preserved.
                </p>
                <label className="upload-zone">
                  <Upload size={30} />
                  <b>Choose a CSV file</b>
                  <span>UTF-8 or UTF-8 BOM · max 10 MiB</span>
                  <input
                    aria-label="Upload CSV"
                    type="file"
                    accept=".csv,text/csv"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file)
                        act(async () => {
                          const d = await api.upload(file);
                          const detail = await api.dataset(d.id);
                          setSelectedDataset(detail);
                          setRules(
                            structuredClone(detail.configurations![0].rules),
                          );
                          setPreview(await api.preview(d.id));
                          setPreviewPage(1);
                          setModal("dataset");
                          setNotice(
                            "Dataset ingested. Review the preview before starting a run.",
                          );
                        });
                    }}
                  />
                </label>
                <div className="or">
                  <span />
                  OR CONNECT A SOURCE
                  <span />
                </div>
                <div className="connector-box">
                  <div className="section-title">
                    <Globe size={18} />
                    <b>HTTP JSON connector</b>
                    <span className="chip green-chip">Allowlisted</span>
                  </div>
                  <p>
                    Bundled mock sales source works offline inside Docker.
                    Timeouts, bounded retries, and pagination included.
                  </p>
                  <div className="form-grid">
                    <label>
                      Source
                      <select
                        value={connector}
                        onChange={(e) => setConnector(e.target.value)}
                      >
                        {sources.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Page size
                      <input
                        type="number"
                        min="1"
                        max="1000"
                        value={pageSize}
                        onChange={(e) => setPageSize(Number(e.target.value))}
                      />
                    </label>
                    <label>
                      Maximum pages
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={maxPages}
                        onChange={(e) => setMaxPages(Number(e.target.value))}
                      />
                    </label>
                  </div>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => {
                        const d = await api.connector(
                          connector,
                          pageSize,
                          maxPages,
                        );
                        const detail = await api.dataset(d.id);
                        setSelectedDataset(detail);
                        setRules(
                          structuredClone(detail.configurations![0].rules),
                        );
                        setPreview(await api.preview(d.id));
                        setModal("dataset");
                      })
                    }
                  >
                    {busy ? "Importing…" : "Import source"}
                    <ArrowRight size={15} />
                  </button>
                </div>
              </>
            )}
            {modal === "dataset" && selectedDataset && rules && (
              <>
                <div className="dataset-meta">
                  <span>
                    <Database size={14} />
                    {fmt(selectedDataset.row_count)} rows
                  </span>
                  <span>{selectedDataset.columns.length} columns</span>
                  <span>
                    SHA-256{" "}
                    <code title={selectedDataset.content_hash}>
                      {short(selectedDataset.content_hash)}…
                    </code>
                  </span>
                  <button
                    className="text-button"
                    onClick={() => act(() => api.original(selectedDataset.id))}
                  >
                    <Download size={14} />
                    Original input
                  </button>
                </div>
                <h3 className="section-heading">
                  01 <span>Preview your input</span>
                </h3>
                {preview && (
                  <>
                    <ValueTable
                      rows={preview.items.map((r) => r.values)}
                      columns={selectedDataset.columns}
                    />
                    <Pager
                      page={previewPage}
                      total={preview.total}
                      size={10}
                      onChange={(n) =>
                        act(async () => {
                          setPreview(await api.preview(selectedDataset.id, n));
                          setPreviewPage(n);
                        })
                      }
                    />
                  </>
                )}
                <h3 className="section-heading">
                  02 <span>Configure validation rules</span>
                  <span className="chip">
                    Next version:{" "}
                    {(selectedDataset.configurations?.[0].version || 0) + 1}
                  </span>
                </h3>
                <p className="help">
                  Strings are trimmed; blanks are null. Invalid numbers and
                  dates are rejected. Unique keys are fixed for each dataset.
                </p>
                <div className="table-scroll rules-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Type</th>
                        <th>Required</th>
                        <th>Non-null</th>
                        <th>Minimum</th>
                        <th>Maximum</th>
                        <th>Allowed values / date format</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {rules.columns.map((c, i) => (
                        <tr key={i}>
                          <td>
                            <input
                              aria-label={"Column name " + i}
                              value={c.name}
                              disabled={rules.unique_keys.includes(c.name)}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? { ...x, name: e.target.value }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <select
                              aria-label={"Type " + c.name}
                              value={c.type}
                              disabled={rules.unique_keys.includes(c.name)}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? {
                                          ...x,
                                          type: e.target.value as typeof c.type,
                                        }
                                      : x,
                                  ),
                                })
                              }
                            >
                              {["string", "number", "integer", "date"].map(
                                (t) => (
                                  <option key={t}>{t}</option>
                                ),
                              )}
                            </select>
                          </td>
                          <td>
                            <input
                              aria-label={"Required " + c.name}
                              type="checkbox"
                              checked={c.required}
                              disabled={rules.unique_keys.includes(c.name)}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? { ...x, required: e.target.checked }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={"Non-null " + c.name}
                              type="checkbox"
                              checked={c.non_null}
                              disabled={rules.unique_keys.includes(c.name)}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? { ...x, non_null: e.target.checked }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={"Minimum " + c.name}
                              type="number"
                              value={c.minimum ?? ""}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? {
                                          ...x,
                                          minimum:
                                            e.target.value === ""
                                              ? null
                                              : Number(e.target.value),
                                        }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={"Maximum " + c.name}
                              type="number"
                              value={c.maximum ?? ""}
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? {
                                          ...x,
                                          maximum:
                                            e.target.value === ""
                                              ? null
                                              : Number(e.target.value),
                                        }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={
                                "Allowed values or date format " + c.name
                              }
                              value={
                                c.type === "date"
                                  ? c.date_format
                                  : c.allowed.join(",")
                              }
                              placeholder={
                                c.type === "date"
                                  ? "%Y-%m-%d"
                                  : "Comma-separated values"
                              }
                              onChange={(e) =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.map((x, j) =>
                                    j === i
                                      ? c.type === "date"
                                        ? { ...x, date_format: e.target.value }
                                        : {
                                            ...x,
                                            allowed: e.target.value
                                              ? e.target.value
                                                  .split(",")
                                                  .map((v) => v.trim())
                                              : [],
                                          }
                                      : x,
                                  ),
                                })
                              }
                            />
                          </td>
                          <td>
                            <button
                              className="icon-button"
                              aria-label={"Remove " + c.name}
                              disabled={rules.unique_keys.includes(c.name)}
                              onClick={() =>
                                setRules({
                                  ...rules,
                                  columns: rules.columns.filter(
                                    (_, j) => i !== j,
                                  ),
                                })
                              }
                            >
                              <X size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button
                  className="text-button add-column"
                  onClick={() =>
                    setRules({
                      ...rules,
                      columns: [
                        ...rules.columns,
                        {
                          name: "new_column",
                          type: "string",
                          required: true,
                          non_null: true,
                          minimum: null,
                          maximum: null,
                          allowed: [],
                          date_format: "%Y-%m-%d",
                        },
                      ],
                    })
                  }
                >
                  <Plus size={14} />
                  Add column rule
                </button>
                <div className="form-grid config-options">
                  <label>
                    Unexpected columns
                    <select
                      value={rules.unexpected}
                      onChange={(e) =>
                        setRules({
                          ...rules,
                          unexpected: e.target.value as Rules["unexpected"],
                        })
                      }
                    >
                      <option value="warn">Warn and ignore</option>
                      <option value="reject">Reject dataset</option>
                      <option value="allow">Allow and ignore</option>
                    </select>
                  </label>
                  <label>
                    Maximum failure rate (%)
                    <input
                      aria-label="Maximum failure rate"
                      type="number"
                      min="0"
                      max="100"
                      value={Math.round(rules.max_failure_rate * 100)}
                      onChange={(e) =>
                        setRules({
                          ...rules,
                          max_failure_rate: Number(e.target.value) / 100,
                        })
                      }
                    />
                  </label>
                  <label>
                    Unique key
                    <input value={rules.unique_keys.join(", ")} readOnly />
                  </label>
                </div>
                <div className="modal-actions">
                  <span>
                    <ShieldCheck size={15} />
                    Exact configuration preserved for this run
                  </span>
                  <button
                    className="primary"
                    onClick={startRun}
                    disabled={busy}
                  >
                    <Play size={15} />
                    {busy ? "Starting…" : "Save & start validation"}
                  </button>
                </div>
              </>
            )}
            {modal === "run" && selectedRun && (
              <>
                <div className="run-state">
                  <Badge state={selectedRun.state} />
                  <span>
                    {selectedRun.kind === "replay"
                      ? "Correction replay"
                      : "Initial validation"}{" "}
                    · configuration v{selectedRun.configuration?.version}
                  </span>
                </div>
                <div className="progress-label">
                  <b>
                    {fmt(selectedRun.processed)} / {fmt(selectedRun.total)} rows
                  </b>
                  <span>
                    {selectedRun.total
                      ? Math.round(
                          (selectedRun.processed / selectedRun.total) * 100,
                        )
                      : 0}
                    %
                  </span>
                </div>
                <div className="progress">
                  <i
                    style={{
                      width:
                        (selectedRun.total
                          ? (selectedRun.processed / selectedRun.total) * 100
                          : 0) + "%",
                    }}
                  />
                </div>
                <div className="run-numbers">
                  <div>
                    <small>Accepted</small>
                    <b className="green-text">{fmt(selectedRun.accepted)}</b>
                  </div>
                  <div>
                    <small>Rejected</small>
                    <b className="amber-text">{fmt(selectedRun.rejected)}</b>
                  </div>
                  <div>
                    <small>Duration</small>
                    <b>{selectedRun.duration_seconds.toFixed(1)}s</b>
                  </div>
                  <div>
                    <small>Throughput</small>
                    <b>
                      {fmt(selectedRun.rows_per_second)}
                      <small> rows/s</small>
                    </b>
                  </div>
                </div>
                {selectedRun.error && (
                  <div className="error">{selectedRun.error}</div>
                )}
                {selectedRun.warnings.length > 0 && (
                  <div className="warning">
                    {selectedRun.warnings.map((w, i) => (
                      <p key={i}>{w.message}</p>
                    ))}
                  </div>
                )}
                <dl className="run-info">
                  <dt>Dataset</dt>
                  <dd>{name(selectedRun.dataset_id)}</dd>
                  <dt>Run ID</dt>
                  <dd className="mono">{selectedRun.id}</dd>
                  <dt>Started</dt>
                  <dd>
                    {selectedRun.started_at
                      ? date(selectedRun.started_at)
                      : "Waiting for worker"}
                  </dd>
                  <dt>Processing attempts</dt>
                  <dd>{selectedRun.attempts}</dd>
                  <dt>Lease expiry</dt>
                  <dd>
                    {selectedRun.lease_until
                      ? date(selectedRun.lease_until)
                      : "No active lease"}
                  </dd>
                  <dt>Failure counts</dt>
                  <dd>
                    {Object.entries(selectedRun.failures)
                      .map(([k, n]) => k + ": " + n)
                      .join(" · ") || "None"}
                  </dd>
                </dl>
                {!!selectedRun.replay_outcomes?.length && (
                  <>
                    <h3 className="section-heading">Replay outcomes</h3>
                    {selectedRun.replay_outcomes.map((o) => (
                      <div className="replay-outcome" key={o.quarantine_id}>
                        <code>{short(o.quarantine_id)}</code>
                        <Badge state={o.outcome || "queued"} />
                        {o.failures.map((f) => f.message).join("; ")}
                      </div>
                    ))}
                  </>
                )}
                <details className="config-snapshot">
                  <summary>Exact configuration snapshot</summary>
                  <pre>
                    {JSON.stringify(selectedRun.configuration?.rules, null, 2)}
                  </pre>
                </details>
                <div className="modal-actions">
                  <button
                    className="secondary"
                    onClick={() => {
                      close();
                      go("Quarantine");
                      setFilter(selectedRun.dataset_id);
                    }}
                  >
                    Review rejected rows
                    <ArrowRight size={14} />
                  </button>
                  <div>
                    {["queued", "running"].includes(selectedRun.state) && (
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          act(async () =>
                            setSelectedRun(
                              await api.action(selectedRun.id, "cancel"),
                            ),
                          )
                        }
                      >
                        Cancel run
                      </button>
                    )}
                    {(["queued", "running"].includes(selectedRun.state) ||
                      (selectedRun.state === "failed" &&
                        selectedRun.error_kind === "infrastructure")) && (
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() =>
                          act(async () =>
                            setSelectedRun(
                              await api.action(selectedRun.id, "recover"),
                            ),
                          )
                        }
                      >
                        <RefreshCw size={14} />
                        Recover run
                      </button>
                    )}
                  </div>
                </div>
              </>
            )}
            {modal === "correction" && selectedQ && (
              <>
                <div className="run-state">
                  <Badge state={selectedQ.status} />
                  <span>
                    Source row #{selectedQ.row_number} · run{" "}
                    {short(selectedQ.run_id)}
                  </span>
                </div>
                <div className="warning">
                  {selectedQ.failures.map((f, i) => (
                    <p key={i}>
                      <b>{f.field}</b>: {f.message}
                    </p>
                  ))}
                </div>
                <h3 className="section-heading">
                  Original evidence <span className="chip">Preserved</span>
                </h3>
                <pre className="evidence">
                  {JSON.stringify(selectedQ.original, null, 2)}
                </pre>
                <h3 className="section-heading">Corrected values</h3>
                <p className="help">
                  Validated against the original configuration. Save first, then
                  select the record for replay.
                </p>
                <div className="correction-fields">
                  {Object.entries(correction).map(([k, v]) => (
                    <label key={k}>
                      {k.replaceAll("_", " ")}
                      <input
                        aria-label={"Correction " + k}
                        disabled={["replayed", "replay_queued"].includes(
                          selectedQ.status,
                        )}
                        value={String(v ?? "")}
                        onChange={(e) =>
                          setCorrection({ ...correction, [k]: e.target.value })
                        }
                      />
                    </label>
                  ))}
                </div>
                {correctionErrors.length > 0 && (
                  <div className="error" role="alert">
                    {correctionErrors.map((f, i) => (
                      <p key={i}>
                        {f.field}: {f.message}
                      </p>
                    ))}
                  </div>
                )}
                <div className="modal-actions">
                  <span>
                    <History size={15} />
                    Every correction is audited
                  </span>
                  <button
                    className="primary"
                    onClick={correct}
                    disabled={
                      busy ||
                      ["replayed", "replay_queued"].includes(selectedQ.status)
                    }
                  >
                    <CheckCircle2 size={15} />
                    {busy ? "Validating…" : "Validate & save correction"}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
function Metric({
  label,
  value,
  icon,
  tone,
  sub,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  tone: string;
  sub: string;
}) {
  return (
    <div className="metric">
      <div>
        <span>{label}</span>
        <span className={"metric-icon " + tone}>{icon}</span>
      </div>
      <b>{value}</b>
      <p>
        <span className={"tiny-dot " + tone} />
        {sub}
      </p>
    </div>
  );
}
function chartPath(rows: Run[], area: boolean) {
  const pts = rows.map((r, i) => [
    rows.length === 1 ? 300 : 15 + i * (570 / (rows.length - 1)),
    155 - (r.processed ? r.accepted / r.processed : 0) * 140,
  ]);
  return (
    "M " +
    pts.map((p) => p.join(" ")).join(" L ") +
    (area
      ? " L " + pts[pts.length - 1][0] + " 175 L " + pts[0][0] + " 175 Z"
      : "")
  );
}
function RunTable({
  rows,
  name,
  open,
}: {
  rows: Run[];
  name: (id: string) => string;
  open: (r: Run) => void;
}) {
  return rows.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Dataset / run</th>
            <th>Status</th>
            <th>Processed</th>
            <th>Accepted</th>
            <th>Rejected</th>
            <th>Duration</th>
            <th>Started</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>
                <button className="row-link" onClick={() => open(r)}>
                  <span className="table-file">
                    <FileText size={17} />
                  </span>
                  <span>
                    <b>{name(r.dataset_id)}</b>
                    <small className="cell-sub">
                      {short(r.id)} · {r.kind}
                    </small>
                  </span>
                </button>
              </td>
              <td>
                <Badge state={r.state} />
              </td>
              <td>
                {fmt(r.processed)}
                <span className="muted"> / {fmt(r.total)}</span>
              </td>
              <td className="green-text">{fmt(r.accepted)}</td>
              <td className={r.rejected ? "amber-text" : "muted"}>
                {fmt(r.rejected)}
              </td>
              <td>{r.duration_seconds.toFixed(1)}s</td>
              <td className="muted">{date(r.created_at)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label={"Open run " + short(r.id)}
                  onClick={() => open(r)}
                >
                  <ArrowUpRight size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty
      title="Ready for your first run"
      detail="Open a dataset, review its validation rules, and start processing."
    />
  );
}
