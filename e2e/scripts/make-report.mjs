#!/usr/bin/env node
/**
 * Turns a Playwright run (test-results/results.json + attachments) into a report someone can CHECK WITHOUT
 * RE-RUNNING the suite: e2e/report/RUN_REPORT.md plus the screenshots it links to, and summary.json for machines.
 *
 *   node scripts/make-report.mjs                 # after `npx playwright test`, from e2e/
 *   node scripts/make-report.mjs --out report    # default output folder
 *
 * Everything in the report is read from the run's own output (results, annotations, attachments, the
 * environment captured by global setup); nothing is typed in by hand.
 */
import fs from "node:fs";
import path from "node:path";

const E2E = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const OUT = path.resolve(E2E, process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : "report");
const RESULTS = path.join(E2E, "test-results", "results.json");
const ENV = path.join(E2E, ".cache", "run-env.json"); // written by fixtures/global-setup.ts

if (!fs.existsSync(RESULTS)) { console.error(`no ${RESULTS}: run the suite first`); process.exit(1); }
const run = JSON.parse(fs.readFileSync(RESULTS, "utf8"));
const env = fs.existsSync(ENV) ? JSON.parse(fs.readFileSync(ENV, "utf8")) : {};

function gitSha() {
  try {
    const git = path.join(E2E, "..", ".git");
    const head = fs.readFileSync(path.join(git, "HEAD"), "utf8").trim();
    if (!head.startsWith("ref:")) return { sha: head, branch: "(detached)" };
    const ref = head.slice(5).trim();
    const loose = path.join(git, ref);
    const sha = fs.existsSync(loose) ? fs.readFileSync(loose, "utf8").trim()
      : (fs.readFileSync(path.join(git, "packed-refs"), "utf8").split("\n").find((l) => l.endsWith(" " + ref)) ?? "").split(" ")[0];
    return { sha, branch: ref.replace("refs/heads/", "") };
  } catch { return { sha: process.env.GITHUB_SHA ?? "unknown", branch: process.env.GITHUB_REF_NAME ?? "unknown" }; }
}

// ---- flatten the suite tree
const tests = [];
(function walk(suites, file, titles) {
  for (const s of suites ?? []) {
    const f = s.file ?? file;
    const t = s.title && s.title !== f && !s.title.endsWith(".ts") ? [...titles, s.title] : titles;
    for (const spec of s.specs ?? []) for (const test of spec.tests ?? []) tests.push({ file: f, line: spec.line ?? 0, title: [...t, spec.title].join(" › "), test });
    walk(s.suites, f, t);
  }
})(run.suites, "", []);
tests.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line); // source order, as in the spec files

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, "img"), { recursive: true });
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
const DEF = /DEF-\d{3}/;
const esc = (s) => String(s ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ");

const rows = [], details = [], summary = [];
let n = 0;
for (const { file, title, test } of tests) {
  n++;
  const last = test.results[test.results.length - 1] ?? {};
  const anns = [...(test.annotations ?? []), ...(last.annotations ?? [])];
  const expectedFail = test.expectedStatus === "failed";
  const outcome = test.status === "skipped" ? "skipped"
    : test.status === "flaky" ? "flaky (passed on retry)"
    : test.status === "expected" ? (expectedFail ? "expected failure" : "passed")
    : expectedFail && last.status === "passed" ? "FAILED (expected to fail, but passed)" : "FAILED";
  const defect = (anns.find((a) => a.type === "fail")?.description ?? "").match(DEF)?.[0]
    ?? ((last.error?.message ?? "").match(DEF) ?? [])[0];
  const id = `t${String(n).padStart(2, "0")}`;

  // copy screenshots
  const imgs = [];
  (last.attachments ?? []).filter((a) => a.contentType === "image/png").forEach((a, i) => {
    const name = `${id}-${slug(a.name)}${i ? "-" + i : ""}.png`;
    const dst = path.join(OUT, "img", name);
    if (a.path && fs.existsSync(a.path)) fs.copyFileSync(a.path, dst);
    else if (a.body) fs.writeFileSync(dst, Buffer.from(a.body, "base64"));
    else return;
    imgs.push({ name: a.name, file: `img/${name}` });
  });

  const turns = anns.filter((a) => a.type === "turn").map((a) => JSON.parse(a.description));
  const measured = anns.filter((a) => ["measured", "grafana-memory"].includes(a.type)).map((a) => `${a.type}: ${a.description}`);
  const sec = ((last.duration ?? 0) / 1000).toFixed(1);
  const defLink = defect ? ` [${defect}](../DEFECTS.md#${defect.toLowerCase()})` : "";
  rows.push(`| ${n} | ${esc(file.replace(/^.*tests\//, ""))} | ${esc(title)} | ${outcome}${defLink} | ${sec} s | [details](#${id}) |`);
  summary.push({ n, file, title, outcome, defect: defect ?? null, seconds: Number(sec), turns, measured });

  const d = [`### <a id="${id}"></a>${n}. ${title}`, "", `**${outcome}**${defLink} · ${sec} s · \`${file}\``, ""];
  for (const t of turns) {
    d.push("| | |", "|---|---|",
      `| Heard (transcript) | ${esc(t.transcript)} |`, `| Language detected | \`${esc(t.lang)}\` |`,
      `| Reply | ${esc(t.answer)} |`, `| Tool calls | ${t.tools.length ? t.tools.map((x) => `\`${x}\``).join(", ") : "none"} |`,
      `| Timings | ${esc((t.meta ?? "").replace(/^tools:[^·]*·\s*/, ""))} |`, "");
  }
  for (const m of measured) d.push(`- ${m}`);
  if (measured.length) d.push("");
  if (outcome !== "passed" && last.error?.message) {
    const msg = last.error.message.replace(/\u001b\[[0-9;]*m/g, "").split("\n").filter(Boolean).slice(0, 6).join("\n");
    d.push("```text", msg, "```", "");
  }
  for (const im of imgs) d.push(`![${im.name}](${im.file})`, "");
  details.push(d.join("\n"));
}

const st = run.stats ?? {};
const count = (o) => summary.filter((s) => s.outcome.startsWith(o)).length;
const { sha, branch } = gitSha();
const ci = process.env.GITHUB_RUN_ID
  ? `[GitHub Actions run ${process.env.GITHUB_RUN_ID}](${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}) (HTML report and traces are attached as artifacts)`
  : "local run (not CI)";

const md = `# E2E run report

Generated from the run's own output by \`e2e/scripts/make-report.mjs\`; nothing here is typed by hand.
Use it to check what the suite did **without re-running it**: every voice turn shows what the app heard, what it
answered and which tool it called, with a screenshot of what the user saw.

| | |
|---|---|
| Result | **${count("passed")} passed**, **${count("expected failure")} expected failures** (known defects), **${count("FAILED")} failed**, ${count("flaky")} flaky, ${count("skipped")} skipped |
| Suite time | ${((st.duration ?? 0) / 60000).toFixed(1)} min (started ${st.startTime ?? "?"}) |
| Code under test | \`${sha.slice(0, 12)}\` on \`${branch}\` |
| Where | ${ci} |
| Machine | ${env.host ?? "?"} |
| Backend | \`${env.llm_backend ?? "?"}\` (offline rules router = no API key), Playwright ${env.playwright ?? "?"}, Node ${env.node ?? "?"} |
| Fleet setup | ${env.fleet ?? "?"} |

"Expected failure" means the test exposed a defect that is written up in [DEFECTS.md](../DEFECTS.md) and is marked
\`test.fail()\`; it turns into a real failure the day the defect is fixed.

## All tests

| # | File | Test | Result | Time | |
|---|---|---|---|---|---|
${rows.join("\n")}

## Details

${details.join("\n\n")}
`;
fs.writeFileSync(path.join(OUT, "RUN_REPORT.md"), md);
fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify({ sha, branch, ci: process.env.GITHUB_RUN_ID ?? null, env, stats: st, tests: summary }, null, 1));
console.log(`wrote ${path.relative(process.cwd(), path.join(OUT, "RUN_REPORT.md"))}: ${tests.length} tests, ${fs.readdirSync(path.join(OUT, "img")).length} screenshots`);
