"use client";

import Link from "next/link";
import {
  Zap,
  Shield,
  GitBranch,
  BarChart3,
  CheckCircle,
  ArrowRight,
  Bot,
  Search,
  FileCheck,
  UserCheck,
} from "lucide-react";

const FEATURES = [
  {
    icon: Bot,
    title: "Multi-Agent Graph",
    desc: "Five specialized agents — triage, knowledge, investigator, resolver, verifier — collaborate via LangGraph with parallel fan-out.",
  },
  {
    icon: Shield,
    title: "Security-First",
    desc: "Prompt injection screening, tenant RLS isolation, JWT/RBAC auth, SHA-256 audit chain, and circuit breakers on every tool call.",
  },
  {
    icon: Search,
    title: "Hybrid Retrieval",
    desc: "BM25 + dense embedding search with RRF fusion and cross-encoder reranking. Time-travel filtering prevents information leakage.",
  },
  {
    icon: UserCheck,
    title: "Human-in-the-Loop",
    desc: "Financial actions (credits, refunds) require lead approval. Severity-sorted queue with real-time SSE updates.",
  },
  {
    icon: FileCheck,
    title: "Eval Pipeline",
    desc: "100 YAML scenarios, 150 adversarial tickets, judge calibration (86% agreement, kappa 0.787), CI gate with threshold enforcement.",
  },
  {
    icon: BarChart3,
    title: "Full Observability",
    desc: "OpenTelemetry GenAI spans on every hop. Cost tracking, latency monitoring, and Langfuse integration out of the box.",
  },
];

const RESULTS = [
  { metric: "Triage accuracy", value: "100%", threshold: "80%" },
  { metric: "Reply rate", value: "100%", threshold: "60%" },
  { metric: "Attack success rate", value: "0.0%", threshold: "5%" },
  { metric: "Benign success", value: "100%", threshold: "70%" },
  { metric: "Judge agreement", value: "86%", threshold: "85%" },
  { metric: "Cohen's kappa", value: "0.787", threshold: "—" },
];

const AGENTS = [
  { name: "Triage", color: "from-blue-500 to-cyan-400", desc: "Classifies, routes, screens for injection" },
  { name: "Knowledge", color: "from-emerald-500 to-teal-400", desc: "Retrieves docs via hybrid search + rerank" },
  { name: "Investigator", color: "from-amber-500 to-orange-400", desc: "Queries accounts, logs, GitHub via MCP" },
  { name: "Resolver", color: "from-violet-500 to-purple-400", desc: "Drafts reply + action plan from evidence" },
  { name: "Verifier", color: "from-rose-500 to-pink-400", desc: "Fact-checks claims, triggers revision loop" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <header className="border-b border-gray-800/50">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
              <Zap size={16} />
            </div>
            <span className="font-bold text-lg tracking-tight">Resolute</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="https://github.com/DhrumilPanchal10/resolute"
              target="_blank"
              className="text-sm text-gray-400 hover:text-white transition-colors"
            >
              GitHub
            </Link>
            <Link
              href="/dashboard/"
              className="text-sm bg-white text-gray-900 px-4 py-2 rounded-lg font-medium hover:bg-gray-100 transition-colors"
            >
              Open Dashboard
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-24 pb-20">
        <div className="max-w-3xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium mb-6">
            <GitBranch size={12} /> Multi-Agent Architecture
          </div>
          <h1 className="text-5xl font-bold leading-tight tracking-tight">
            Support resolution
            <br />
            <span className="bg-gradient-to-r from-blue-400 to-violet-400 bg-clip-text text-transparent">
              powered by AI agents
            </span>
          </h1>
          <p className="mt-6 text-lg text-gray-400 leading-relaxed max-w-2xl">
            Five specialized agents collaborate to triage, investigate, and resolve customer
            support tickets — with full audit trails, human-in-the-loop approval, and
            tenant-isolated security.
          </p>
          <div className="mt-8 flex items-center gap-4">
            <Link
              href="/dashboard/"
              className="inline-flex items-center gap-2 bg-gradient-to-r from-blue-500 to-violet-600 text-white px-6 py-3 rounded-xl font-medium hover:opacity-90 transition-opacity"
            >
              Try Live Demo <ArrowRight size={16} />
            </Link>
            <Link
              href="https://github.com/DhrumilPanchal10/resolute"
              target="_blank"
              className="inline-flex items-center gap-2 border border-gray-700 text-gray-300 px-6 py-3 rounded-xl font-medium hover:border-gray-500 hover:text-white transition-colors"
            >
              View Source
            </Link>
          </div>
        </div>
      </section>

      {/* Agent Pipeline */}
      <section className="border-t border-gray-800/50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-2xl font-bold mb-3">Agent Pipeline</h2>
          <p className="text-gray-400 mb-10 max-w-2xl">
            Each ticket flows through a graph of specialists, with parallel fan-out for knowledge
            retrieval and investigation, a revision loop for quality, and approval gates for actions.
          </p>
          <div className="flex items-center gap-3 overflow-x-auto pb-4">
            {AGENTS.map((agent, i) => (
              <div key={agent.name} className="flex items-center gap-3 shrink-0">
                <div className="w-48 p-4 rounded-xl bg-gray-900 border border-gray-800">
                  <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${agent.color} flex items-center justify-center mb-3`}>
                    <span className="text-sm font-bold text-white">{i + 1}</span>
                  </div>
                  <p className="font-semibold text-sm">{agent.name}</p>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">{agent.desc}</p>
                </div>
                {i < AGENTS.length - 1 && (
                  <ArrowRight size={16} className="text-gray-700 shrink-0" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-gray-800/50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-2xl font-bold mb-3">Built for Production</h2>
          <p className="text-gray-400 mb-10 max-w-2xl">
            Every layer is designed for real-world deployment — not just a prototype.
          </p>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map(({ icon: Icon, title, desc }) => (
              <div
                key={title}
                className="p-5 rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 transition-colors"
              >
                <Icon size={20} className="text-blue-400 mb-3" />
                <h3 className="font-semibold text-sm mb-1.5">{title}</h3>
                <p className="text-xs text-gray-400 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Results */}
      <section className="border-t border-gray-800/50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-2xl font-bold mb-3">Evaluation Results</h2>
          <p className="text-gray-400 mb-10 max-w-2xl">
            All metrics pass CI gate thresholds. 421 tests, 100 scenarios, 150 adversarial tickets,
            50 gold-labeled judge calibration samples.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {RESULTS.map(({ metric, value, threshold }) => (
              <div
                key={metric}
                className="p-4 rounded-xl bg-gray-900 border border-gray-800 text-center"
              >
                <p className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-teal-300 bg-clip-text text-transparent">
                  {value}
                </p>
                <p className="text-xs text-gray-400 mt-1">{metric}</p>
                {threshold !== "—" && (
                  <div className="flex items-center justify-center gap-1 mt-2">
                    <CheckCircle size={10} className="text-emerald-500" />
                    <span className="text-[10px] text-emerald-500/70">
                      threshold: {threshold}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section className="border-t border-gray-800/50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-2xl font-bold mb-3">Architecture</h2>
          <p className="text-gray-400 mb-10 max-w-2xl">
            The full stack — from the Next.js frontend through the FastAPI backend to the LangGraph
            agent pipeline, MCP tool servers, and Postgres with row-level security.
          </p>
          <div className="rounded-xl bg-gray-900 border border-gray-800 p-6 font-mono text-xs text-gray-400 leading-relaxed overflow-x-auto">
            <pre>{`Next.js UI ──SSE──▶ FastAPI (JWT/RBAC) ──▶ LangGraph
                                            ├─ triage          (small model)
                                            ├─ knowledge ──┐   (parallel fan-out)
                                            ├─ investigator┘   (strong model)
                                            ├─ resolver        (strong model)
                                            ├─ verifier ──(revise ≤2)──▶ resolver
                                            └─ supervisor (budget + routing)
                                                   │
                    MCP servers (auth + audit per call):
                    github · docs · accounts · logs · stripe(test)
                                                   │
                    Postgres (RLS) · pgvector · Redis · Semantic cache
                                                   │
                    OpenTelemetry GenAI spans ──▶ Langfuse / Phoenix`}</pre>
          </div>
        </div>
      </section>

      {/* Tech Stack */}
      <section className="border-t border-gray-800/50 py-20">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-2xl font-bold mb-10">Tech Stack</h2>
          <div className="flex flex-wrap gap-3">
            {[
              "Python 3.12",
              "LangGraph",
              "FastAPI",
              "MCP SDK",
              "LiteLLM",
              "Gemini",
              "Pydantic",
              "PostgreSQL",
              "pgvector",
              "Redis",
              "OpenTelemetry",
              "Langfuse",
              "Next.js 16",
              "TypeScript",
              "Tailwind CSS",
              "Docker",
              "Terraform",
              "GitHub Actions",
            ].map((tech) => (
              <span
                key={tech}
                className="px-3 py-1.5 rounded-lg bg-gray-900 border border-gray-800 text-xs text-gray-300 font-medium"
              >
                {tech}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800/50 py-8">
        <div className="max-w-6xl mx-auto px-6 flex items-center justify-between text-xs text-gray-600">
          <p>Resolute — Multi-agent support resolution platform</p>
          <p>Built by Dhrumil Panchal</p>
        </div>
      </footer>
    </div>
  );
}
